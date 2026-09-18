"""Unit tests for parrot.cli.events (FEAT-573 TASK-3403)."""
from __future__ import annotations

from unittest.mock import MagicMock  # verified: tests/cli/test_integration.py:12

import pytest  # verified: tests/cli/test_integration.py:14

from parrot.cli.events import (
    BackendCapabilities, TextDelta, ToolFailed, ToolFinished, ToolStarted, TurnCancelled,
    TurnCompleted, TurnEventKind, TurnFailed, TurnStarted, summarize_message_text,
)


@pytest.mark.parametrize(
    ("cls", "kwargs", "kind"),
    [
        (TurnStarted, {"query": "hi", "streaming": True}, TurnEventKind.STARTED),
        (TextDelta, {"text": "he"}, TurnEventKind.DELTA),
        (ToolStarted, {"call_id": "s1", "tool_name": "t"}, TurnEventKind.TOOL_STARTED),
        (ToolFinished, {"call_id": "s1", "tool_name": "t", "duration_ms": 1.0, "result_status": "success", "result_size_bytes": 2}, TurnEventKind.TOOL_FINISHED),
        (ToolFailed, {"call_id": "s1", "tool_name": "t", "duration_ms": 1.0, "error_type": "E", "error_message": "m"}, TurnEventKind.TOOL_FAILED),
        (TurnCompleted, {"text": "x", "message": MagicMock()}, TurnEventKind.COMPLETED),
        (TurnFailed, {"error_type": "E", "error_message": "m"}, TurnEventKind.FAILED),
        (TurnCancelled, {}, TurnEventKind.CANCELLED),
    ],
)
def test_each_event_has_fixed_kind_and_defaults(cls, kwargs, kind) -> None:
    ev = cls(turn_id="t", seq=0, **kwargs)
    assert ev.kind is kind and ev.turn_id == "t" and ev.seq == 0 and ev.at is not None


def test_seq_must_be_non_negative() -> None:
    with pytest.raises(ValueError):
        TextDelta(turn_id="t", seq=-1, text="x")


def test_turn_completed_accepts_duck_typed_message() -> None:
    msg = MagicMock(); msg.output = "answer"; msg.response = None
    ev = TurnCompleted(turn_id="t", seq=3, text="answer", message=msg)
    assert ev.message is msg


def test_summarize_message_text_fallback_order() -> None:
    m1 = MagicMock(); m1.output = "plain"; assert summarize_message_text(m1) == "plain"
    m2 = MagicMock(); m2.output = None; m2.response = "resp"; assert summarize_message_text(m2) == "resp"
    m3 = MagicMock(); m3.output = {"a": 1}; assert '"a": 1' in summarize_message_text(m3)
    assert summarize_message_text(object()) == ""
    m4 = MagicMock(); m4.output = [1, 2, 3]
    assert summarize_message_text(m4) == "[\n  1,\n  2,\n  3\n]"

    # A circular reference is not JSON-serialisable even with default=str,
    # so json.dumps raises ValueError and the fallback str(output) path runs.
    circular: list = []
    circular.append(circular)
    m5 = MagicMock(); m5.output = circular
    assert summarize_message_text(m5) == str(circular)


def test_backend_capabilities_defaults() -> None:
    caps = BackendCapabilities()
    assert (caps.streaming, caps.live_tool_events, caps.usage, caps.resume) == (True, False, False, False)
