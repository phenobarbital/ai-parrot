"""Unit tests for FEAT-378 feature-mode session-state extensions (TASK-1919).

Covers the 4 new ``NodeId`` values and the three new event-sourced actions/
reducers: ``JudgeVerdictRecorded``, ``FeedbackDecisionRecorded``,
``DocsArtifactLinked``. Per FEAT-322, all new state must enter
``DevLoopSessionState`` via actions + reducers — never mutable attributes.
"""

from __future__ import annotations

from parrot.flows.dev_loop.session_state import (
    DevLoopSessionState,
    DocsArtifactLinked,
    FeedbackDecisionRecorded,
    JudgeVerdictRecorded,
    NodeStarted,
    reduce,
)

RUN_ID = "run-feat3780001"


def _initial_state() -> DevLoopSessionState:
    return DevLoopSessionState(run_id=RUN_ID, channel=f"parrot-session://{RUN_ID}")


def test_new_node_ids_valid():
    """The 4 new NodeIds fold through the existing node/started action."""
    state = _initial_state()
    for node_id in ("planner", "synthesis", "feedback_router", "feature_handoff"):
        state = reduce(state, NodeStarted(node_id=node_id))
        assert state.nodes[node_id].status == "running"


def test_judge_verdict_recorded_accumulates_per_round():
    state = _initial_state()
    state = reduce(
        state,
        JudgeVerdictRecorded(
            round="qa-1",
            judge_id="j1",
            backend="claude-code",
            model="claude-sonnet-4-6",
            passed=True,
            findings_count=0,
            summary="clean",
        ),
    )
    state = reduce(
        state,
        JudgeVerdictRecorded(
            round="qa-1",
            judge_id="j2",
            backend="codex",
            model="gpt-5.5",
            passed=False,
            findings_count=2,
            summary="found issues",
        ),
    )
    # A second QA round starts a fresh list, keyed independently.
    state = reduce(
        state,
        JudgeVerdictRecorded(
            round="qa-2",
            judge_id="j1",
            backend="claude-code",
            model="claude-sonnet-4-6",
            passed=True,
            findings_count=0,
            summary="clean on retry",
        ),
    )

    assert len(state.judge_verdicts["qa-1"]) == 2
    assert state.judge_verdicts["qa-1"][0].judge_id == "j1"
    assert state.judge_verdicts["qa-1"][0].passed is True
    assert state.judge_verdicts["qa-1"][1].judge_id == "j2"
    assert state.judge_verdicts["qa-1"][1].passed is False
    assert state.judge_verdicts["qa-1"][1].findings_count == 2

    assert len(state.judge_verdicts["qa-2"]) == 1
    assert state.judge_verdicts["qa-2"][0].judge_id == "j1"


def test_feedback_decision_recorded():
    state = _initial_state()
    state = reduce(
        state,
        FeedbackDecisionRecorded(
            decision="retry",
            dev_brief="fix the null check",
            notes="",
            qa_attempt=1,
        ),
    )
    state = reduce(
        state,
        FeedbackDecisionRecorded(
            decision="accept_with_notes",
            dev_brief="",
            notes="minor style nit",
            qa_attempt=2,
        ),
    )

    assert len(state.feedback_decisions) == 2
    assert state.feedback_decisions[0].decision == "retry"
    assert state.feedback_decisions[0].qa_attempt == 1
    assert state.feedback_decisions[1].decision == "accept_with_notes"
    assert state.feedback_decisions[1].notes == "minor style nit"


def test_docs_artifact_linked():
    state = _initial_state()
    state = reduce(
        state,
        DocsArtifactLinked(
            docs_path="docs/features/feat-378-devloop-enhancement.md",
            wiki_page_id="wiki-123",
            pr_url="https://github.com/org/repo/pull/42",
        ),
    )

    assert len(state.docs_artifacts) == 1
    artifact = state.docs_artifacts[0]
    assert artifact.docs_path == "docs/features/feat-378-devloop-enhancement.md"
    assert artifact.wiki_page_id == "wiki-123"
    assert artifact.pr_url == "https://github.com/org/repo/pull/42"


def test_docs_artifact_linked_optional_fields_default_none():
    state = _initial_state()
    state = reduce(state, DocsArtifactLinked(docs_path="docs/features/x.md"))
    artifact = state.docs_artifacts[0]
    assert artifact.wiki_page_id is None
    assert artifact.pr_url is None


def test_unknown_action_still_ignored_or_raises_as_before():
    """Regression: an unrecognized ``type`` value degrades to a no-op.

    ``reduce`` matches on ``action.type`` via a chain of ``if`` branches and
    falls through to ``return state`` for anything unmatched — this test
    locks in that forward-compat behavior is unchanged by the new branches
    added for FEAT-378.
    """
    state = _initial_state()

    class _FakeAction:
        type = "totally/unknown"

    result = reduce(state, _FakeAction())  # type: ignore[arg-type]
    assert result is state
