# task-tracker-mcp

An MCP server for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that extracts **main tasks** from your git commit history.

Instead of listing every commit, it filters out noise (merges, tests, docs, config, linting, typos), groups related commits by scope, and surfaces only the features and significant fixes.

## Example

15 commits in your repo:

```
feat(auth): add JWT middleware for protected routes
feat(auth): add login page component
feat(auth): add password reset flow
fix(auth): handle expired refresh tokens
test: add unit tests for auth service
fix: fix typo in login error message
docs: update README with auth setup instructions
chore: update eslint config
style: format auth components with prettier
fix: fix import path in auth middleware
test: add integration tests for login endpoint
chore(deps): bump jsonwebtoken from 8.5.1 to 9.0.0
style: fix linting errors in auth module
ci: add auth service to GitHub Actions workflow
Merge branch 'main' into feature/auth
```

Ask Claude Code: `"give tasks 15"`

Output:

```
## my-project

- Add password reset flow
```

12 noise commits filtered. 3 auth features grouped into 1 task.

## Install

### From PyPI (one command)

```bash
claude mcp add task-tracker -- uvx task-tracker-mcp
```

### From source

```bash
git clone https://github.com/y4du-em/task-tracker-mcp.git
cd task-tracker-mcp
claude mcp add task-tracker -- uv run --with mcp --with pydantic src/task_tracker_mcp/server.py
```

### Verify

```bash
claude mcp list
```

## Usage

Inside Claude Code, in any git repository:

```
give tasks today
give tasks last week
give tasks this month
give tasks 20
give tasks today from main
give tasks last week by author "john"
```

### Supported time ranges

| Query | What it fetches |
|-------|----------------|
| `today` | Since midnight today |
| `yesterday` | Since midnight yesterday |
| `this week` | Since Monday of current week |
| `last week` | Last 7 days |
| `this month` | Since 1st of current month |
| `last month` | Since 1st of previous month |
| `last 3 days` | Last 3 days |
| `last 2 weeks` | Last 14 days |

### Parameters

| Parameter | Description |
|-----------|-------------|
| `count` | Number of recent commits (e.g., 15) |
| `time_range` | Time-based filter (e.g., "today") |
| `branch` | Branch to read from (default: current) |
| `author` | Filter by commit author |
| `path` | Path to git repo (default: cwd) |

## What Gets Filtered

**Automatically skipped** (not even parsed):
- Merge commits (`Merge branch`, `Merge pull request`)
- Version bumps (`bump v1.2.3`, `release v2.0`)
- Dependency bot commits (`Bump axios from 0.21 to 0.27`)
- WIP, fixup, squash commits
- Empty messages

**Classified as noise** (parsed but filtered out):
- Tests: `test: add unit tests`, `add integration tests`
- Docs: `docs: update README`, `update changelog`
- Style: `style: format code`, `fix linting errors`
- Config: `chore: update eslint config`, `update .env`
- CI/CD: `ci: update GitHub Actions`, `add Dockerfile`
- Trivial: `fix: fix typo`, `fix import path`
- Data entry: `feat(values): add values`, `add uat data`

**Kept as tasks:**
- Features: `feat(auth): add JWT middleware`
- Significant fixes: `fix(auth): handle expired tokens`, `fix: XSS vulnerability`
- Breaking changes: `feat!: redesign API response format`

## How Grouping Works

Commits sharing the same **scope** (the part in parentheses) are grouped:

```
feat(auth): add login page          ─┐
feat(auth): add JWT middleware        ├─→ 1 task: "Add JWT middleware"
fix(auth): handle expired tokens     ─┘
feat(dashboard): add revenue chart   ───→ 1 task: "Add revenue chart"
```

When a group has both features and fixes, the feature description is used as the representative.

For commits without explicit scope, the server infers scope from keywords in the description (auth, payment, dashboard, search, etc.).

## Commit Formats Supported

| Format | Example |
|--------|---------|
| Conventional | `feat: add user authentication` |
| Scoped | `fix(auth): resolve token expiry bug` |
| Breaking | `feat!: redesign API response format` |
| Tagged | `[Auth] Add JWT refresh flow` |
| Plain text | `Add dark mode support` |
| Emoji | `✨ Add new search feature` |
| Gitmoji | `:bug: Fix memory leak in worker` |
| Ticket prefix | `JIRA-123: Implement OAuth2 flow` |

## Development

```bash
git clone https://github.com/y4du-em/task-tracker-mcp.git
cd task-tracker-mcp
pip install -e .
pytest tests/
```

## Uninstall

```bash
claude mcp remove task-tracker
pip uninstall task-tracker-mcp
```

## License

MIT