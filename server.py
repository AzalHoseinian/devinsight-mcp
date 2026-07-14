"""
DevInsight MCP Server
======================
An MCP (Model Context Protocol) server that gives Claude (or any MCP client)
the ability to inspect a local git repository: language/line stats, TODO/FIXME
tracking, recent commit history, and files that are getting too large.

Built with the official Python SDK (FastMCP). Demonstrates all three core
MCP primitives:
  - Tools:    repo_stats, find_todos, git_log_summary, find_large_files,
              repo_health, tech_stack
  - Resource: repo://tree/{path}  (dynamic directory tree)
  - Prompt:   review_todos        (turns raw TODOs into a prioritized prompt)

Run locally with the MCP Inspector:
    mcp dev server.py

Or run directly (stdio transport, for use with Claude Desktop / other clients):
    python server.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("DevInsight")

# ----------------------------------------------------------------------------
# Config: directories we never want to walk into, and what counts as "code"
# ----------------------------------------------------------------------------

IGNORED_DIRS = {
    ".git", ".github", "node_modules", "venv", ".venv", "env",
    "__pycache__", "dist", "build", ".next", ".nuxt", ".svelte-kit",
    ".idea", ".vscode", "target", "coverage", "htmlcov",
    ".pytest_cache", ".mypy_cache", ".cache",
}

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rs", ".swift", ".kt", ".html",
    ".css", ".scss", ".vue", ".sh", ".sql", ".yaml", ".yml", ".json",
}

TODO_TAGS = ("TODO", "FIXME", "HACK", "XXX")

# Lock files and binary assets: real project content, but noise in line/size
# statistics — excluded from _iter_files, which feeds repo_stats, find_todos,
# find_large_files, and repo_health. tech_stack looks for these by name
# separately, since their *presence* is a useful package-manager signal.
LOCK_FILENAMES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock",
    "cargo.lock", "gemfile.lock", "composer.lock", "uv.lock", "bun.lockb",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".exe", ".dll",
}

# ----------------------------------------------------------------------------
# Config: tech_stack detection tables
# ----------------------------------------------------------------------------

# filename -> {category: [tags]}, for manifests whose mere presence is a signal.
MANIFEST_SIGNALS: dict[str, dict[str, list[str]]] = {
    "pyproject.toml": {"languages": ["Python"]},
    "requirements.txt": {"languages": ["Python"], "package_managers": ["pip"]},
    "Pipfile": {"languages": ["Python"], "package_managers": ["Pipenv"]},
    "poetry.lock": {"package_managers": ["Poetry"]},
    "environment.yml": {"languages": ["Python"], "package_managers": ["Conda"]},
    "package.json": {"languages": ["JavaScript/TypeScript"]},
    "package-lock.json": {"package_managers": ["npm"]},
    "yarn.lock": {"package_managers": ["Yarn"]},
    "pnpm-lock.yaml": {"package_managers": ["pnpm"]},
    "bun.lockb": {"package_managers": ["Bun"]},
    "tsconfig.json": {"languages": ["TypeScript"]},
    "Cargo.toml": {"languages": ["Rust"], "package_managers": ["Cargo"]},
    "go.mod": {"languages": ["Go"], "package_managers": ["Go Modules"]},
    "composer.json": {"languages": ["PHP"], "package_managers": ["Composer"]},
    "build.gradle": {"languages": ["Java/Kotlin"], "package_managers": ["Gradle"]},
    "build.gradle.kts": {"languages": ["Kotlin"], "package_managers": ["Gradle"]},
    "pom.xml": {"languages": ["Java"], "package_managers": ["Maven"]},
    "Gemfile": {"languages": ["Ruby"], "package_managers": ["Bundler"]},
    "Dockerfile": {"deployment": ["Docker"]},
    "docker-compose.yml": {"deployment": ["Docker Compose"]},
    "docker-compose.yaml": {"deployment": ["Docker Compose"]},
    "Procfile": {"deployment": ["Heroku"]},
    "vercel.json": {"deployment": ["Vercel"]},
    "netlify.toml": {"deployment": ["Netlify"]},
    "serverless.yml": {"deployment": ["Serverless Framework"]},
    "kustomization.yaml": {"deployment": ["Kubernetes"]},
    ".gitlab-ci.yml": {"ci_cd": ["GitLab CI"]},
    "Jenkinsfile": {"ci_cd": ["Jenkins"]},
    ".travis.yml": {"ci_cd": ["Travis CI"]},
    "azure-pipelines.yml": {"ci_cd": ["Azure Pipelines"]},
}

# dependency/package name -> human-readable tag, checked against parsed
# manifest contents (package.json deps, requirements.txt lines, etc).
FRAMEWORK_PACKAGE_MAP = {
    "react": "React", "react-dom": "React", "next": "Next.js",
    "vue": "Vue.js", "nuxt": "Nuxt.js", "svelte": "Svelte",
    "@angular/core": "Angular", "express": "Express", "@nestjs/core": "NestJS",
    "gatsby": "Gatsby", "tailwindcss": "Tailwind CSS", "vite": "Vite",
    "fastapi": "FastAPI", "django": "Django", "flask": "Flask",
    "mcp": "MCP (Model Context Protocol)", "celery": "Celery",
    "sqlalchemy": "SQLAlchemy", "rails": "Ruby on Rails",
    "laravel/framework": "Laravel",
}

DATABASE_PACKAGE_MAP = {
    "psycopg2": "PostgreSQL", "psycopg2-binary": "PostgreSQL", "pg": "PostgreSQL",
    "mysqlclient": "MySQL", "pymysql": "MySQL", "mysql2": "MySQL",
    "pymongo": "MongoDB", "mongoose": "MongoDB",
    "redis": "Redis", "ioredis": "Redis",
}


def _iter_files(root: Path):
    """Yield every file under root, pruning ignored directories and
    skipping lock files / binary assets that don't belong in stats."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in filenames:
            if name.lower() in LOCK_FILENAMES:
                continue
            if Path(name).suffix.lower() in BINARY_EXTENSIONS:
                continue
            yield Path(dirpath) / name


