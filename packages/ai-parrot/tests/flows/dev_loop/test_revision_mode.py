"""Revision-mode run: node, flow, runner, webhook trigger (FEAT-250 TASK-012)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop.models import RevisionBrief
from parrot.flows.dev_loop.nodes.revision_handoff import RevisionHandoffNode
from parrot.flows.dev_loop.runner import (
    DevLoopRunner,
    build_dev_loop_revision_flow,
)
from parrot.flows.dev_loop.webhook import RevisionWebhookHandler


@pytest.fixture
def sample_revision_brief() -> RevisionBrief:
    return RevisionBrief(
        repo_path="/abs/.claude/worktrees/repos/run-x/navigator",
        branch="feat-251-fix-x",
        pr_number=42,
        repository="navigator-org/navigator",
        jira_issue_key="OPS-1",
        feedback="Please also handle the null case.",
        head_sha="deadbeef",
    )


# ── RevisionHandoffNode ────────────────────────────────────────────────


@pytest.fixture
def mock_git() -> MagicMock:
    g = MagicMock()
    g.add_pr_comment = AsyncMock(return_value={"id": "c1"})
    g.create_pull_request = AsyncMock()
    return g


@pytest.mark.asyncio
async def test_revision_handoff_no_new_pr(mock_git, monkeypatch):
    # Stub the git push subprocess so no real git runs.
    async def _ok_push(self, branch, cwd):
        return None

    monkeypatch.setattr(RevisionHandoffNode, "_push_branch", _ok_push)
    node = RevisionHandoffNode(mock_git)
    ctx = {
        "repo_path": "/abs/clone",
        "branch": "feat-251-fix-x",
        "pr_number": 42,
        "repository": "org/nav",
        "feedback": "fix null case",
    }
    out = await node.execute(ctx, deps=None)
    assert out["status"] == "revised"
    assert out["pr_number"] == 42
    assert ctx["mode"] == "revision"
    mock_git.add_pr_comment.assert_awaited_once()
    mock_git.create_pull_request.assert_not_called()


@pytest.mark.asyncio
async def test_revision_handoff_push_failure_blocks(mock_git, monkeypatch):
    async def _fail_push(self, branch, cwd):
        raise RuntimeError("push rejected")

    monkeypatch.setattr(RevisionHandoffNode, "_push_branch", _fail_push)
    node = RevisionHandoffNode(mock_git)
    out = await node.execute({"branch": "b", "repo_path": "/x", "pr_number": 1}, deps=None)
    assert out["status"] == "blocked"
    mock_git.add_pr_comment.assert_not_called()


# ── revision flow shape ────────────────────────────────────────────────


def test_revision_flow_enters_at_development():
    flow = build_dev_loop_revision_flow(
        dispatcher=MagicMock(), jira_toolkit=MagicMock(),
        git_toolkit=MagicMock(), redis_url="redis://x",
        publish_flow_events=False,
    )
    names = set(flow._nodes.keys())
    assert names == {"development", "qa", "revision_handoff", "failure_handler", "close"}
    # No intent/research/bug_intake nodes in the revision graph.
    assert "intent_classifier" not in names
    assert "research" not in names


# ── run_revision (end-to-end with stubbed node executes) ───────────────


@pytest.mark.asyncio
async def test_run_revision_enters_at_development(monkeypatch, sample_revision_brief):
    # Drive the REAL node executes with mocked dependencies (dispatcher/git/
    # jira) rather than monkeypatching class methods — this stays correct even
    # when an earlier test (test_lazy_import) re-imports the dev_loop package
    # and creates duplicate class identities.
    async def fake_dispatch(*, brief, profile, output_model, **kw):
        # Compare by NAME and build via the node's own ``output_model`` class so
        # this is immune to duplicate class identities from a module re-import.
        name = output_model.__name__
        if name == "DevelopmentOutput":
            return output_model(files_changed=[], commit_shas=[], summary="ok")
        if name == "QAReport":
            return output_model(passed=True, criterion_results=[], lint_passed=True)
        # sdd-codereview verdict — defaults to passed=True.
        return output_model()

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=fake_dispatch)
    git = MagicMock()
    git.add_pr_comment = AsyncMock(return_value={"id": "c1"})
    jira = MagicMock()
    jira.jira_add_comment = AsyncMock(return_value={})
    jira.jira_transition_issue = AsyncMock(return_value={})
    jira.jira_transition_to = AsyncMock(return_value={})

    # Fake the git push subprocess (success) — asyncio is global, so this is
    # immune to the dev_loop module re-import.
    class _Proc:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def _fake_exec(*a, **k):
        return _Proc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_exec)

    runner = DevLoopRunner(
        MagicMock(),  # initial flow unused by run_revision
        dispatcher=dispatcher, jira_toolkit=jira,
        git_toolkit=git, redis_url="redis://x",
    )
    result = await runner.run_revision(sample_revision_brief, run_id="rev-1")
    executed = set(result.responses)
    assert {"development", "qa", "revision_handoff", "close"}.issubset(executed)
    assert "intent_classifier" not in executed
    assert "research" not in executed
    # The revision handoff commented the EXISTING PR; no new PR was opened.
    git.add_pr_comment.assert_awaited_once()
    git.create_pull_request.assert_not_called()


@pytest.mark.asyncio
async def test_run_revision_requires_deps():
    runner = DevLoopRunner(MagicMock())  # no revision deps
    with pytest.raises(RuntimeError):
        await runner.run_revision(
            RevisionBrief(repo_path="/x", branch="b", pr_number=1,
                          repository="o/r", jira_issue_key="K-1",
                          feedback="f", head_sha="s")
        )


# ── webhook trigger filtering ──────────────────────────────────────────


def _handler(trigger="changes_requested", bot_login="flow-bot"):
    runner = MagicMock()
    runner.run_revision = AsyncMock(return_value="RESULT")
    return RevisionWebhookHandler(runner, trigger=trigger, bot_login=bot_login), runner


def _review_payload(**over):
    base = {
        "pr_number": 42, "branch": "feat-251-x", "repository": "o/r",
        "head_sha": "abc", "author": "alice", "review_state": "changes_requested",
        "body": "please fix",
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_revision_trigger_filters_bot_comments():
    handler, runner = _handler()
    out = await handler.handle_event(
        "github.pr_review", _review_payload(author="flow-bot")
    )
    assert out is None
    runner.run_revision.assert_not_called()


@pytest.mark.asyncio
async def test_changes_requested_only_fires_on_change_requests():
    handler, runner = _handler()
    # a plain comment (pr_comment) does not fire under changes_requested
    out = await handler.handle_event("github.pr_comment", _review_payload(review_state=None))
    assert out is None
    # an approving review does not fire either
    out = await handler.handle_event("github.pr_review", _review_payload(review_state="approved"))
    assert out is None
    # a change-requesting review fires
    out = await handler.handle_event("github.pr_review", _review_payload())
    assert out == "RESULT"
    runner.run_revision.assert_awaited_once()


@pytest.mark.asyncio
async def test_revision_dedup_by_head_sha():
    handler, runner = _handler()
    await handler.handle_event("github.pr_review", _review_payload(head_sha="same"))
    await handler.handle_event("github.pr_review", _review_payload(head_sha="same"))
    assert runner.run_revision.await_count == 1


@pytest.mark.asyncio
async def test_command_trigger_requires_revise_prefix():
    handler, runner = _handler(trigger="command")
    out = await handler.handle_event(
        "github.pr_comment",
        _review_payload(review_state=None, body="looks good"),
    )
    assert out is None
    out = await handler.handle_event(
        "github.pr_comment",
        _review_payload(review_state=None, body="/revise add a guard", head_sha="z"),
    )
    assert out == "RESULT"
