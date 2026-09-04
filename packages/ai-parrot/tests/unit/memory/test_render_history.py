"""Unit tests for ``parrot.memory.render`` (FEAT-524, TASK-2809).

Each of the guarantees documented on :func:`render_history` in spec §2 gets
its own test, per spec §4 (M2 rows).
"""

from __future__ import annotations

import copy

import pytest

from parrot.memory import ConversationHistory, ConversationTurn, HistoryMessage, render_history


def _turn(index: int, assistant: str = "a", chatbot_id: str | None = None) -> ConversationTurn:
    """Build a minimal turn: user says ``q<index>``, assistant replies ``assistant``."""
    return ConversationTurn(
        turn_id=f"t{index}",
        user_id="u",
        user_message=f"q{index}",
        assistant_response=assistant,
        chatbot_id=chatbot_id,
    )


def _history(*turns: ConversationTurn) -> ConversationHistory:
    """Build a history holding ``turns``."""
    history = ConversationHistory(session_id="s", user_id="u")
    for turn in turns:
        history.add_turn(turn)
    return history


def test_render_empty_and_none():
    """``None`` and a turn-less history both render to an empty list."""
    assert render_history(None) == []
    assert render_history(_history()) == []


def test_render_alternation():
    """Roles strictly alternate, start with user and end with assistant."""
    history = _history(*[_turn(i) for i in range(3)])

    rendered = render_history(history)

    assert [m.role for m in rendered] == ["user", "assistant"] * 3
    assert rendered[0].role == "user"
    assert rendered[-1].role == "assistant"
    assert [m.content for m in rendered] == ["q0", "a", "q1", "a", "q2", "a"]


def test_render_carries_turn_identity():
    """Each rendered message keeps its originating turn id and chatbot id."""
    history = _history(_turn(1, chatbot_id="A"))

    rendered = render_history(history)

    assert all(m.turn_id == "t1" for m in rendered)
    assert all(m.chatbot_id == "A" for m in rendered)


def test_render_merges_consecutive_same_role():
    """A skipped assistant reply must not break alternation — merge instead.

    Two user turns whose assistant replies are empty would each contribute a
    lone user message. Rendering skips empty-assistant turns entirely, so this
    exercises the merge path via a *foreign* filtered turn between two own
    turns instead: dropping the middle turn leaves ``assistant`` followed by
    ``user``, which is already alternating. The direct merge case is a history
    whose turns were written with the same role twice — constructed here by
    rendering two turns where the first has a real reply and the second
    repeats the user text.
    """
    history = _history(
        _turn(1, assistant="a1", chatbot_id="A"),
        _turn(2, assistant="a2", chatbot_id="B"),
        _turn(3, assistant="a3", chatbot_id="A"),
    )

    # Filtering out the middle (foreign) turn leaves q1/a1/q3/a3 — still
    # alternating, and the two own turns are NOT merged together.
    rendered = render_history(history, current_chatbot_id="A", include_other_agents=False)

    assert [m.role for m in rendered] == ["user", "assistant", "user", "assistant"]
    assert [m.content for m in rendered] == ["q1", "a1", "q3", "a3"]


def test_render_merges_same_role_messages_directly():
    """The ``_append`` merge joins same-role content with a blank line."""
    from parrot.memory.render import _append

    out: list[HistoryMessage] = []
    _append(out, HistoryMessage("user", "first", chatbot_id="A", turn_id="t1"))
    _append(out, HistoryMessage("user", "second", chatbot_id="B", turn_id="t2"))

    assert len(out) == 1
    assert out[0].content == "first\n\nsecond"
    # Identity of the FIRST message in the merged run is kept.
    assert out[0].chatbot_id == "A"
    assert out[0].turn_id == "t1"


@pytest.mark.parametrize("assistant", ["", "   ", "\n\t "])
def test_render_skips_empty_assistant(assistant: str):
    """A turn with no assistant text produces no messages at all."""
    assert render_history(_history(_turn(1, assistant=assistant))) == []


