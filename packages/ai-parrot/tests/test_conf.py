"""Default-value tests for parrot.conf settings (TASK-876).

Verifies that the six dev-loop settings introduced by FEAT-129 resolve to
their documented defaults when no environment overrides are set.
"""

from __future__ import annotations

from parrot import conf


class TestDevLoopSettingsDefaults:
    def test_concurrency_defaults(self):
        assert conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES == 3
        assert conf.FLOW_MAX_CONCURRENT_RUNS == 5

    def test_jira_account_default_empty(self):
        assert conf.FLOW_BOT_JIRA_ACCOUNT_ID == ""

    def test_worktree_base_path_default(self):
        assert conf.WORKTREE_BASE_PATH == ".claude/worktrees"

    def test_stream_ttl_default_seven_days(self):
        assert conf.FLOW_STREAM_TTL_SECONDS == 604800

    def test_acceptance_allowlist_default(self):
        assert conf.ACCEPTANCE_CRITERION_ALLOWLIST == [
            "flowtask",
            "pytest",
            "ruff",
            "mypy",
            "pylint",
        ]