def _safe_read_lines(path: Path) -> Optional[list[str]]:
    """Read a file as text lines, returning None if it looks like binary."""
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as f:
            return f.readlines()
    except (UnicodeDecodeError, PermissionError, OSError):
        return None


# ----------------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------------

@mcp.tool()
def repo_stats(path: str = ".") -> dict:
    """
    Get a language and size breakdown for a local repository.

    Args:
        path: Filesystem path to the repo root (default: current directory).

    Returns:
        Dict with total_files, total_lines, and a per-extension breakdown
        (files + lines), sorted by line count descending.
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return {"error": f"Path does not exist: {root}"}

    by_ext: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "lines": 0})
    total_files = 0
    total_lines = 0

    for file in _iter_files(root):
        ext = file.suffix or "(no extension)"
        lines = _safe_read_lines(file)
        if lines is None:
            continue
        total_files += 1
        total_lines += len(lines)
        by_ext[ext]["files"] += 1
        by_ext[ext]["lines"] += len(lines)

    sorted_ext = dict(
        sorted(by_ext.items(), key=lambda kv: kv[1]["lines"], reverse=True)
    )

    return {
        "root": str(root),
        "total_files": total_files,
        "total_lines": total_lines,
        "by_extension": sorted_ext,
    }


@mcp.tool()
def find_todos(path: str = ".", max_results: int = 100) -> list[dict]:
    """
    Scan a repo for TODO / FIXME / HACK / XXX comments.

    Args:
        path: Filesystem path to the repo root.
        max_results: Cap on how many matches to return (default 100).

    Returns:
        List of {file, line_number, tag, text} dicts, one per match found.
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return [{"error": f"Path does not exist: {root}"}]

    results = []
    for file in _iter_files(root):
        if file.suffix not in CODE_EXTENSIONS:
            continue
        lines = _safe_read_lines(file)
        if lines is None:
            continue
        for i, line in enumerate(lines, start=1):
            for tag in TODO_TAGS:
                if tag in line:
                    results.append({
                        "file": str(file.relative_to(root)),
                        "line_number": i,
                        "tag": tag,
                        "text": line.strip()[:200],
                    })
                    break
            if len(results) >= max_results:
                return results
    return results


