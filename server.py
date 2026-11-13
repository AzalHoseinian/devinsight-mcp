"""Thin launcher kept so `mcp dev server.py` and existing Claude Desktop configs keep working.

The implementation lives in devinsight_mcp.py (installed as the `devinsight-mcp` command).
"""

from devinsight_mcp import main, mcp  # noqa: F401  (`mcp` is what `mcp dev` looks for)

if __name__ == "__main__":
    main()
