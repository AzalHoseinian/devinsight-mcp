# DevInsight MCP

<!-- mcp-name: io.github.AzalHoseinian/devinsight-mcp -->

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/devinsight-mcp.svg)](https://pypi.org/project/devinsight-mcp/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-compatible-6E56CF.svg)](https://modelcontextprotocol.io)
[![Tests](https://github.com/AzalHoseinian/devinsight-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/AzalHoseinian/devinsight-mcp/actions/workflows/test.yml)

> A lightweight [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that gives Claude the ability to inspect, analyze, and grade local Git repositories.

Built with Anthropic's official Python MCP SDK, DevInsight demonstrates all three MCP primitives — **Tools**, **Resources**, and **Prompts** — through practical developer workflows: language stats, TODO tracking, git history, large-file detection, an overall repo health score, and technology-stack fingerprinting.

---

## Demo

![DevInsight demo](docs/demo.gif)

*A live session driving the DevInsight tools against this very repository — repo stats, TODO scan, and large-file detection.*

---

## ✨ Features

- 📊 Repository statistics — languages, file counts, line counts
- 📝 Scan projects for `TODO`, `FIXME`, `HACK`, and `XXX`
- 📜 Summarize recent Git commits (author, date, message, +/- lines)
- 📁 Detect oversized source files that are due for a refactor
- 🩺 Score overall repository health (README/LICENSE/tests/git, TODO density, file size) with concrete recommendations
- 🧰 Fingerprint a project's tech stack — languages, frameworks, databases, package managers, CI/CD, deployment
- 🌳 Browse repositories through an MCP Resource
- 🤖 Review and prioritize TODOs using an MCP Prompt

Scanning automatically skips noise: `.git`, `.github`, `node_modules`, virtualenvs, build/cache directories, lock files, and binary assets — see [Repository Scanning](#repository-scanning) below.

---

## Why DevInsight?

Developers spend a surprising amount of time manually inspecting repositories:

- searching for TODOs
- checking Git history
- counting files
- finding oversized modules
- judging whether a project is in good shape before diving in

DevInsight exposes these tasks as MCP tools so Claude can perform them for you, directly in conversation.

Instead of manually searching your project, you can simply ask:

> "Summarize the last 10 commits."

> "Find every TODO and tell me which ones are most important."

> "Which files are becoming too large?"

> "How healthy is this repo, and what should I fix first?"

> "What's the tech stack of this project?"

---

## Installation

### Install from PyPI (easiest)

```bash
pip install devinsight-mcp
devinsight-mcp        # runs the server over stdio
```

Or run it without installing, using [uv](https://docs.astral.sh/uv/):

```bash
uvx devinsight-mcp
```

### From source (development)

#### Clone the repository

```bash
git clone https://github.com/AzalHoseinian/devinsight-mcp.git
cd devinsight-mcp
```

#### Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows:

```bash
.venv\Scripts\activate
```

#### Install dependencies

```bash
pip install -r requirements.txt
```

#### Run the tests

```bash
pip install pytest
python -m pytest -q
```

#### Try it with the MCP Inspector

The easiest way to test the server standalone is with the official MCP Inspector:

```bash
mcp dev server.py
```

The Inspector lets you invoke every Tool, inspect Resources, test Prompts, and debug raw responses — all in the browser, no client app required.

---

## Claude Desktop Setup

Add DevInsight to your `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

**Easiest (uses `uvx`):**

```json
{
  "mcpServers": {
    "devinsight": {
      "command": "uvx",
      "args": ["devinsight-mcp"]
    }
  }
}
```

**From a clone:**

```json
{
  "mcpServers": {
    "devinsight": {
      "command": "/absolute/path/to/devinsight-mcp/.venv/bin/python3",
      "args": [
        "/absolute/path/to/devinsight-mcp/server.py"
      ]
    }
  }
}
```

If you installed the command with `pip install .` or `pip install devinsight-mcp`, you can point Claude Desktop at it instead:

```json
{
  "mcpServers": {
    "devinsight": {
      "command": "/absolute/path/to/devinsight-mcp/.venv/bin/devinsight-mcp"
    }
  }
}
```

Using the virtual environment's Python interpreter (rather than a bare `python`) ensures Claude Desktop finds the `mcp` package regardless of what's active in your shell.

Fully **quit and reopen** Claude Desktop afterwards — it only reads this file on startup. Then try:

> Use `repo_stats` on ~/projects/my-app

or

> Review all TODOs in this repository.

---

## Security notes

DevInsight is **read-only**: it never writes, deletes or executes anything from the repositories it scans. The only external command it runs is `git log` with a fixed argument list.

It can, however, read **any path you give it** that your user account can read, so only connect it to clients you trust. It does not follow symlinked directories when drawing the tree, and it skips lock files and binaries in statistics.

---

## Available Tools

| Primitive | Name | Purpose |
|------------|------|---------|
| **Tool** | `repo_stats` | Language and line-count breakdown |
| **Tool** | `find_todos` | Find TODO / FIXME / HACK / XXX comments |
| **Tool** | `git_log_summary` | Summarize recent Git activity |
| **Tool** | `find_large_files` | Detect files exceeding a configurable size |
| **Tool** | `repo_health` | Overall 0-100 health score with recommendations |
| **Tool** | `tech_stack` | Detect languages, frameworks, databases, package managers, CI/CD, deployment |
| **Resource** | `repo://tree/{path}` | Render the repository tree |
| **Prompt** | `review_todos` | Ask Claude to prioritize TODOs |

### Usage examples

```text
repo_stats(path="~/projects/my-app")
→ { "total_files": 142, "total_lines": 18734,
    "by_extension": { ".ts": {...}, ".tsx": {...}, ... } }

find_todos(path=".", max_results=50)
→ [ { "file": "src/api.ts", "line_number": 42,
      "tag": "TODO", "text": "handle retry backoff" }, ... ]

git_log_summary(path=".", count=5)
→ { "commits": [ { "hash": "a1b2c3d4", "author": "...", 
      "date": "2026-07-10", "message": "...", 
      "insertions": 12, "deletions": 3 }, ... ] }

find_large_files(path=".", threshold_lines=300)
→ [ { "file": "src/legacy/parser.py", "lines": 812 }, ... ]

repo_health(path=".")
→ { "score": 78,
    "checks": { "has_git": true, "has_readme": true,
                "has_license": true, "has_tests": false },
    "recommendations": [ "Add a test suite ..." ] }

tech_stack(path=".")
→ { "languages": ["Python"], "frameworks": ["FastAPI"],
    "databases": ["PostgreSQL"], "package_managers": ["pip"],
    "ci_cd": ["GitHub Actions"], "deployment": ["Docker"] }
```

---

## Repository Scanning

Statistics tools (`repo_stats`, `find_todos`, `find_large_files`, `repo_health`) walk the repo while pruning directories as they go — ignored subtrees are never descended into.

**Ignored directories:** `.git`, `.github`, `node_modules`, `venv`, `.venv`, `env`, `__pycache__`, `dist`, `build`, `.next`, `.nuxt`, `.svelte-kit`, `.idea`, `.vscode`, `target`, `coverage`, `htmlcov`, `.pytest_cache`, `.mypy_cache`, `.cache`

**Excluded from statistics:** lock files (`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `poetry.lock`, `Cargo.lock`, `Gemfile.lock`, `composer.lock`, `uv.lock`, `bun.lockb`) and binary assets (`.png`, `.jpg`, `.jpeg`, `.gif`, `.pdf`, `.zip`, `.exe`, `.dll`) — these are real project content, but noise in line/size stats.

`tech_stack` looks at these same files directly, since a lock file's mere *presence* is a useful package-manager signal.

---

# Architecture

```text
               Claude Desktop
                      │
                      ▼
             DevInsight MCP Server
                      │
      ┌───────────────┼───────────────┐
      ▼               ▼               ▼
 Git Repository   File System     Git History
```

---

# Project Structure

```text
devinsight-mcp/
├── devinsight_mcp.py      # implementation (installed as the `devinsight-mcp` command)
├── server.py              # thin launcher for `mcp dev server.py`
├── tests/
├── .github/workflows/test.yml
├── pytest.ini
├── requirements.txt
├── pyproject.toml
├── README.md
├── docs/
│   ├── demo.gif
│   ├── demo.tape
│   └── demo_cli.py
└── .gitignore
```

---

# Roadmap

- [x] Repository statistics
- [x] TODO scanner
- [x] Git history summaries
- [x] Large file detection
- [x] Repository tree resource
- [x] TODO review prompt
- [x] Overall repo health score
- [x] Tech stack detection
- [x] Test suite and CI
- [ ] Optional allowlist of readable root directories
- [ ] Lint summary tool
- [ ] GitHub Issues integration
- [ ] Dependency vulnerability analysis
- [ ] Pull request insights

---

# Tech Stack

- Python
- Anthropic MCP Python SDK
- Git
- Claude Desktop
- Model Context Protocol (MCP)

---

# Contributing

Contributions, suggestions, and feedback are welcome.

If you'd like to improve DevInsight, feel free to open an issue or submit a pull request.

---

# License

MIT — see [LICENSE](LICENSE).