@mcp.tool()
def git_log_summary(path: str = ".", count: int = 10) -> dict:
    """
    Summarize the most recent git commits in a repo: author, date, message,
    and how many lines were added/removed.

    Args:
        path: Filesystem path to the repo root (must be a git repo).
        count: How many recent commits to include (default 10).

    Returns:
        Dict with a list of commits, or an error if this isn't a git repo.
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return {"error": f"Path does not exist: {root}"}

    try:
        raw = subprocess.run(
            [
                "git", "-C", str(root), "log",
                f"-{count}",
                "--pretty=format:%H|%an|%ad|%s",
                "--date=short",
                "--shortstat",
            ],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return {"error": f"Not a git repo, or git is unavailable: {e}"}

    commits = []
    current = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line and line.count("|") >= 3:
            if current:
                commits.append(current)
            commit_hash, author, date, message = line.split("|", 3)
            current = {
                "hash": commit_hash[:8],
                "author": author,
                "date": date,
                "message": message,
                "insertions": 0,
                "deletions": 0,
            }
        elif current is not None and "changed" in line:
            for chunk in line.split(","):
                chunk = chunk.strip()
                if "insertion" in chunk:
                    current["insertions"] = int(chunk.split()[0])
                elif "deletion" in chunk:
                    current["deletions"] = int(chunk.split()[0])
    if current:
        commits.append(current)

    return {"root": str(root), "commit_count": len(commits), "commits": commits}


@mcp.tool()
def find_large_files(path: str = ".", threshold_lines: int = 300, top_n: int = 10) -> list[dict]:
    """
    Flag source files that are unusually large — often a signal they're due
    for a refactor or split.

    Args:
        path: Filesystem path to the repo root.
        threshold_lines: Minimum line count to be flagged (default 300).
        top_n: Max number of files to return, largest first (default 10).

    Returns:
        List of {file, lines} dicts, sorted largest first.
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return [{"error": f"Path does not exist: {root}"}]

    flagged = []
    for file in _iter_files(root):
        if file.suffix not in CODE_EXTENSIONS:
            continue
        lines = _safe_read_lines(file)
        if lines is None:
            continue
        if len(lines) >= threshold_lines:
            flagged.append({"file": str(file.relative_to(root)), "lines": len(lines)})

    flagged.sort(key=lambda x: x["lines"], reverse=True)
    return flagged[:top_n]


README_NAMES = {"readme.md", "readme.rst", "readme.txt", "readme"}
LICENSE_NAMES = {
    "license", "license.md", "license.txt",
    "licence", "licence.md", "licence.txt",
    "copying", "copying.md",
}
TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec", "specs"}


def _has_root_file(root: Path, names: set[str]) -> bool:
    for entry in root.iterdir():
        if entry.is_file() and entry.name.lower() in names:
            return True
    return False


def _looks_like_test_file(rel_path: Path) -> bool:
    if any(part.lower() in TEST_DIR_NAMES for part in rel_path.parts[:-1]):
        return True
    stem = rel_path.stem.lower()
    return stem.startswith("test_") or stem.endswith("_test") or stem.endswith(".test") or stem.endswith(".spec")


