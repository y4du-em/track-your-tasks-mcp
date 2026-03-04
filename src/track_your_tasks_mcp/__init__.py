"""
task-tracker-mcp: Extract main tasks from git commit history.

An MCP server for Claude Code that reads your git commits, filters out
noise (merges, tests, docs, config), groups related commits by scope,
and surfaces only the main features and significant fixes.
"""

__version__ = "0.1.0"