"""
Task Tracker MCP Server
=======================
Extracts MAIN tasks (features & significant fixes) from git commits.

Supports:
  - Time-based queries: "today", "last week", "this month", or commit count
  - Any commit format: conventional, tagged, plain text, emoji, tickets
  - Scope-aware grouping: feat(auth) + fix(auth) = 1 task group
  - Merge/noise filtering: skips merges, tests, docs, lint, config, etc.
  - Branch and author filtering

Usage in Claude Code:
    "give tasks today"
    "give tasks last week"
    "give tasks 20"
    "give tasks today from main"
"""

import subprocess
import re
import os
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("task_tracker_mcp")


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ParsedCommit:
    """A single parsed commit with extracted metadata."""
    raw: str
    commit_type: str
    scope: Optional[str]
    description: str
    is_breaking: bool = False


@dataclass
class TaskGroup:
    """A group of related commits forming one logical task."""
    scope: str
    label: str
    description: str
    commit_count: int = 0
    has_feature: bool = False
    has_fix: bool = False
    descriptions: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# COMMIT PARSING
# ═══════════════════════════════════════════════════════════════════════════

SKIP_PATTERNS: list[re.Pattern] = [
    re.compile(r"^Merge\s+(branch|pull request|remote|tag|commit)", re.I),
    re.compile(r"^Merge\s+.+\s+into\s+", re.I),
    re.compile(r"^Merged\s+(PR|MR)\s*#?\d+", re.I),
    re.compile(r"^Auto-merge", re.I),
    re.compile(r"^Automatic merge", re.I),
    re.compile(r'^Revert\s+"?Merge', re.I),
    re.compile(r"^(bump|release)\s+v?\d+\.\d+", re.I),
    re.compile(r"^v?\d+\.\d+\.\d+\s*$"),
    re.compile(r"^Bump\s+\S+\s+from\s+\S+\s+to\s+", re.I),
    re.compile(r"^\s*$"),
    re.compile(r"^wip\s*$", re.I),
    re.compile(r"^(fixup|squash)!\s+", re.I),
    re.compile(r"^initial\s+commit\s*$", re.I),
]

CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|chore|refactor|docs|style|test|perf|ci|build|revert"
    r"|improvement|hotfix|bugfix|feature|update|cleanup|lint|format|release)"
    r"(?P<breaking>!)?"
    r"(?:\((?P<scope>[^)]+)\))?"
    r"\s*:\s*(?P<desc>.+)$",
    re.I,
)

TAGGED_RE = re.compile(r"^\[(?P<scope>[^\]]+)\]\s*(?P<desc>.+)$")

EMOJI_RE = re.compile(
    r"^(?:[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u26A0\u2728"
    r"\U0001F680\U0001F6A8\U0001F4DD\U0001F527\U0001F40E"
    r"\U0001F4A5\u267B\u2705\U0001F3A8\U0001F9EA\U0001F4E6"
    r"\U0001F6A7\U0001F4C7\U0001F4AC\U0001F389\u26D4"
    r"\U0001F6D1\u2B06\u2B07\U0001F504\U0001F525]+|"
    r":[a-z_]+:)\s*"
)

TICKET_RE = re.compile(r"^(?:[A-Z]{2,10}-\d+|#\d+)\s*:?\s*")

NOISE_TYPES = {
    "chore", "docs", "style", "test", "ci", "build", "lint", "format", "revert",
}

