import os
import subprocess

import devinsight_mcp as server


def test_find_todos_uses_word_boundaries(tmp_path):
    (tmp_path / "a.py").write_text("# TODO: real\nTODOS = []\nx = MYTODO\n# FIXME later\n")
    tags = [r["tag"] for r in server.find_todos(str(tmp_path))]
    assert tags == ["TODO", "FIXME"]


def test_repo_health_counts_same_todos(tmp_path):
    (tmp_path / "a.py").write_text("# TODO: real\nTODOS = []\n")
    assert server.repo_health(str(tmp_path))["todo_count"] == 1


def test_repo_stats_ignores_node_modules(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "b.js").write_text("y = 2\n")
    assert server.repo_stats(str(tmp_path))["total_files"] == 1


def test_missing_path_returns_error(tmp_path):
    assert "error" in server.repo_stats(str(tmp_path / "nope"))


def test_repo_tree_survives_symlink_loop(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    os.symlink(tmp_path, d / "loop")
    assert "loop" in server.repo_tree(str(tmp_path))


def test_git_log_summary_clamps_count(tmp_path):
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"]}
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "f.txt").write_text("hi\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "a | b"], check=True, env=env)
    out = server.git_log_summary(str(tmp_path), count=-5)
    assert out["commit_count"] == 1
    assert out["commits"][0]["message"] == "a | b"


def test_tech_stack_detects_python_and_mcp(tmp_path):
    (tmp_path / "requirements.txt").write_text("mcp[cli]>=1.2.0\n")
    result = server.tech_stack(str(tmp_path))
    assert "Python" in result["languages"]
    assert "MCP (Model Context Protocol)" in result["frameworks"]
