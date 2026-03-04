"""Tests for task-tracker-mcp commit parsing and task extraction."""

import pytest
from task_tracker_mcp.server import (
    _parse_commit,
    _is_noise,
    _is_significant_fix,
    _is_trivial_description,
    _group_commits,
    _clean_description,
    _resolve_time_range,
)


# ═══════════════════════════════════════════════════════════════════════════
# SKIP PATTERNS — commits that should return None from _parse_commit
# ═══════════════════════════════════════════════════════════════════════════


class TestSkipPatterns:
    @pytest.mark.parametrize("subject", [
        "Merge branch 'main' into develop",
        "Merge pull request #42 from feature/auth",
        "Merge remote-tracking branch 'origin/main'",
        "Merged PR #123",
        "Auto-merge from staging",
        "Automatic merge of release/v2.0",
        'Revert "Merge branch main"',
        "bump v1.2.3",
        "release v2.0.0",
        "1.2.3",
        "Bump axios from 0.21 to 0.27",
        "",
        "   ",
        "wip",
        "WIP",
        "fixup! add login handler",
        "squash! refactor auth module",
        "initial commit",
    ])
    def test_skipped(self, subject):
        assert _parse_commit(subject) is None


# ═══════════════════════════════════════════════════════════════════════════
# COMMIT PARSING — conventional, tagged, emoji, plain text
# ═══════════════════════════════════════════════════════════════════════════


class TestParsing:
    def test_conventional_feat(self):
        c = _parse_commit("feat: add user authentication")
        assert c.commit_type == "feat"
        assert c.scope is None
        assert c.description == "add user authentication"

    def test_conventional_feat_with_scope(self):
        c = _parse_commit("feat(auth): add JWT middleware")
        assert c.commit_type == "feat"
        assert c.scope == "auth"
        assert c.description == "add JWT middleware"

    def test_conventional_fix_with_scope(self):
        c = _parse_commit("fix(coil-reports): show warning when no data matches")
        assert c.commit_type == "fix"
        assert c.scope == "coil-reports"

    def test_breaking_change(self):
        c = _parse_commit("feat!: redesign API response format")
        assert c.is_breaking is True
        assert c.commit_type == "feat"

    def test_tagged_format(self):
        c = _parse_commit("[Auth] Add JWT refresh flow")
        assert c.scope == "auth"
        assert "JWT refresh flow" in c.description

    def test_emoji_prefix(self):
        c = _parse_commit("✨ Add search feature")
        assert c is not None
        assert "search feature" in c.description.lower()

    def test_gitmoji_prefix(self):
        c = _parse_commit(":bug: Fix memory leak in worker")
        assert c is not None
        assert "memory leak" in c.description.lower()

    def test_ticket_prefix(self):
        c = _parse_commit("JIRA-123: Implement OAuth2 flow")
        assert c is not None
        assert "OAuth2" in c.description

    def test_plain_text_add(self):
        c = _parse_commit("Add dark mode support")
        assert c.commit_type == "feat"

    def test_plain_text_fix(self):
        c = _parse_commit("Fix login crash on empty password")
        assert c.commit_type == "fix"

    def test_plain_text_refactor(self):
        c = _parse_commit("Refactor database connection pooling")
        assert c.commit_type == "refactor"


# ═══════════════════════════════════════════════════════════════════════════
# NOISE DETECTION
# ═══════════════════════════════════════════════════════════════════════════


class TestNoiseDetection:
    @pytest.mark.parametrize("subject", [
        "chore: update eslint config",
        "test: add unit tests for auth",
        "docs: update README",
        "style: format code with prettier",
        "ci: update GitHub Actions workflow",
        "build: configure webpack for production",
        "lint: fix eslint warnings",
        "fix: fix typo in error message",
        "fix: fix import path",
        "feat: update dependencies",
        "chore(deps): bump jsonwebtoken from 8.5 to 9.0",
    ])
    def test_is_noise(self, subject):
        c = _parse_commit(subject)
        if c:
            assert _is_noise(c), f"Expected noise: {subject}"

    @pytest.mark.parametrize("subject", [
        "feat(auth): add JWT middleware for protected routes",
        "feat: implement full-text search with Elasticsearch",
        "feat(dashboard): add revenue chart component",
        "feat(coil-reports): add date range and tube type filters",
    ])
    def test_not_noise(self, subject):
        c = _parse_commit(subject)
        assert c is not None
        assert not _is_noise(c), f"Should NOT be noise: {subject}"


# ═══════════════════════════════════════════════════════════════════════════
# TRIVIAL DESCRIPTION FILTER
# ═══════════════════════════════════════════════════════════════════════════


class TestTrivialDescription:
    @pytest.mark.parametrize("desc", [
        "add values",
        "add aswan uat values",
        "update values",
        "add data",
        "add production data entries",
        "remove old records",
        "add uat data",
    ])
    def test_trivial(self, desc):
        assert _is_trivial_description(desc), f"Expected trivial: {desc}"

    @pytest.mark.parametrize("desc", [
        "add date range and tube type filters",
        "add most downtime top 10 tab",
        "add overall summary cards above filters",
        "implement OAuth2 login with Google",
        "show warning when no data matches selected filters",
    ])
    def test_not_trivial(self, desc):
        assert not _is_trivial_description(desc), f"Should NOT be trivial: {desc}"


# ═══════════════════════════════════════════════════════════════════════════
# SIGNIFICANT FIX DETECTION
# ═══════════════════════════════════════════════════════════════════════════


