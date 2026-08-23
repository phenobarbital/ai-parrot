"""Unit tests for parrot.flows.dev_loop.nodes.feature_handoff (TASK-1924)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop.models import (
    CriterionResult,
    DevelopmentOutput,
    FeedbackDecision,
    PlannerOutput,
    QAReport,
    SynthesisReport,
)
from parrot.flows.dev_loop.nodes.feature_handoff import FeatureHandoffNode
from parrot.flows.dev_loop.session_state import SessionHost


@pytest.fixture
def planner_out(tmp_path) -> PlannerOutput:
    return PlannerOutput(
        spec_path="sdd/specs/my-feature.spec.md",
        task_index_path=str(tmp_path / "sdd/tasks/index/my-feature.json"),
        feat_id="FEAT-999",
        branch_name="feat-999-my-feature",
        worktree_path=str(tmp_path),
        jira_issue_key=None,
    )


@pytest.fixture
def ctx(planner_out) -> dict:
    return {
        "run_id": "r1",
        "planner_output": planner_out,
        "development_output": DevelopmentOutput(
            files_changed=["a.py", "b.py"], commit_shas=["abc"], summary="implemented"
        ),
        "synthesis_report": SynthesisReport(
            consistent=True, adjustments=["fixed import"], summary="clean"
        ),
        "qa_report": QAReport(
            passed=True,
            criterion_results=[
                CriterionResult(
                    name="c1", kind="shell", exit_code=0,
                    duration_seconds=0.1, passed=True,
                )
            ],
            lint_passed=True,
        ),
    }


def _node(**kwargs) -> FeatureHandoffNode:
    return FeatureHandoffNode(**kwargs)


async def _ok_git(self, cwd, *args):
    return ""


def _patch_gh_available(monkeypatch, available: bool):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.feature_handoff.FeatureHandoffNode._gh_available",
        lambda self: available,
    )


def _patch_instant_sleep(monkeypatch):
    async def _instant_sleep(delay):
        return None

    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.feature_handoff.asyncio.sleep", _instant_sleep
    )


async def test_happy_path_draft_pr_and_docs(ctx, monkeypatch):
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, True)

    async def _fake_gh_create(self, branch, title, body):
        return "https://github.com/x/y/pull/7"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _fake_gh_create)

    node = _node()
    result = await node.execute(ctx)

    assert result["status"] == "ready_to_deploy"
    assert result["pr_url"] == "https://github.com/x/y/pull/7"
    assert result["pr_number"] == 7
    assert result["docs_path"] == "docs/features/feat-999-my-feature.md"
    assert result["wiki_page_id"] is None  # ingest off by default


async def test_never_merges(ctx, monkeypatch):
    """No git-merge verb is ever issued across a full run."""
    recorded_git_calls: list[tuple] = []

    async def _recording_git(self, cwd, *args):
        recorded_git_calls.append(args)
        return ""

    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _recording_git)
    _patch_gh_available(monkeypatch, True)

    async def _fake_gh_create(self, branch, title, body):
        return "https://github.com/x/y/pull/7"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _fake_gh_create)

    node = _node()
    await node.execute(ctx)

    for call_args in recorded_git_calls:
        assert "merge" not in call_args


async def test_create_pr_with_gh_never_issues_merge(monkeypatch):
    """The real (unmocked) ``_create_pr_with_gh`` subprocess invocation is
    always "pr create", never "pr merge"."""
    captured_argv: list[str] = []

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return b"https://github.com/x/y/pull/1\n", b""

    async def _fake_exec(*argv, **kwargs):
        captured_argv.extend(argv)
        return _FakeProc()

    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.feature_handoff.asyncio.create_subprocess_exec",
        _fake_exec,
    )
    node = _node()
    await node._create_pr_with_gh("feat-999-x", "title", "body")

    assert captured_argv[:3] == ["gh", "pr", "create"]
    assert "merge" not in captured_argv


async def test_wiki_unavailable_degrades(ctx, monkeypatch):
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, True)

    async def _fake_gh_create(self, branch, title, body):
        return "https://github.com/x/y/pull/7"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _fake_gh_create)

    # Wiki ingest ON but no wiki_toolkit configured -> degrade, PR still created.
    node = _node(wiki_page_ingest=True, wiki_toolkit=None)
    result = await node.execute(ctx)

    assert result["status"] == "ready_to_deploy"
    assert result["wiki_page_id"] is None


async def test_wiki_ingest_success(ctx, monkeypatch):
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, True)

    async def _fake_gh_create(self, branch, title, body):
        return "https://github.com/x/y/pull/7"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _fake_gh_create)

    wiki = MagicMock()
    wiki.create_page = AsyncMock(return_value={"page_id": "page-42"})
    node = _node(wiki_page_ingest=True, wiki_toolkit=wiki)
    result = await node.execute(ctx)

    assert result["wiki_page_id"] == "page-42"
    wiki.create_page.assert_awaited_once()


async def test_graph_memory_absent_noop(ctx, monkeypatch):
    """No facade injected (the default) -> strict no-op."""
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, True)

    async def _fake_gh_create(self, branch, title, body):
        return "https://github.com/x/y/pull/7"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _fake_gh_create)

    node = _node()
    result = await node.execute(ctx)  # must not raise

    assert result["status"] == "ready_to_deploy"


async def test_no_jira_key_no_jira_calls(ctx, monkeypatch):
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, True)

    async def _fake_gh_create(self, branch, title, body):
        return "https://github.com/x/y/pull/7"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _fake_gh_create)

    jira = MagicMock()
    jira.jira_transition_issue = AsyncMock(return_value={"ok": True})
    jira.jira_transition_to = AsyncMock(return_value={"ok": True})
    jira.jira_add_comment = AsyncMock(return_value={"id": "c1"})

    node = _node(jira_toolkit=jira)  # ctx.planner_output.jira_issue_key is None
    await node.execute(ctx)

    jira.jira_transition_issue.assert_not_awaited()
    jira.jira_transition_to.assert_not_awaited()
    jira.jira_add_comment.assert_not_awaited()


async def test_jira_transition_and_comment_when_ticket_present(ctx, monkeypatch):
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, True)

    async def _fake_gh_create(self, branch, title, body):
        return "https://github.com/x/y/pull/7"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _fake_gh_create)

    ctx["planner_output"] = ctx["planner_output"].model_copy(
        update={"jira_issue_key": "OPS-1"}
    )
    jira = MagicMock()
    jira.jira_transition_issue = AsyncMock(return_value={"ok": True})
    jira.jira_transition_to = AsyncMock(return_value={"ok": True})
    jira.jira_add_comment = AsyncMock(return_value={"id": "c1"})

    node = _node(jira_toolkit=jira)
    await node.execute(ctx)

    jira.jira_add_comment.assert_awaited_once()


async def test_gh_missing_rest_fallback(ctx, monkeypatch):
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, False)

    async def _fake_rest_create(self, branch, title, body):
        return "https://github.com/x/y/pull/9"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_via_rest", _fake_rest_create)

    node = _node()
    result = await node.execute(ctx)

    assert result["status"] == "ready_to_deploy"
    assert result["pr_number"] == 9


async def test_both_pr_paths_fail_blocked(ctx, monkeypatch):
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, True)
    _patch_instant_sleep(monkeypatch)

    async def _always_fails(self, branch, title, body):
        raise RuntimeError("502 bad gateway")

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _always_fails)

    node = _node()
    result = await node.execute(ctx)

    assert result["status"] == "blocked"
    assert "error" in result


async def test_push_failure_blocked(ctx, monkeypatch):
    async def _failing_push(self, cwd, *args):
        raise RuntimeError("git push: permission denied")

    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _failing_push)

    node = _node()
    result = await node.execute(ctx)

    assert result["status"] == "blocked"
    assert "push" in result["error"]


async def test_accept_notes_in_pr_body(ctx, monkeypatch):
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, True)

    captured_body = {}

    async def _fake_gh_create(self, branch, title, body):
        captured_body["body"] = body
        return "https://github.com/x/y/pull/7"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _fake_gh_create)

    ctx["feedback_decision"] = FeedbackDecision(
        decision="accept_with_notes", notes="two nit findings accepted"
    )

    node = _node()
    await node.execute(ctx)

    assert "two nit findings accepted" in captured_body["body"]


async def test_decision_recorded_action(ctx, monkeypatch):
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, True)

    async def _fake_gh_create(self, branch, title, body):
        return "https://github.com/x/y/pull/7"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _fake_gh_create)

    host = SessionHost("run-1")
    ctx["session_host"] = host

    node = _node()
    result = await node.execute(ctx)

    assert len(host.state.docs_artifacts) == 1
    artifact = host.state.docs_artifacts[0]
    assert artifact.docs_path == result["docs_path"]
    assert artifact.pr_url == result["pr_url"]


async def test_graph_memory_publishes_run_outcome(ctx, monkeypatch):
    """An injected facade receives the real publish_run_outcome contract.

    Regression: the node used to construct ``DevLoopGraphMemory()`` and
    call ``publish_run_outcome(feat_id=..., pr_url=...)`` — both wrong
    (keyword-only ctor; the real signature is
    ``(run_id, report, outcome, summary)``), so every feature-mode run
    logged a warning and wrote nothing to the graph.
    """
    monkeypatch.setattr(FeatureHandoffNode, "_run_git", _ok_git)
    _patch_gh_available(monkeypatch, True)

    async def _fake_gh_create(self, branch, title, body):
        return "https://github.com/x/y/pull/7"

    monkeypatch.setattr(FeatureHandoffNode, "_create_pr_with_gh", _fake_gh_create)

    graph_memory = MagicMock()
    graph_memory.publish_run_outcome = AsyncMock(return_value=None)

    node = _node(graph_memory=graph_memory)
    result = await node.execute(ctx)

    assert result["status"] == "ready_to_deploy"
    graph_memory.publish_run_outcome.assert_awaited_once()
    args, _ = graph_memory.publish_run_outcome.call_args
    run_id, report, outcome, summary = args
    assert run_id == "r1"
    assert report is ctx["qa_report"]
    assert outcome == "succeeded"
    assert "FEAT-999" in summary and "pull/7" in summary
