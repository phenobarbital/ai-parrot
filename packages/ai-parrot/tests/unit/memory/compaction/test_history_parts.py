"""FEAT-886 M16 — budgeted parts: RAW / PRUNED / dropped, canonical text, byte identity, custom policy."""
from __future__ import annotations

from parrot.memory.abstract import ConversationHistory, ConversationTurn
from parrot.memory.compaction.compact import compact_history
from parrot.memory.compaction.models import ContextBudget, Limit, ToolInvocation, ToolStatus, TurnState
from parrot.memory.compaction.policies import PrunedInvocation, prune_turn, prune_turn_parts
from parrot.memory.compaction.tokens import HeuristicCounter
from parrot.memory.parts import MessagePart, render_parts_text
from parrot.memory.render import HistoryMessage, render_history

COUNTER = HeuristicCounter()


def _inv(name: str = "query_database", output: str = "rows", error: str | None = None, **kw) -> ToolInvocation:
    return ToolInvocation(
        tool_name=name, input={"sql": "SELECT 1"}, output=output, status=ToolStatus.COMPLETED,
        elapsed_ms=1200, error=error, **kw,
    )


def _turn(i: int, invs=(), *, text: str = "word " * 40, chatbot_id: str = "bot") -> ConversationTurn:
    return ConversationTurn(
        turn_id=f"turn-{i}", user_id="u", user_message=f"q{i} {text}", assistant_response=f"a{i} {text}",
        chatbot_id=chatbot_id, tool_invocations=list(invs),
    )


def _history(turns) -> ConversationHistory:
    h = ConversationHistory(session_id="s", user_id="u", chatbot_id="bot")
    h.turns.extend(turns)
    return h


def _budget(**kw) -> ContextBudget:
    base = dict(window=4_000, reserve_output=200, reserve_fixed=200, verbatim_tokens=400, min_verbatim_turns=1,
                max_turns=50)
    base.update(kw)
    return ContextBudget(**base)


def test_parts_raw_pruned_dropped():
    """RAW, PRUNED, and dropped turns produce the specified parts (text-only turns carry none)."""
    big = "x" * 4_000
    turns = [_turn(i, [_inv(output=big)] if i % 2 == 0 else []) for i in range(12)]
    result = compact_history(_history(turns), _budget(max_turns=8), counter=COUNTER, current_chatbot_id="bot")
    states = {v.turn_id: v for v in result.views}
    assert result.dropped_turn_ids, "scenario must drop old turns"
    for tid in result.dropped_turn_ids:
        assert tid not in states  # dropped: no view, no parts
    pruned = [v for v in result.views if v.state is TurnState.PRUNED and v.parts]
    assert pruned
    for view in pruned:
        assert [p.kind for p in view.parts][0] == "tool_use"
        assert any("<tool-output-omitted" in p.content for p in view.parts)  # approved omission notice only
        assert big not in "".join(p.content for p in view.parts)
    newest_raw = [v for v in result.views if v.state is TurnState.RAW and v.parts]
    for view in newest_raw:
        assert view.parts[0].kind == "tool_use" and view.parts[0].tool_call_id is None
    for view in result.views:
        if not view.assistant_suffix:
            assert view.parts is None


def test_suffix_equals_rendered_parts():
    """assistant_suffix == render_parts_text(parts) for every view that has tool activity."""
    turns = [_turn(i, [_inv(output="o" * (50 * (i + 1)), error="e" if i == 3 else None), _inv("file_read")])
             for i in range(10)]
    result = compact_history(_history(turns), _budget(), counter=COUNTER, current_chatbot_id="bot")
    checked = 0
    for view in result.views:
        if view.parts:
            assert view.assistant_suffix == render_parts_text(view.parts)
            checked += 1
    assert checked >= 2
    # token accounting measured exactly that text: estimated size >= the counter's count of the suffix
    for view in result.views:
        assert view.estimated_tokens >= COUNTER.count(view.assistant_suffix)


def test_render_parts_text_shapes():
    assert render_parts_text(()) == ""
    parts = (
        MessagePart("tool_use", "- t ok in={}", "t"),
        MessagePart("tool_result", "out=1", "t"),
        MessagePart("text", "… +2 more"),
        MessagePart("text", "\nhint"),
    )
    assert render_parts_text(parts) == "\n\n<tool-activity>\n- t ok in={} out=1\n… +2 more\n</tool-activity>\nhint"


def test_disabled_compaction_byte_identical():
    """Rendering a plain ConversationHistory carries no parts and the exact old text."""
    h = _history([_turn(i, [_inv()]) for i in range(3)])
    messages = render_history(h)
    assert all(m.parts is None for m in messages)
    assert messages[1].content == h.turns[0].assistant_response  # no suffix, as today


def test_view_render_carries_parts_and_label_precedes_them():
    turns = [_turn(0, [_inv()], chatbot_id="other"), _turn(1, [_inv()], chatbot_id="bot")]
    result = compact_history(_history(turns), _budget(window=20_000, verbatim_tokens=10_000), counter=COUNTER,
                             current_chatbot_id="bot")
    messages = render_history(result.views, current_chatbot_id="bot")
    foreign = messages[1]
    assert foreign.content.startswith("[agent:other] ")
    assert foreign.parts is not None and foreign.parts[0].content.startswith("[agent:other] ")
    assert render_history(result.views, current_chatbot_id="bot", include_other_agents=False)[0].chatbot_id == "bot"


def test_merged_messages_concatenate_parts_in_order():
    a = HistoryMessage("user", "one", parts=(MessagePart("text", "one"),))
    b = HistoryMessage("user", "two")
    from parrot.memory.render import _append

    out: list = []
    _append(out, a)
    _append(out, b)
    assert out[0].content == "one\n\ntwo"
    assert [p.content for p in out[0].parts] == ["one", "\n\n", "two"]
    plain: list = []
    _append(plain, HistoryMessage("user", "x"))
    _append(plain, HistoryMessage("user", "y"))
    assert plain[0].parts is None


def test_custom_policy_without_parts():
    """A custom policy that returns no parts is wrapped in one text part; the suffix is unchanged."""

    class NoPartsPolicy:
        name = "custom"

        def prune(self, inv, *, turn_id, limit):
            return PrunedInvocation(f"- custom line for {inv.tool_name}", ())

    turn = _turn(0, [_inv("mytool")])
    parts, _ = prune_turn_parts(turn, limit=Limit(), policies={"mytool": NoPartsPolicy()})
    assert parts == (MessagePart("text", "- custom line for mytool"),)
    suffix, _ = prune_turn(turn, limit=Limit(), policies={"mytool": NoPartsPolicy()})
    assert suffix == "\n\n<tool-activity>\n- custom line for mytool\n</tool-activity>"
