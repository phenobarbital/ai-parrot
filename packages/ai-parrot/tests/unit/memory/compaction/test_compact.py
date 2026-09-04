"""Unit + property tests for FEAT-525 compact_history (three-tier pre-pass)."""

from __future__ import annotations

import copy

from hypothesis import HealthCheck, given, settings, strategies as st

from parrot.memory.abstract import ConversationHistory, ConversationTurn
from parrot.memory.compaction.compact import compact_history, render_tool_activity
from parrot.memory.compaction.models import ContextBudget, Limit, ToolInvocation, TurnState

from .conftest import make_turn


def test_three_tier_walk_chatty(chatty_history, budget, counter):
    r = compact_history(chatty_history, budget, counter=counter)
    assert len(r.views) == 30 and all(v.state is TurnState.RAW for v in r.views)
    assert r.omissions == () and r.stage2_needed is False and len(r.dropped_turn_ids) == 20


def test_three_tier_walk_database(database_history, budget, counter):
    r = compact_history(database_history, budget, counter=counter)
    assert r.views[-1].state is TurnState.RAW and all(v.state is TurnState.PRUNED for v in r.views[:-1])
    assert r.history_estimate <= int(0.8 * budget.available) and len(r.omissions) == len(r.views) - 1
    assert r.boundary_turn_id == r.views[-2].turn_id and all(
        "<tool-output-omitted" in v.assistant_suffix for v in r.views[:-1]
    )


def test_persisted_boundary_forces_pruned(chatty_history, budget, counter):
    first = compact_history(chatty_history, budget, counter=counter)
    b = first.views[10].turn_id
    r = compact_history(chatty_history, budget, counter=counter, boundary_turn_id=b)
    assert all(v.state is TurnState.PRUNED for v in r.views[:11]) and r.views[11].state is TurnState.RAW
    assert r.boundary_turn_id == b


def test_dropped_sets_stage2(database_history, counter):
    r = compact_history(database_history, ContextBudget(window=16_000), counter=counter)
    assert r.dropped_turn_ids and r.stage2_needed is True


def test_min_verbatim_turns_guard(counter):
    # A single huge newest turn: still RAW, stage2_needed True, nothing truncated.
    h = ConversationHistory(session_id="s", user_id="u", turns=[make_turn(0, tokens=40_000)])
    r = compact_history(h, ContextBudget(window=32_000), counter=counter)
    assert len(r.views) == 1 and r.views[0].state is TurnState.RAW
    assert r.views[0].assistant_text == h.turns[0].assistant_response
    assert r.stage2_needed is True

    # Two large text-only turns: min_verbatim_turns=2 forces BOTH RAW even
    # though their combined size blows past verbatim_tokens/watermark.
    h2 = ConversationHistory(
        session_id="s2",
        user_id="u",
        turns=[make_turn(0, tokens=20_000), make_turn(1, tokens=20_000)],
    )
    r2 = compact_history(h2, ContextBudget(window=32_000), counter=counter)
    assert len(r2.views) == 2 and all(v.state is TurnState.RAW for v in r2.views)


def test_oversize_rule_inside_verbatim_tier(counter):
    """An oversize invocation is pruned even for a turn that would otherwise be verbatim-eligible.

    The turn's *classification* becomes PRUNED (an oversize invocation
    disqualifies RAW entirely — otherwise `min_verbatim_turns` would force
    RAW purely on the now-tiny notice-only rendered size, defeating the
    pruned tier for any oversize-heavy history; see `test_three_tier_walk_database`).
    Its suffix still carries the omission notice and the Omission is
    still collected. The newest turn's identical-sized output is exempt
    from the oversize rule and renders as a plain excerpt.
    """
    big = "z" * 20_000  # 5_000 heuristic tokens > oversize_tool_tokens (2_000)
    older = ConversationTurn(
        turn_id="t0",
        user_id="u",
        user_message="q0",
        assistant_response="a0",
        tool_invocations=[ToolInvocation(tool_name="query_database", input={"sql": "x"}, output=big)],
    )
    newest = ConversationTurn(
        turn_id="t1",
        user_id="u",
        user_message="q1",
        assistant_response="a1",
        tool_invocations=[ToolInvocation(tool_name="query_database", input={"sql": "y"}, output=big)],
    )
    h = ConversationHistory(session_id="s", user_id="u", turns=[older, newest])
    r = compact_history(h, ContextBudget(window=32_000), counter=counter)

    assert len(r.views) == 2
    older_view, newest_view = r.views
    assert older_view.turn_id == "t0" and older_view.state is TurnState.PRUNED
    assert "<tool-output-omitted" in older_view.assistant_suffix
    assert len(r.omissions) == 1

    assert newest_view.turn_id == "t1" and newest_view.state is TurnState.RAW
    assert "out=" in newest_view.assistant_suffix
    assert "<tool-output-omitted" not in newest_view.assistant_suffix


def test_legacy_turn_counted_lazily(counter):
    turn = make_turn(0, tokens=150)
    assert turn.token_count is None
    h = ConversationHistory(session_id="s", user_id="u", turns=[turn])
    r = compact_history(h, ContextBudget(window=32_000), counter=counter)
    assert len(r.views) == 1
    # compact_history never stamps token_count on the input turn (purity).
    assert turn.token_count is None


def test_render_tool_activity_empty_and_limits():
    turn_no_tools = ConversationTurn(turn_id="t", user_id="u", user_message="q", assistant_response="a")
    assert render_tool_activity(turn_no_tools, Limit()) == ""

    invocations = [
        ToolInvocation(tool_name=f"tool{i}", input={}, output="y" * 1000) for i in range(20)
    ]
    turn = ConversationTurn(
        turn_id="t2", user_id="u", user_message="q", assistant_response="a", tool_invocations=invocations
    )
    suffix = render_tool_activity(turn, Limit(max_invocations=12, max_output_chars=50))
    assert "… +8 more" in suffix
    assert "…(+950 chars)" in suffix


@st.composite
def st_history(draw):
    n = draw(st.integers(min_value=1, max_value=12))
    turns = []
    for i in range(n):
        tokens = draw(st.integers(min_value=10, max_value=9_000))
        tool_output_chars = draw(st.sampled_from([0, 0, 0, 5_000, 20_000]))
        turns.append(make_turn(i, tokens=tokens, tool_output_chars=tool_output_chars))
    return ConversationHistory(session_id="s", user_id="u", chatbot_id="bot", turns=turns)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.data())
def test_compact_is_pure_and_deterministic(counter, data):
    h = data.draw(st_history())
    before = copy.deepcopy(h)
    b = ContextBudget(window=data.draw(st.integers(min_value=13_000, max_value=200_000)))
    r1, r2 = compact_history(h, b, counter=counter), compact_history(h, b, counter=counter)
    assert r1 == r2 and h == before
    states = [v.state for v in r1.views]
    assert states == sorted(states, key=lambda s: s is TurnState.RAW)
