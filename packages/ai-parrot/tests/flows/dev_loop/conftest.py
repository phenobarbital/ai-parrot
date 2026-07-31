"""Shared fixtures for the dev-loop test suite (TASK-888).

Also hosts the live-test skip guards + fixture repo used by the FEAT-250
end-to-end integration tests (``test_e2e_feat250.py``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    FlowtaskCriterion,
    LogSource,
    ResearchOutput,
    ShellCriterion,
)


# ---------------------------------------------------------------------------
# Live-test skip guards (FEAT-250 TASK-013)
# ---------------------------------------------------------------------------


@pytest.fixture
def skip_unless_claude_available():
    """Skip when the ``claude`` CLI or ``ANTHROPIC_API_KEY`` is missing."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set; live test skipped")
    if shutil.which("claude") is None:
        pytest.skip("`claude` CLI not on PATH; live test skipped")


@pytest.fixture
def skip_unless_github_available():
    """Skip when a GitHub token / target repo are not configured."""
    if not os.environ.get("GITHUB_TOKEN"):
        pytest.skip("GITHUB_TOKEN not set; live test skipped")
    if not os.environ.get("GITHUB_REPOSITORY"):
        pytest.skip("GITHUB_REPOSITORY not set; live test skipped")


@pytest.fixture
def skip_unless_private_repo_configured():
    """Skip the private-clone test unless a token + private slug are set."""
    if not os.environ.get("GITHUB_TOKEN"):
        pytest.skip("GITHUB_TOKEN not set; private-clone test skipped")
    if not os.environ.get("DEV_LOOP_TEST_PRIVATE_REPO"):
        pytest.skip(
            "DEV_LOOP_TEST_PRIVATE_REPO (owner/name) not set; "
            "private-clone test skipped"
        )


@pytest.fixture(autouse=True)
def _isolate_dev_loop_run_artifacts(tmp_path, monkeypatch) -> None:
    """Redirect ``DevLoopRunner``'s terminal-snapshot writes to a tmp dir.

    FEAT-322 TASK-1851: ``DevLoopRunner._close_host`` persists the terminal
    ``Snapshot`` under ``conf.OUTPUT_DIR/dev_loop_runs/`` on every completed
    run. Without this autouse guard, every test in this suite that drives a
    real run (not just the new host-lifecycle tests) would write JSON files
    into the actual repo's ``outputs/`` directory. Applied unconditionally
    to every test in the module so pre-existing tests stay side-effect-free.
    """
    monkeypatch.setattr(
        "parrot.flows.dev_loop.runner.conf.OUTPUT_DIR", str(tmp_path)
    )


@pytest.fixture
def temp_worktree_base(tmp_path, monkeypatch) -> Iterator[str]:
    """Point ``WORKTREE_BASE_PATH`` / ``DEV_LOOP_REPO_BASE_PATH`` at a tmp dir."""
    base = str(tmp_path)
    for target in (
        "parrot.flows.dev_loop.dispatcher.conf.WORKTREE_BASE_PATH",
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        "parrot.flows.dev_loop.nodes.research.conf.DEV_LOOP_REPO_BASE_PATH",
    ):
        try:
            monkeypatch.setattr(target, base)
        except AttributeError:  # pragma: no cover - attribute may not exist
            pass
    yield base


@pytest.fixture
def fixture_git_repo(tmp_path) -> str:
    """Create a disposable local git repo containing a deliberately broken file.

    Used as the fixture "codebase" for the initial-run / revision e2e tests so
    the flow has something concrete to fix.
    """
    repo = tmp_path / "fixture-repo"
    repo.mkdir()

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True
        )

    _git("init", "-q")
    _git("config", "user.email", "fixture@example.com")
    _git("config", "user.name", "fixture")
    (repo / "calc.py").write_text(
        "def add(a, b):\n    return a - b  # BUG: should be a + b\n"
    )
    _git("add", ".")
    _git("commit", "-qm", "initial (with bug)")
    return str(repo)


@pytest.fixture
def sample_bug_brief() -> BugBrief:
    """Canonical happy-path bug brief used across the suite."""
    return BugBrief(
        summary=(
            "Customer sync flowtask drops the last row when the input "
            "has >1000 records"
        ),
        affected_component="etl/customers/sync.yaml",
        log_sources=[
            LogSource(
                kind="cloudwatch",
                locator="/etl/prod/customers",
                time_window_minutes=120,
            )
        ],
        acceptance_criteria=[
            FlowtaskCriterion(
                name="customers-sync-passes",
                task_path="etl/customers/sync.yaml",
                expected_exit_code=0,
            ),
            ShellCriterion(name="lint-clean", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def sample_research_output() -> ResearchOutput:
    """Canonical research output used by Development / QA / Handoff tests."""
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix-customer-sync",
        worktree_path="/abs/.claude/worktrees/feat-130-fix-customer-sync",
        log_excerpts=[],
    )


@pytest.fixture
def fake_dispatch_messages():
    """Mimic ``ClaudeAgentClient.ask_stream`` output without the SDK.

    Returns three duck-typed messages: two ``_AssistantMessage``
    fragments concatenating into a valid ``ResearchOutput`` JSON, plus
    a final ``_ResultMessage``. No ``claude_agent_sdk`` import is
    triggered.
    """

    class _AssistantMessage:
        def __init__(self, content):
            self.content = content

    class _TextBlock:
        def __init__(self, text):
            self.text = text

    class _ResultMessage:
        def __init__(self, **kw):
            self.subtype = kw.get("subtype", "success")
            self.num_turns = kw.get("num_turns", 1)
            self.total_cost_usd = kw.get("total_cost_usd", 0.0)
            self.content = []

    return [
        _AssistantMessage(
            content=[
                _TextBlock(
                    text=(
                        '{"jira_issue_key":"OPS-1",'
                        '"spec_path":"sdd/specs/x.spec.md",'
                    )
                )
            ]
        ),
        _AssistantMessage(
            content=[
                _TextBlock(
                    text=(
                        '"feat_id":"FEAT-130",'
                        '"branch_name":"feat-130-fix",'
                        '"worktree_path":'
                        '"/abs/.claude/worktrees/feat-130-fix",'
                        '"log_excerpts":[]}'
                    )
                )
            ]
        ),
        _ResultMessage(),
    ]


@pytest.fixture
def mock_jira():
    """A pre-wired ``JiraToolkit`` mock for node tests."""
    j = MagicMock()
    j.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    j.jira_transition_to = AsyncMock(return_value={"ok": True})
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    j.jira_assign_issue = AsyncMock(return_value={"ok": True})
    return j


@pytest.fixture
def mock_dispatcher():
    """A pre-wired ``ClaudeCodeDispatcher`` mock for node tests."""
    d = MagicMock()
    d.dispatch = AsyncMock()
    return d
