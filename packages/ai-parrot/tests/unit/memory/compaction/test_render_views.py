"""Unit tests for FEAT-525 render_history() accepting TurnView sequences."""

import ast
from pathlib import Path

from parrot.memory.abstract import ConversationHistory, ConversationTurn
from parrot.memory.compaction.models import TurnState, TurnView
from parrot.memory.render import render_history


def _turn(i, chatbot_id="bot"):
    return ConversationTurn(
        turn_id=f"t{i}", user_id="u", user_message=f"q{i}", assistant_response=f"a{i}", chatbot_id=chatbot_id
    )


def _view(t, suffix="", state=TurnState.RAW):
    return TurnView(
        turn_id=t.turn_id,
        chatbot_id=t.chatbot_id,
        user_text=t.user_message,
        assistant_text=t.assistant_response,
        assistant_suffix=suffix,
        state=state,
        estimated_tokens=1,
    )


def test_render_views_appends_suffix():
    t = _turn(1)
    out = render_history([_view(t, "\n\n<tool-activity>\n- q ok\n</tool-activity>")], current_chatbot_id="bot")
    assert [m.role for m in out] == ["user", "assistant"]
    assert out[1].content == "a1\n\n<tool-activity>\n- q ok\n</tool-activity>" and out[1].turn_id == "t1"


def test_render_foreign_view_label_precedes_text_and_suffix():
    t = _turn(1, chatbot_id="other")
    out = render_history([_view(t, "\n\nX")], current_chatbot_id="bot")
    assert out[1].content == "[agent:other] a1\n\nX"


def test_render_text_only_views_identical_to_plain():
    turns = [_turn(i) for i in range(5)]
    h = ConversationHistory(session_id="s", user_id="u", chatbot_id="bot", turns=turns)
    assert render_history([_view(t) for t in turns], current_chatbot_id="bot") == render_history(
        h, current_chatbot_id="bot"
    )


def test_render_plain_history_max_turns_unchanged():
    h = ConversationHistory(session_id="s", user_id="u", turns=[_turn(i) for i in range(5)])
    assert [m.turn_id for m in render_history(h, max_turns=2)] == ["t3", "t3", "t4", "t4"]


def test_render_imports_no_compaction():
    import parrot.memory.render as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    guarded = {
        id(n)
        for top in tree.body
        if isinstance(top, ast.If) and getattr(top.test, "id", "") == "TYPE_CHECKING"
        for n in ast.walk(top)
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) not in guarded:
            names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
            assert not any("compaction" in n for n in names), ast.dump(node)
