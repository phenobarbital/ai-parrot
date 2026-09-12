"""``node/progress`` — the node-authored narrative channel.

Covers the reducer bound, the clamps at the action boundary, the
``DevLoopNode.report_progress`` helper's never-raise contract, and the
``dispatch/delta`` content classification the console filters on.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from parrot.flows.dev_loop.nodes.base import DevLoopNode
from parrot.flows.dev_loop.session_state import (
    PROGRESS_MAX,
    DevLoopSessionState,
    DispatchDelta,
    NodeProgress,
    SessionHost,
    action_from_dispatch_event,
    reduce,
    session_channel,
)


def _fresh() -> DevLoopSessionState:
    return DevLoopSessionState(run_id="run-1", channel=session_channel("run-1"))


class TestReducer:
    def test_appends_entries_in_order(self):
        state = _fresh()
        state = reduce(state, NodeProgress(node_id="planner", phase="started", headline="Generating spec"))
        state = reduce(state, NodeProgress(node_id="planner", phase="finished", headline="Spec written"))
        entries = state.nodes["planner"].progress
        assert [e.phase for e in entries] == ["started", "finished"]
        assert entries[0].headline == "Generating spec"

    def test_bounded_to_progress_max(self):
        state = _fresh()
        for i in range(PROGRESS_MAX + 5):
            state = reduce(state, NodeProgress(node_id="development", headline=f"wave {i}"))
        entries = state.nodes["development"].progress
        assert len(entries) == PROGRESS_MAX
        assert entries[-1].headline == f"wave {PROGRESS_MAX + 4}"
        assert entries[0].headline == "wave 5"

    def test_does_not_touch_status_or_summary(self):
        state = reduce(_fresh(), NodeProgress(node_id="qa", headline="x"))
        node = state.nodes["qa"]
        assert node.status == "idle"
        assert node.summary == {}

    def test_headline_and_detail_are_clamped_and_normalised(self):
        action = NodeProgress(node_id="qa", headline="  a\n\nb   " + "x" * 500, detail="d" * 1000)
        assert action.headline.startswith("a b xxx")
        assert len(action.headline) == 160
        assert len(action.detail) == 400

    def test_replay_folds_to_host_state(self):
        host = SessionHost("run-1")
        host.apply(NodeProgress(node_id="planner", phase="started", headline="go"))
        assert host.state.nodes["planner"].progress[0].headline == "go"
        replayed = [e.action for e in host.replay_since(0)]
        assert any(a.type == "node/progress" for a in replayed)


class _Node(DevLoopNode):
    async def execute(self, ctx, deps=None, **kwargs):  # pragma: no cover - never run
        return {}


class _ExplodingHost:
    def apply(self, action):
        raise RuntimeError("boom")


class TestReportProgress:
    def test_reaches_the_session_host(self):
        host = SessionHost("run-1")
        shared: Dict[str, Any] = {"session_host": host}
        _Node(node_id="planner").report_progress(shared, "started", "Generating spec", "from doc.md")
        entry = host.state.nodes["planner"].progress[0]
        assert entry.phase == "started"
        assert entry.headline == "Generating spec"
        assert entry.detail == "from doc.md"

    def test_no_host_is_a_noop(self):
        _Node(node_id="planner").report_progress({}, "started", "x")  # must not raise

    def test_failing_host_is_swallowed(self):
        _Node(node_id="planner").report_progress({"session_host": _ExplodingHost()}, "started", "x")

    def test_seat_node_id_is_swallowed(self):
        host = SessionHost("run-1")
        _Node(node_id="development.w1").report_progress({"session_host": host}, "working", "x")
        assert "development.w1" not in host.state.nodes


class TestDeltaContentKind:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"message_class": "AssistantMessage", "text": "hi"}, "text"),
            ({"message_class": "AssistantMessage", "thinking": "hmm"}, "thinking"),
            ({"message_class": "AssistantMessage", "text": "hi", "thinking": "hmm"}, "text"),
            ({"message_class": "SystemMessage", "subtype": "init"}, "system"),
            ({"message_class": "ResultMessage", "num_turns": 3}, "result"),
            ({"message_class": "UserMessage"}, "empty"),
            ({}, "empty"),
        ],
    )
    def test_classification(self, payload, expected):
        action = action_from_dispatch_event("dispatch.message", "development", 1.0, payload)
        assert isinstance(action, DispatchDelta)
        assert action.content_kind == expected

    def test_thinking_is_carried_and_clamped(self):
        action = action_from_dispatch_event(
            "dispatch.message", "development", 1.0, {"thinking": "a  b\n" + "x" * 1000, "seat": "development.w1"}
        )
        assert action.thinking.startswith("a b x")
        assert len(action.thinking) == 400

    def test_thinking_folds_into_seat_state(self):
        action = action_from_dispatch_event(
            "dispatch.message", "development", 1.0, {"thinking": "plan first", "seat": "development.w1"}
        )
        state = reduce(_fresh(), action)
        seat = state.nodes["development"].dispatch.seats["development.w1"]
        assert seat.last_thinking == "plan first"
        assert seat.message_count == 1
