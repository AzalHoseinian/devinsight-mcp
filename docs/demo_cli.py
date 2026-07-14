"""
Tiny CLI used only to record the README demo GIF.
Drives the real DevInsight tool functions against this repo and
prints results the way Claude would relay them in a chat.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import repo_stats, find_todos, find_large_files  # noqa: E402


def slow_print(text: str, delay: float = 0.015) -> None:
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def main() -> None:
    root = str(Path(__file__).resolve().parent.parent)

    slow_print("$ Ask Claude: \"Give me repo stats for devinsight-mcp\"")
    time.sleep(0.4)
    print(json.dumps(repo_stats(root), indent=2))
    time.sleep(1.2)

    slow_print("\n$ Ask Claude: \"Find TODOs in this repo\"")
    time.sleep(0.4)
    print(json.dumps(find_todos(root)[:3], indent=2))
    time.sleep(1.2)

    slow_print("\n$ Ask Claude: \"Any files getting too large?\"")
    time.sleep(0.4)
    print(json.dumps(find_large_files(root, threshold_lines=50), indent=2))
    time.sleep(1.0)


if __name__ == "__main__":
    main()