NOISE_DESC_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(add|write|update|fix)\s+(unit\s+)?tests?\b", re.I),
    re.compile(r"\btest\s+(for|coverage)\b", re.I),
    re.compile(r"\b(update|add|fix|improve)\s+(docs?|documentation|readme|comments?|changelog)\b", re.I),
    re.compile(r"\b(typo|spelling|grammar|wording)\b", re.I),
    re.compile(r"\b(lint|format|prettier|eslint|indent|whitespace)\b", re.I),
    re.compile(r"\b(config|tsconfig|webpack|vite|babel|eslintrc|gitignore|\.env)\b", re.I),
    re.compile(r"\b(update|bump|upgrade)\s+(deps?|dependencies|packages?)\b", re.I),
    re.compile(r"\b(rename|move|reorganize|restructure|cleanup|clean\s*up|tidy)\b", re.I),
    re.compile(r"\b(tweak|adjust|minor|small|tiny|slight)\b", re.I),
    re.compile(r"\b(fix\s+)?(import|export|type\s*error|missing\s+type)\b", re.I),
    re.compile(r"\b(changelog|release\s+notes|version)\b", re.I),
    re.compile(r"\b(add|remove)\s+(log|logging|console\.log|debug|print)\b", re.I),
    re.compile(r"\b(ci|cd|pipeline|github\s*actions?|workflow|dockerfile)\b", re.I),
    # Data entry / seed / config values — not real features
    re.compile(r"^add\s+\w*\s*values?\s*$", re.I),
    re.compile(r"^add\s+\w+\s+(uat|prod|staging|dev|test)\s+values?\s*$", re.I),
    re.compile(r"\b(seed|populate|insert|load)\s+(data|values|records|entries)\b", re.I),
    re.compile(r"^add\s+(data|entries|records|seed|samples?|defaults?|initial)\b", re.I),
    re.compile(r"\b(uat|staging|prod)\s+(values?|data|config|entries)\b", re.I),
]

MAJOR_FIX_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(security|vulnerability|xss|csrf|injection|exploit)\b", re.I),
    re.compile(r"\b(crash|critical|breaking|regression|data\s*loss)\b", re.I),
    re.compile(r"\b(race\s*condition|deadlock|memory\s*leak)\b", re.I),
    re.compile(r"\b(production|hotfix|emergency|urgent|outage)\b", re.I),
]


def _parse_commit(subject: str) -> Optional[ParsedCommit]:
    subject = subject.strip()
    if any(p.search(subject) for p in SKIP_PATTERNS):
        return None

    m = CONVENTIONAL_RE.match(subject)
    if m:
        return ParsedCommit(
            raw=subject,
            commit_type=m.group("type").lower(),
            scope=m.group("scope").strip().lower() if m.group("scope") else None,
            description=m.group("desc").strip(),
            is_breaking=bool(m.group("breaking")),
        )

    cleaned = EMOJI_RE.sub("", subject).strip()

    m = TAGGED_RE.match(cleaned)
    if m:
        return ParsedCommit(
            raw=subject, commit_type="feat",
            scope=m.group("scope").strip().lower(),
            description=m.group("desc").strip(),
        )

    cleaned = TICKET_RE.sub("", cleaned).strip()
    if not cleaned:
        return None

    first_word = cleaned.split()[0].lower() if cleaned else ""
    if first_word in ("fix", "fixed", "fixes", "fixing", "bugfix", "hotfix", "resolve", "resolved"):
        commit_type = "fix"
        desc = re.sub(r"^(fix(?:ed|es|ing)?|bugfix|hotfix|resolve[ds]?)\s*:?\s*", "", cleaned, flags=re.I)
    elif first_word in ("add", "added", "adding", "implement", "implemented", "create", "created",
                         "build", "built", "introduce", "introduced", "enable", "enabled", "integrate"):
        commit_type = "feat"
        desc = cleaned
    elif first_word in ("refactor", "refactored", "improve", "improved", "optimize", "optimized"):
        commit_type = "refactor"
        desc = cleaned
    else:
        commit_type = "unknown"
        desc = cleaned

    return ParsedCommit(raw=subject, commit_type=commit_type, scope=None, description=desc.strip())


def _is_noise(commit: ParsedCommit) -> bool:
    if commit.commit_type in NOISE_TYPES:
        return True
    combined = f"{commit.raw} {commit.description}"
    if any(p.search(combined) for p in NOISE_DESC_PATTERNS):
        return True

    # Low-quality description filter — catches "add values", "add X uat values", etc.
    # Even if prefixed with feat:, a vague 1-3 word description is not a real feature.
    if _is_trivial_description(commit.description):
        return True

    return False