@mcp.tool()
def repo_health(path: str = ".", large_file_threshold: int = 300) -> dict:
    """
    Give a repository an overall health score with supporting evidence.

    Checks for a README, a LICENSE, a test suite, and Git version control,
    plus TODO density and oversized files, then rolls it all into a single
    0-100 score with concrete recommendations.

    Args:
        path: Filesystem path to the repo root.
        large_file_threshold: Line count above which a file counts as "large".

    Returns:
        Dict with score, component checks, counts, largest_files, and
        a list of recommendations for the lowest-scoring areas.
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return {"error": f"Path does not exist: {root}"}

    source_files = 0
    source_lines = 0
    todo_count = 0
    has_tests = False
    large_files: list[dict] = []

    for file in _iter_files(root):
        rel = file.relative_to(root)
        if _looks_like_test_file(rel):
            has_tests = True
        if file.suffix not in CODE_EXTENSIONS:
            continue
        lines = _safe_read_lines(file)
        if lines is None:
            continue
        source_files += 1
        source_lines += len(lines)
        if len(lines) >= large_file_threshold:
            large_files.append({"file": str(rel), "lines": len(lines)})
        for line in lines:
            if any(tag in line for tag in TODO_TAGS):
                todo_count += 1

    large_files.sort(key=lambda x: x["lines"], reverse=True)

    has_readme = _has_root_file(root, README_NAMES)
    has_license = _has_root_file(root, LICENSE_NAMES)
    has_git = (root / ".git").is_dir()

    todo_density = todo_count / max(source_lines / 1000, 1e-9)
    if todo_density <= 1:
        todo_score = 20
    elif todo_density <= 3:
        todo_score = 15
    elif todo_density <= 6:
        todo_score = 10
    elif todo_density <= 10:
        todo_score = 5
    else:
        todo_score = 0

    large_file_ratio = len(large_files) / max(source_files, 1)
    if not large_files:
        size_score = 20
    elif large_file_ratio <= 0.02:
        size_score = 15
    elif large_file_ratio <= 0.05:
        size_score = 10
    elif large_file_ratio <= 0.10:
        size_score = 5
    else:
        size_score = 0

    score = (
        (15 if has_git else 0)
        + (15 if has_readme else 0)
        + (10 if has_license else 0)
        + (20 if has_tests else 0)
        + todo_score
        + size_score
    )

    recommendations = []
    if not has_git:
        recommendations.append("Initialize Git version control (git init) to track history.")
    if not has_readme:
        recommendations.append("Add a README describing what the project does and how to run it.")
    if not has_license:
        recommendations.append("Add a LICENSE file to clarify how others may use this code.")
    if not has_tests:
        recommendations.append("Add a test suite (e.g. a tests/ directory) — none was detected.")
    if todo_score < 15:
        recommendations.append(
            f"Reduce TODO/FIXME/HACK/XXX density ({todo_count} found) — work through the backlog."
        )
    if size_score < 15:
        recommendations.append(
            f"Split up the {len(large_files)} file(s) over {large_file_threshold} lines — "
            "large files are harder to review and maintain."
        )

    return {
        "root": str(root),
        "score": score,
        "checks": {
            "has_git": has_git,
            "has_readme": has_readme,
            "has_license": has_license,
            "has_tests": has_tests,
        },
        "source_files": source_files,
        "source_lines": source_lines,
        "todo_count": todo_count,
        "largest_files": large_files[:5],
        "recommendations": recommendations or ["Looks healthy — no major gaps detected."],
    }


def _split_requirement_name(line: str) -> Optional[str]:
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    name = re.split(r"[<>=!~;\[\s]", line, maxsplit=1)[0].strip()
    return name or None


def _match_packages(names: list[str], frameworks: set[str], databases: set[str]) -> None:
    for name in names:
        key = name.strip().lower()
        if key in FRAMEWORK_PACKAGE_MAP:
            frameworks.add(FRAMEWORK_PACKAGE_MAP[key])
        if key in DATABASE_PACKAGE_MAP:
            databases.add(DATABASE_PACKAGE_MAP[key])


@mcp.tool()
def tech_stack(path: str = ".") -> dict:
    """
    Detect a project's technology stack from its manifest and config files.

    Looks for common manifests (pyproject.toml, requirements.txt,
    package.json, Dockerfile, docker-compose.yml, GitHub Actions workflows,
    Cargo.toml, go.mod, composer.json, build.gradle, and more), and inspects
    package.json / requirements.txt contents for known frameworks and
    databases.

    Args:
        path: Filesystem path to the repo root.

    Returns:
        Dict with sorted lists for languages, frameworks, databases,
        package_managers, ci_cd, and deployment, plus the manifest files
        that were found.
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return {"error": f"Path does not exist: {root}"}

    languages: set[str] = set()
    frameworks: set[str] = set()
    databases: set[str] = set()
    package_managers: set[str] = set()
    ci_cd: set[str] = set()
    deployment: set[str] = set()
    found_manifests: list[str] = []

    try:
        entries = {p.name: p for p in root.iterdir() if p.is_file()}
    except PermissionError:
        entries = {}

    for filename, signal in MANIFEST_SIGNALS.items():
        if filename not in entries:
            continue
        found_manifests.append(filename)
        languages.update(signal.get("languages", []))
        package_managers.update(signal.get("package_managers", []))
        ci_cd.update(signal.get("ci_cd", []))
        deployment.update(signal.get("deployment", []))

    for suffix, lang in {".csproj": "C#/.NET", ".sln": "C#/.NET"}.items():
        if any(f.endswith(suffix) for f in entries):
            languages.add(lang)

    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.is_dir() and any(workflows_dir.glob("*.y*ml")):
        ci_cd.add("GitHub Actions")
        found_manifests.append(".github/workflows/")

    package_json = entries.get("package.json")
    if package_json is not None:
        text = _safe_read_lines(package_json)
        if text is not None:
            try:
                data = json.loads("".join(text))
                deps = list(data.get("dependencies", {}).keys()) + list(
                    data.get("devDependencies", {}).keys()
                )
                _match_packages(deps, frameworks, databases)
                if package_managers.isdisjoint({"npm", "Yarn", "pnpm", "Bun"}):
                    package_managers.add("npm")
            except json.JSONDecodeError:
                pass

    requirements_txt = entries.get("requirements.txt")
    if requirements_txt is not None:
        lines = _safe_read_lines(requirements_txt) or []
        names = [n for n in (_split_requirement_name(l) for l in lines) if n]
        _match_packages(names, frameworks, databases)

    pyproject = entries.get("pyproject.toml")
    if pyproject is not None:
        lines = _safe_read_lines(pyproject) or []
        blob = "".join(lines).lower()
        for key, tag in FRAMEWORK_PACKAGE_MAP.items():
            if key in blob:
                frameworks.add(tag)
        for key, tag in DATABASE_PACKAGE_MAP.items():
            if key in blob:
                databases.add(tag)

    return {
        "root": str(root),
        "languages": sorted(languages),
        "frameworks": sorted(frameworks),
        "databases": sorted(databases),
        "package_managers": sorted(package_managers),
        "ci_cd": sorted(ci_cd),
        "deployment": sorted(deployment),
        "manifests_found": sorted(found_manifests),
    }


