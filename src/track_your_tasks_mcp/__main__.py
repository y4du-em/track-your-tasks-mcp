"""Entry point for `python -m task_tracker_mcp`."""

from task_tracker_mcp.server import mcp

def main() -> None:
    """Run the MCP server."""
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()