def _is_trivial_description(desc: str) -> bool:
    """
    Reject descriptions that are too vague to be a real task.

    "add values"              → trivial (just data entry)
    "add aswan uat values"    → trivial (environment-specific data)
    "update values"           → trivial
    "add date range filters"  → NOT trivial (specific feature)
    """
    d = desc.strip().lower()
    words = d.split()

    # Less than 3 meaningful words = too vague
    stop_actions = {"add", "added", "update", "updated", "fix", "fixed", "remove", "removed",
                    "set", "change", "changed", "modify", "modified"}
    stop_nouns = {"values", "value", "data", "items", "stuff", "things", "files", "file",
                  "code", "changes", "content", "info", "entry", "entries", "record", "records"}
    stop_env = {"uat", "staging", "prod", "production", "dev", "development", "test", "testing",
                "local", "qa", "sandbox", "demo"}

    # Strip action word from front
    remaining = [w for w in words if w not in stop_actions]

    # If what remains is only stop nouns / env words, it's trivial
    meaningful = [w for w in remaining if w not in stop_nouns and w not in stop_env]

    # "add values" → remaining=["values"] → meaningful=[] → trivial
    # "add aswan uat values" → remaining=["aswan","uat","values"] → meaningful=["aswan"] → 1 word = trivial
    # "add date range filters" → remaining=["date","range","filters"] → meaningful=["date","range","filters"] → 3 = real
    if len(meaningful) < 2:
        return True

    # Very short total description (< 4 words including the verb) = probably trivial
    if len(words) <= 2:
        return True

    return False


def _is_significant_fix(commit: ParsedCommit) -> bool:
    combined = f"{commit.raw} {commit.description}"
    if commit.is_breaking:
        return True
    if any(p.search(combined) for p in MAJOR_FIX_PATTERNS):
        return True
    if commit.scope and commit.commit_type in ("fix", "bugfix", "hotfix"):
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# GROUPING
# ═══════════════════════════════════════════════════════════════════════════


def _clean_description(desc: str) -> str:
    desc = desc.strip()
    desc = re.sub(r"\s*\(?(?:[A-Z]{2,10}-\d+|#\d+)\)?\s*$", "", desc)
    desc = re.sub(r"\s*[,;]?\s*(?:closes?|fixes|resolves?)\s+.*$", "", desc, flags=re.I)
    if desc:
        desc = desc[0].upper() + desc[1:]
    desc = desc.rstrip(".,;:!- ")
    return desc


def _infer_scope(description: str, raw: str = "") -> str:
    """Infer scope from description when no explicit scope is given."""
    combined = f"{raw} {description}".lower()
    domain_keywords = {
        "auth": ["auth", "login", "signup", "register", "jwt", "token", "session", "password", "oauth", "sso"],
        "payment": ["payment", "checkout", "billing", "stripe", "invoice", "subscription", "cart", "order"],
        "dashboard": ["dashboard", "analytics", "chart", "metrics", "reporting", "admin", "panel", "stats"],
        "search": ["search", "elasticsearch", "autocomplete", "fuzzy", "filter"],
        "notification": ["notification", "email", "sms", "push", "alert"],
        "api": ["endpoint", "route", "handler", "controller", "middleware", "graphql", "rest"],
        "database": ["database", "migration", "schema", "table", "sql", "orm", "model"],
        "ui": ["component", "page", "layout", "screen", "form", "modal", "sidebar", "theme"],
        "infra": ["docker", "kubernetes", "deploy", "nginx", "redis", "cache", "queue", "websocket"],
        "user": ["user", "profile", "account", "role", "permission"],
        "report": ["report", "export", "csv", "pdf", "summary"],
    }
    for domain, keywords in domain_keywords.items():
        if any(kw in combined for kw in keywords):
            return domain
    words = re.findall(r"[a-z]{3,}", combined)
    stop = {"add", "fix", "update", "implement", "create", "remove", "handle",
            "the", "and", "for", "with", "from", "this", "that", "when", "show"}
    significant = [w for w in words if w not in stop][:2]
    return "-".join(significant) if significant else "general"