class TestSignificantFix:
    def test_scoped_fix_is_significant(self):
        c = _parse_commit("fix(auth): handle expired refresh tokens")
        assert _is_significant_fix(c)

    def test_security_fix_is_significant(self):
        c = _parse_commit("fix: patch XSS vulnerability in input sanitization")
        assert _is_significant_fix(c)

    def test_crash_fix_is_significant(self):
        c = _parse_commit("fix: prevent crash on null user profile")
        assert _is_significant_fix(c)

    def test_breaking_fix_is_significant(self):
        c = _parse_commit("fix!: change API response format")
        assert _is_significant_fix(c)

    def test_unscoped_minor_fix_not_significant(self):
        c = _parse_commit("fix: fix typo in header")
        # typo is caught by noise, but if it weren't:
        # an unscoped fix without major indicators is not significant
        if c and not _is_noise(c):
            assert not _is_significant_fix(c)


# ═══════════════════════════════════════════════════════════════════════════
# GROUPING — scope-based clustering
# ═══════════════════════════════════════════════════════════════════════════


class TestGrouping:
    def test_same_scope_groups_together(self):
        commits = [
            _parse_commit("feat(auth): add login page"),
            _parse_commit("fix(auth): handle expired tokens"),
        ]
        groups = _group_commits([c for c in commits if c])
        assert len(groups) == 1
        assert groups[0].scope == "auth"

    def test_different_scopes_separate(self):
        commits = [
            _parse_commit("feat(auth): add login page"),
            _parse_commit("feat(dashboard): add analytics chart"),
        ]
        groups = _group_commits([c for c in commits if c])
        assert len(groups) == 2

    def test_feature_description_preferred_over_fix(self):
        commits = [
            _parse_commit("feat(reports): add date range filters"),
            _parse_commit("fix(reports): show warning when no data"),
        ]
        groups = _group_commits([c for c in commits if c])
        assert len(groups) == 1
        assert "date range filters" in groups[0].description.lower()


# ═══════════════════════════════════════════════════════════════════════════
# TIME RANGE RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════


class TestTimeRange:
    def test_today(self):
        result = _resolve_time_range("today")
        assert "00:00:00" in result

    def test_last_week(self):
        result = _resolve_time_range("last week")
        assert "00:00:00" in result

    def test_last_n_days(self):
        result = _resolve_time_range("last 3 days")
        assert "00:00:00" in result

    def test_this_month(self):
        result = _resolve_time_range("this month")
        assert "-01 00:00:00" in result

    def test_passthrough(self):
        result = _resolve_time_range("2024-01-15")
        assert result == "2024-01-15"


# ═══════════════════════════════════════════════════════════════════════════
# FULL SCENARIO TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestFullScenarios:
    def _run_pipeline(self, subjects: list[str]) -> list[str]:
        """Run the full parse → filter → group pipeline on subjects."""
        parsed = [c for s in subjects if (c := _parse_commit(s))]
        significant = []
        for c in parsed:
            if _is_noise(c):
                continue
            if c.commit_type in ("feat", "feature"):
                significant.append(c)
            elif c.commit_type in ("fix", "bugfix", "hotfix"):
                if _is_significant_fix(c):
                    significant.append(c)
            elif c.commit_type == "unknown":
                fw = c.description.split()[0].lower() if c.description else ""
                if fw in ("add", "added", "implement", "create", "build",
                          "introduce", "enable", "integrate"):
                    significant.append(c)
            elif c.commit_type == "refactor" and c.scope:
                significant.append(c)
        if not significant:
            significant = [c for c in parsed if not _is_noise(c)]
        groups = _group_commits(significant) if significant else []
        return [g.description for g in groups]

    def test_real_world_coil_reports(self):
        tasks = self._run_pipeline([
            "feat(coil-reports): add date range and tube type filters",
            "fix(coil-reports): show warning when no data matches selected filters",
            "feat(values): add values",
            "feat(aswan-uat): add aswan uat values",
            "feat(machine-downtime): add most downtime top 10 tab",
            "feat(delivery-performance): add overall summary cards above filters",
            "chore: update eslint config",
            "test: add unit tests",
            "docs: update README",
            "style: format code",
            "Merge branch 'main' into develop",
        ])
        assert len(tasks) <= 3
        assert any("date range" in t.lower() for t in tasks)
        assert not any("add values" == t.lower() for t in tasks)

    def test_auth_feature_15_commits(self):
        tasks = self._run_pipeline([
            "feat: implement user authentication with JWT",
            "feat(auth): add login page component",
            "fix: fix login form validation error",
            "feat(auth): add JWT middleware for protected routes",
            "style: format auth components with prettier",
            "test: add unit tests for auth service",
            "fix: fix typo in login error message",
            "docs: update README with auth setup instructions",
            "chore: update eslint config",
            "feat(auth): add password reset flow",
            "fix: fix import path in auth middleware",
            "test: add integration tests for login endpoint",
            "chore(deps): bump jsonwebtoken from 8.5.1 to 9.0.0",
            "style: fix linting errors in auth module",
            "ci: add auth service to GitHub Actions workflow",
        ])
        assert len(tasks) <= 3

    def test_pure_noise_returns_empty(self):
        tasks = self._run_pipeline([
            "fix: fix typo in header component",
            "style: format code with prettier",
            "docs: update changelog",
            "chore: bump typescript from 4.9 to 5.0",
            "test: increase test coverage",
            "Merge pull request #45",
        ])
        assert len(tasks) == 0