# ----------------------------------------------------------------------------
# Resource: exposes a directory tree as browsable, read-only context
# ----------------------------------------------------------------------------

@mcp.resource("repo://tree/{path}")
def repo_tree(path: str) -> str:
    """Return an indented directory tree for the given repo path."""
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return f"Path does not exist: {root}"

    lines = [str(root)]

    def walk(dir_path: Path, prefix: str = ""):
        try:
            entries = sorted(
                [p for p in dir_path.iterdir() if p.name not in IGNORED_DIRS],
                key=lambda p: (p.is_file(), p.name.lower()),
            )
        except PermissionError:
            return
        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if i == len(entries) - 1 else "│   "
                walk(entry, prefix + extension)

    walk(root)
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Prompt: turns raw find_todos() output into a structured review prompt
# ----------------------------------------------------------------------------

@mcp.prompt()
def review_todos(repo_path: str = ".") -> str:
    """
    Build a prompt asking Claude to triage this repo's TODOs by urgency
    and suggest which ones to tackle first.
    """
    return (
        f"Run find_todos on '{repo_path}', then group the results into "
        "Critical / Nice-to-have / Stale categories. For each Critical item, "
        "suggest a one-sentence plan to resolve it. Keep the whole response "
        "under 200 words."
    )


if __name__ == "__main__":
    mcp.run()