def _group_commits(commits: list[ParsedCommit]) -> list[TaskGroup]:
    groups: dict[str, TaskGroup] = {}

    for commit in commits:
        scope = commit.scope or _infer_scope(commit.description, commit.raw)

        if scope not in groups:
            groups[scope] = TaskGroup(
                scope=scope, label="Feature", description="", descriptions=[],
            )

        group = groups[scope]
        group.commit_count += 1
        clean_desc = _clean_description(commit.description)

        if commit.commit_type in ("feat", "feature"):
            group.has_feature = True
            group.descriptions.insert(0, clean_desc)
        elif commit.commit_type in ("fix", "bugfix", "hotfix"):
            group.has_fix = True
            group.descriptions.append(clean_desc)
        else:
            group.descriptions.append(clean_desc)

    results: list[TaskGroup] = []
    for scope, group in groups.items():
        if not group.descriptions:
            continue
        if group.has_feature and group.has_fix:
            group.label = "Feature"
        elif group.has_feature:
            group.label = "Feature"
        elif group.has_fix:
            group.label = "Fix"
        else:
            group.label = "Update"
        # Pick best description: feature descriptions are at front (insert(0,...))
        if group.has_feature:
            group.description = group.descriptions[0] if group.descriptions else ""
        else:
            group.description = max(group.descriptions, key=len) if group.descriptions else ""
        results.append(group)

    label_order = {"Feature": 0, "Fix": 1, "Update": 2}
    results.sort(key=lambda g: label_order.get(g.label, 9))
    return results


# ═══════════════════════════════════════════════════════════════════════════
# GIT HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _run_git(args: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git error: {result.stderr.strip()}")
    return result.stdout.strip()


def _get_repo_name(cwd: str) -> str:
    try:
        remote_url = _run_git(["config", "--get", "remote.origin.url"], cwd)
        name = remote_url.rstrip("/")
        if ":" in name and not name.startswith("http"):
            name = name.split(":")[-1]
        name = name.split("/")[-1]
        return name.removesuffix(".git")
    except RuntimeError:
        try:
            root = _run_git(["rev-parse", "--show-toplevel"], cwd)
            return os.path.basename(root)
        except RuntimeError:
            return "Unknown Project"


