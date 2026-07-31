"""Unit tests for dispatch telemetry harvest (FEAT-378 TASK-1927).

Covers ``ClaudeCodeDispatcher._extract_result_usage`` (dict-shaped and
object-shaped ``usage``, absent usage), the ``dispatch.completed``
payload -> :class:`DispatchCompleted` action mapping
(``action_from_dispatch_event``), the reducer fold into
:class:`DispatchState`, and a regression test that a payload-less
``dispatch.completed`` behaves exactly as before.
"""

from __future__ import annotations

from typing import Any, List

from parrot.flows.dev_loop import ClaudeCodeDispatcher
from parrot.flows.dev_loop.session_state import (
    DispatchCompleted,
    DispatchQueued,
    action_from_dispatch_event,
    reduce,
    session_channel,
)
from parrot.flows.dev_loop.session_state import DevLoopSessionState

RUN_ID = "run-test0001"


def _fresh_state() -> DevLoopSessionState:
    return DevLoopSessionState(run_id=RUN_ID, channel=session_channel(RUN_ID))


class _ResultMessage:
    """Minimal terminal-ResultMessage duck-type (mirrors test_dispatcher.py)."""

    def __init__(
        self,
        *,
        is_error: bool = False,
        usage: Any = None,
        total_cost_usd: Any = None,
        num_turns: int = 1,
        duration_ms: Any = None,
    ) -> None:
        self.subtype = "success"
        self.is_error = is_error
        self.api_error_status = None
        self.result = None
        self.num_turns = num_turns
        self.permission_denials = None
        self.usage = usage
        self.total_cost_usd = total_cost_usd
        self.duration_ms = duration_ms


class _UsageObj:
    """Object-shaped ``usage`` (attributes instead of dict keys)."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _NonTerminalMessage:
    """A message with no ``is_error`` attribute — must be skipped."""


# ---------------------------------------------------------------------------
# _extract_result_usage
# ---------------------------------------------------------------------------


def test_extract_result_usage_dict_shaped():
    messages: List[Any] = [
        _NonTerminalMessage(),
        _ResultMessage(
            usage={
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 5,
            },
            total_cost_usd=0.0123,
            num_turns=3,
            duration_ms=4200,
        ),
    ]
    detail = ClaudeCodeDispatcher._extract_result_usage(messages)
    assert detail == {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 10,
        "cache_read_input_tokens": 5,
        "total_cost_usd": 0.0123,
        "num_turns": 3,
        "duration_ms": 4200,
    }


def test_extract_result_usage_object_shaped():
    messages: List[Any] = [
        _ResultMessage(
            usage=_UsageObj(input_tokens=20, output_tokens=8),
            total_cost_usd=0.002,
            num_turns=1,
            duration_ms=900,
        ),
    ]
    detail = ClaudeCodeDispatcher._extract_result_usage(messages)
    assert detail == {
        "input_tokens": 20,
        "output_tokens": 8,
        "total_cost_usd": 0.002,
        "num_turns": 1,
        "duration_ms": 900,
    }


def test_extract_result_usage_absent_returns_none():
    # No terminal ResultMessage at all (no `is_error` attribute anywhere).
    messages: List[Any] = [_NonTerminalMessage(), _NonTerminalMessage()]
    assert ClaudeCodeDispatcher._extract_result_usage(messages) is None

    # Terminal ResultMessage present but usage/cost/turns/duration all None.
    messages_empty: List[Any] = [
        _ResultMessage(usage=None, total_cost_usd=None, duration_ms=None)
    ]
    # num_turns defaults to 1 in the fake, so stub it to None to hit the
    # "nothing extractable" branch explicitly.
    messages_empty[0].num_turns = None
    assert ClaudeCodeDispatcher._extract_result_usage(messages_empty) is None


# ---------------------------------------------------------------------------
# action_from_dispatch_event — usage payload -> DispatchCompleted kwargs
# ---------------------------------------------------------------------------


def test_action_from_dispatch_event_maps_usage_payload():
    action = action_from_dispatch_event(
        "dispatch.completed",
        "development",
        1.0,
        {
            "output_model": "ResearchOutput",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 5,
                "total_cost_usd": 0.0123,
                "num_turns": 3,
                "duration_ms": 4200,
            },
        },
    )
    assert isinstance(action, DispatchCompleted)
    assert action.input_tokens == 100
    assert action.output_tokens == 50
    assert action.cache_creation_input_tokens == 10
    assert action.cache_read_input_tokens == 5
    assert action.total_cost_usd == 0.0123
    assert action.num_turns == 3
    assert action.duration_ms == 4200


def test_action_from_dispatch_event_ignores_unknown_usage_keys():
    action = action_from_dispatch_event(
        "dispatch.completed",
        "development",
        1.0,
        {"usage": {"input_tokens": 7, "some_unknown_field": "x"}},
    )
    assert isinstance(action, DispatchCompleted)
    assert action.input_tokens == 7
    assert action.output_tokens is None


# ---------------------------------------------------------------------------
# Reducer fold
# ---------------------------------------------------------------------------


def test_reducer_folds_usage_into_dispatch_state():
    state = reduce(_fresh_state(), DispatchQueued(node_id="development"))
    state = reduce(
        state,
        DispatchCompleted(
            node_id="development",
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=10,
            cache_read_input_tokens=5,
            total_cost_usd=0.0123,
            num_turns=3,
            duration_ms=4200,
        ),
    )
    dispatch = state.nodes["development"].dispatch
    assert dispatch.status == "completed"
    assert dispatch.input_tokens == 100
    assert dispatch.output_tokens == 50
    assert dispatch.cache_creation_input_tokens == 10
    assert dispatch.cache_read_input_tokens == 5
    assert dispatch.total_cost_usd == 0.0123
    assert dispatch.num_turns == 3
    assert dispatch.duration_ms == 4200


def test_payloadless_completed_unchanged():
    """A `DispatchCompleted` with no telemetry fields behaves exactly as
    before TASK-1927 — status flips to completed, all telemetry fields
    stay `None`."""
    state = reduce(_fresh_state(), DispatchQueued(node_id="qa"))
    state = reduce(state, DispatchCompleted(node_id="qa"))
    dispatch = state.nodes["qa"].dispatch
    assert dispatch.status == "completed"
    assert dispatch.input_tokens is None
    assert dispatch.output_tokens is None
    assert dispatch.cache_creation_input_tokens is None
    assert dispatch.cache_read_input_tokens is None
    assert dispatch.total_cost_usd is None
    assert dispatch.num_turns is None
    assert dispatch.duration_ms is None


def test_action_from_dispatch_event_completed_no_payload_unchanged():
    """`action_from_dispatch_event("dispatch.completed", ...)` with no
    payload still builds a bare `DispatchCompleted` (regression)."""
    action = action_from_dispatch_event("dispatch.completed", "qa", 1.0)
    assert isinstance(action, DispatchCompleted)
    assert action.input_tokens is None
    assert action.total_cost_usd is None
