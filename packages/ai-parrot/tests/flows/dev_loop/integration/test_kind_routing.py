"""FEAT-132 integration smoke tests — kind-based routing (TASK-903).

Three live tests that verify the full issuetype-routing + plan-summary
path against a real Jira sandbox and Anthropic key. All three tests
skip cleanly when the required environment variables are absent, so
they can live in CI without a live environment.

Run manually when you have credentials:

    pytest packages/ai-parrot/tests/flows/dev_loop/integration/ \
           -m live -v --no-header

Marks ``live`` is registered in ``pytest.ini``; use ``-m "not live"``
for the standard suite.
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    IntentClassifierNode,
    ShellCriterion,
    WorkBrief,
)
from parrot.flows.dev_loop.nodes.research import ResearchNode

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Skip helpers
# ---------------------------------------------------------------------------


def _need_env(*names: str) -> None:
    """Skip the current test if any of *names* is unset in the environment."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        pytest.skip(f"missing env vars: {missing!r} — set them for live tests")


def _smoke_brief(kind: str, suffix: str = "") -> WorkBrief:
    """Build a minimal WorkBrief with a unique smoke-test summary.

    The summary is unique per invocation so ``_find_existing_issue``
    never false-matches a prior test run's ticket. The `feat-132-smoke`
    prefix is recognisable — clean up manually after live runs if needed.
    """
    unique = uuid.uuid4().hex[:8]
    return WorkBrief(
        kind=kind,
        summary=f"feat-132-smoke-{unique}{suffix} — automated test, safe to close",
        affected_component="tests/flows/dev_loop/integration",
        acceptance_criteria=[
            ShellCriterion(name="lint", command="ruff check ."),
        ],
        escalation_assignee=os.environ.get("FLOW_BOT_JIRA_ACCOUNT_ID", ""),
        reporter=os.environ.get("FLOW_BOT_JIRA_ACCOUNT_ID", ""),
    )


def _build_mock_jira() -> MagicMock:
    """Minimal JiraToolkit mock that records calls for assertion."""
    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(
        return_value={"key": f"SMOKE-{uuid.uuid4().hex[:4].upper()}"}
    )
    jira.jira_add_comment = AsyncMock(return_value={"id": "c-1"})
    jira.jira_search_issues = AsyncMock(return_value={"issues": []})
    jira._resolve_account_id = AsyncMock(side_effect=lambda v: v)
    return jira


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_end_to_end_bug_kind_creates_bug_ticket(
    skip_unless_redis_available, monkeypatch, tmp_path
):
    """kind='bug' results in jira_create_issue called with issuetype='Bug'.

    This is a semi-live test: it uses real ResearchNode logic but a mock
    Jira toolkit and a mock dispatcher so no real tickets are created or
    ``claude`` calls are made. The test is still gated behind
    ``skip_unless_redis_available`` to stay consistent with the rest of
    the integration suite.
    """
    _need_env("ANTHROPIC_API_KEY")
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )

    from parrot.flows.dev_loop.models import ResearchOutput
    brief = _smoke_brief("bug")
    jira = _build_mock_jira()

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        return_value=ResearchOutput(
            jira_issue_key=jira.jira_create_issue.return_value["key"],
            spec_path="sdd/specs/smoke.spec.md",
            feat_id="FEAT-999",
            branch_name=f"feat-999-smoke-{uuid.uuid4().hex[:6]}",
            worktree_path=str(tmp_path / "feat-999-smoke"),
            log_excerpts=[],
        )
    )

    node = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
    )
    # Inject a pre-built plan client so no LLM call is made.
    node._plan_client = MagicMock()
    node._plan_client.ask = AsyncMock(
        return_value=MagicMock(response="Smoke plan step 1.")
    )

    await node.execute("", {"bug_brief": brief, "run_id": "smoke-bug-1"})

    kwargs = jira.jira_create_issue.call_args.kwargs
    assert kwargs["issuetype"] == "Bug", (
        f"Expected issuetype='Bug' for kind='bug', got {kwargs['issuetype']!r}"
    )


async def test_end_to_end_enhancement_kind_creates_story_ticket(
    skip_unless_redis_available, monkeypatch, tmp_path
):
    """kind='enhancement' results in jira_create_issue called with issuetype='Story'."""
    _need_env("ANTHROPIC_API_KEY")
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )

    from parrot.flows.dev_loop.models import ResearchOutput
    brief = _smoke_brief("enhancement")
    jira = _build_mock_jira()

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        return_value=ResearchOutput(
            jira_issue_key=jira.jira_create_issue.return_value["key"],
            spec_path="sdd/specs/smoke.spec.md",
            feat_id="FEAT-999",
            branch_name=f"feat-999-smoke-{uuid.uuid4().hex[:6]}",
            worktree_path=str(tmp_path / "feat-999-smoke"),
            log_excerpts=[],
        )
    )

    node = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
    )
    node._plan_client = MagicMock()
    node._plan_client.ask = AsyncMock(
        return_value=MagicMock(response="Smoke enhancement plan.")
    )

    await node.execute("", {"bug_brief": brief, "run_id": "smoke-enh-1"})

    kwargs = jira.jira_create_issue.call_args.kwargs
    assert kwargs["issuetype"] == "Story", (
        f"Expected issuetype='Story' for kind='enhancement', got {kwargs['issuetype']!r}"
    )


async def test_end_to_end_reused_ticket_skips_plan_comment(
    skip_unless_redis_available, monkeypatch, tmp_path
):
    """When existing_issue_key is set, no 'Plan for run-' comment is posted."""
    _need_env("ANTHROPIC_API_KEY")
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )

    from parrot.flows.dev_loop.models import ResearchOutput
    # Provide an existing_issue_key to force the reuse path.
    brief = _smoke_brief("bug").model_copy(
        update={"existing_issue_key": "SMOKE-REUSE-99"}
    )
    jira = _build_mock_jira()
    jira.jira_get_issue = AsyncMock(return_value={"key": "SMOKE-REUSE-99"})
    # jira_create_issue must NOT be called on the reuse path.
    jira.jira_create_issue = AsyncMock(
        side_effect=AssertionError(
            "jira_create_issue must not be called on reuse path"
        )
    )

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        return_value=ResearchOutput(
            jira_issue_key="SMOKE-REUSE-99",
            spec_path="sdd/specs/smoke.spec.md",
            feat_id="FEAT-999",
            branch_name=f"feat-999-smoke-reuse-{uuid.uuid4().hex[:6]}",
            worktree_path=str(tmp_path / "feat-999-smoke-reuse"),
            log_excerpts=[],
        )
    )

    node = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
    )

    await node.execute("", {"bug_brief": brief, "run_id": "smoke-reuse-1"})

    # Assert no plan-summary comment was posted.
    bodies = [c.kwargs.get("body", "") for c in jira.jira_add_comment.call_args_list]
    plan_comments = [b for b in bodies if b.startswith("Plan for run-")]
    assert not plan_comments, (
        f"Expected no plan-summary comment on reuse path, got: {plan_comments!r}"
    )