def _resolve_time_range(time_range: str) -> str:
    tr = time_range.strip().lower()
    now = datetime.now()

    simple_map = {
        "today": now.strftime("%Y-%m-%d 00:00:00"),
        "yesterday": (now - timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"),
        "last week": (now - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00"),
        "past week": (now - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00"),
        "this week": (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d 00:00:00"),
        "this month": now.strftime("%Y-%m-01 00:00:00"),
    }

    if tr in simple_map:
        return simple_map[tr]

    if tr in ("last month", "past month"):
        if now.month == 1:
            d = now.replace(year=now.year - 1, month=12, day=1)
        else:
            d = now.replace(month=now.month - 1, day=1)
        return d.strftime("%Y-%m-%d 00:00:00")

    m = re.match(r"last\s+(\d+)\s+(day|days|week|weeks|month|months)", tr)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip("s")
        if unit == "day":
            d = now - timedelta(days=n)
        elif unit == "week":
            d = now - timedelta(weeks=n)
        else:  # month
            d = now - timedelta(days=n * 30)
        return d.strftime("%Y-%m-%d 00:00:00")

    return time_range


# ═══════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════


def _get_tasks(
    cwd: str,
    count: Optional[int] = None,
    since: Optional[str] = None,
    author: Optional[str] = None,
    branch: Optional[str] = None,
) -> str:
    args = ["log", "--format=%s"]
    if branch: args.append(branch)
    if since: args.append(f"--since={since}")
    if count: args.append(f"-{count}")
    if author: args.append(f"--author={author}")
    if not count: args.append("-500")

    raw = _run_git(args, cwd)
    subjects = raw.split("\n") if raw else []

    if not subjects:
        return "No commits found in the specified range."

    project_name = _get_repo_name(cwd)

    # Phase 1: Parse
    parsed = [c for subj in subjects if (c := _parse_commit(subj))]

    if not parsed:
        return f"## {project_name}\n\nNo meaningful commits found (all were merges or auto-generated)."

    # Phase 2: Filter to significant
    significant: list[ParsedCommit] = []
    for commit in parsed:
        if _is_noise(commit):
            continue
        if commit.commit_type in ("feat", "feature"):
            significant.append(commit)
        elif commit.commit_type in ("fix", "bugfix", "hotfix"):
            if _is_significant_fix(commit):
                significant.append(commit)
        elif commit.commit_type == "unknown":
            first = commit.description.split()[0].lower() if commit.description else ""
            if first in ("add", "added", "implement", "create", "build", "introduce",
                         "enable", "integrate", "launch", "ship"):
                significant.append(commit)
        elif commit.commit_type == "refactor" and commit.scope:
            significant.append(commit)

    # Fallback
    if not significant:
        significant = [c for c in parsed if not _is_noise(c)]

    if not significant:
        return f"## {project_name}\n\nNo main tasks found — all commits were maintenance/noise."

    # Phase 3: Group
    groups = _group_commits(significant)
    if not groups:
        return f"## {project_name}\n\nNo main tasks found."

    # Phase 4: Format — clean task descriptions only
    lines: list[str] = []
    for group in groups:
        lines.append(f"- {group.description}")

    return f"## {project_name}\n\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# MCP TOOL
# ═══════════════════════════════════════════════════════════════════════════


class GetTasksInput(BaseModel):
    """Input for retrieving main tasks from git commits."""

    model_config = ConfigDict(
        str_strip_whitespace=True, validate_assignment=True, extra="forbid",
    )

    count: Optional[int] = Field(
        default=None,
        description=(
            "Number of recent commits to check. "
            "Use this OR time_range, not both. "
            "Example: 15 checks the last 15 commits."
        ),
        ge=1, le=500,
    )
    time_range: Optional[str] = Field(
        default=None,
        description=(
            "Time-based filter instead of commit count. "
            "Supports: 'today', 'yesterday', 'this week', 'last week', "
            "'this month', 'last month', 'last 3 days', 'last 2 weeks'. "
            "Use this OR count, not both."
        ),
    )
    path: Optional[str] = Field(
        default=None,
        description="Absolute path to the git repository. Defaults to cwd.",
    )
    author: Optional[str] = Field(
        default=None,
        description="Filter by author name or email. Example: 'John'",
    )
    branch: Optional[str] = Field(
        default=None,
        description="Git branch to read from. Defaults to current branch. Example: 'main'",
    )


@mcp.tool(
    name="task_tracker_get_tasks",
    annotations={
        "title": "Get Main Tasks from Git Commits",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def task_tracker_get_tasks(params: GetTasksInput) -> str:
    """Get ONLY main features and significant fixes from git commits.

    Supports time-based queries ('today', 'last week', 'this month') or
    commit count. Parses each commit's type (feat/fix/chore) and scope
    (the part in parentheses), filters out noise, groups related commits
    by scope, and returns only main tasks.

    Example: 15 commits about auth with feat + fix commits
    → returns 1 task: Add JWT authentication with refresh tokens

    Args:
        params: count OR time_range (at least one required), plus optional path/author/branch

    Returns:
        Markdown with project heading and main tasks
    """
    try:
        cwd = params.path or os.getcwd()
        _run_git(["rev-parse", "--is-inside-work-tree"], cwd)

        since = None
        if params.time_range:
            since = _resolve_time_range(params.time_range)

        if not params.count and not since:
            return "Error: Provide either a commit count or time range (e.g., 'today', 'last week')."

        return _get_tasks(cwd=cwd, count=params.count, since=since,
                          author=params.author, branch=params.branch)

    except FileNotFoundError:
        return "Error: git is not installed or not in PATH."
    except RuntimeError as e:
        msg = str(e)
        if "not a git repository" in msg.lower():
            return "Error: Not a git repository. Run from inside a git project or provide 'path'."
        return f"Error: {msg}"
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out."
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")