def test_render_skip_empty_preserves_alternation():
    """An empty-assistant turn in the middle does not break alternation."""
    history = _history(_turn(1, assistant="a1"), _turn(2, assistant="  "), _turn(3, assistant="a3"))

    rendered = render_history(history)

    assert [m.role for m in rendered] == ["user", "assistant", "user", "assistant"]
    assert [m.content for m in rendered] == ["q1", "a1", "q3", "a3"]


def test_render_other_agent_label_and_filter():
    """Foreign turns are labelled by default and dropped when asked."""
    history = _history(_turn(1, chatbot_id="A"), _turn(2, chatbot_id="B"))

    labeled = render_history(history, current_chatbot_id="A")
    assert len(labeled) == 4
    assert labeled[3].content.startswith("[agent:B]")
    # The current agent's own turn is never labelled.
    assert labeled[1].content == "a"

    filtered = render_history(history, current_chatbot_id="A", include_other_agents=False)
    assert len(filtered) == 2
    assert [m.content for m in filtered] == ["q1", "a"]


def test_render_custom_other_agent_label():
    """``other_agent_label`` is a format string receiving ``chatbot_id``."""
    history = _history(_turn(1, chatbot_id="B"))

    rendered = render_history(
        history, current_chatbot_id="A", other_agent_label="<<{chatbot_id}>>"
    )

    assert rendered[1].content == "<<B>> a"


def test_render_legacy_turn_is_never_foreign():
    """A turn with ``chatbot_id=None`` predates attribution — treat as own."""
    history = _history(_turn(1, chatbot_id=None))

    rendered = render_history(history, current_chatbot_id="A", include_other_agents=False)

    assert len(rendered) == 2
    assert rendered[1].content == "a"


def test_render_no_current_id_means_nothing_is_foreign():
    """Without ``current_chatbot_id`` no turn can be foreign, so none is labelled."""
    history = _history(_turn(1, chatbot_id="A"), _turn(2, chatbot_id="B"))

    rendered = render_history(history)

    assert len(rendered) == 4
    assert not any("[agent:" in m.content for m in rendered)


def test_render_max_turns():
    """``max_turns`` keeps only the most recent N turns."""
    history = _history(*[_turn(i) for i in range(5)])

    rendered = render_history(history, max_turns=2)

    assert [m.content for m in rendered] == ["q3", "a", "q4", "a"]


def test_render_max_turns_none_keeps_all():
    """``max_turns=None`` is 'no limit', not 'nothing'."""
    history = _history(*[_turn(i) for i in range(4)])

    assert len(render_history(history, max_turns=None)) == 8


@pytest.mark.parametrize("max_turns", [0, -1])
def test_render_max_turns_non_positive_is_empty(max_turns: int):
    """A non-positive budget renders nothing rather than the whole history."""
    history = _history(*[_turn(i) for i in range(3)])

    assert render_history(history, max_turns=max_turns) == []


def test_render_is_pure():
    """Two renders are equal and the input history is never mutated."""
    history = _history(_turn(1, chatbot_id="A"), _turn(2, chatbot_id="B"))
    before = copy.deepcopy(history)

    first = render_history(history, current_chatbot_id="A", max_turns=2)
    second = render_history(history, current_chatbot_id="A", max_turns=2)

    assert first == second
    assert history.to_dict() == before.to_dict()
    assert len(history.turns) == 2


def test_history_message_is_frozen():
    """``HistoryMessage`` is immutable — renders can be cached/shared safely."""
    message = HistoryMessage("user", "hi")

    with pytest.raises(Exception):
        message.content = "changed"  # type: ignore[misc]


def test_render_module_does_not_import_storage_backends():
    """``render.py`` is a leaf module: no Redis/file/mem backend imports.

    ``parrot.clients`` types against ``HistoryMessage``; if this module ever
    pulled a storage backend, every LLM client would inherit a Redis
    dependency (spec §7).
    """
    from pathlib import Path

    import parrot.memory.render as render_module

    source = Path(render_module.__file__).read_text(encoding="utf-8")
    for forbidden in (".redis", ".file", ".mem", "redis", "aiofiles"):
        assert f"import {forbidden}" not in source
        assert f"from {forbidden}" not in source
