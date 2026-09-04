"""Provider-neutral rendering of a :class:`ConversationHistory` (FEAT-524).

This module is the **single** place that decides how stored conversation
turns become messages for an LLM.  ``AbstractBot`` calls :func:`render_history`
and hands the result to the client as ``history=``; the client only maps the
neutral :class:`HistoryMessage` list onto its provider's message shape (see
``AbstractClient._format_history``).

Design constraints (spec §2 "Data Models", §7 "Patterns to Follow"):

* :func:`render_history` is a **pure function** — same inputs always produce
  the same output, the input ``history`` is never mutated, and nothing here
  performs I/O.
* This is a **leaf module**: it imports only from :mod:`parrot.memory.abstract`,
  never from the storage backends (``.redis`` / ``.file`` / ``.mem``).  That is
  what lets :mod:`parrot.clients` type against ``HistoryMessage`` without
  dragging Redis or aiofiles into the client dependency set.
* Text only.  File attachments and provider-native ``tool_use`` /
  ``tool_result`` blocks are explicitly out of scope — ``ConversationTurn``
  does not store them.

This function is also the documented extension point for the forthcoming
per-turn compaction work (token budgeting, pruning, omission store): it
replaces the removed ``ConversationHistory.get_messages_for_api()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

from .abstract import ConversationHistory

__all__ = ("HistoryMessage", "render_history")


#: Separator used when two consecutive rendered messages share a role.
_MERGE_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class HistoryMessage:
    """A single rendered conversation message, provider-neutral and text-only.

    Attributes:
        role: Either ``"user"`` or ``"assistant"``.
        content: The message text.
        chatbot_id: The agent that produced the turn this message came from,
            or ``None`` for legacy turns written before attribution existed.
            When a message is the result of merging several turns, this is the
            ``chatbot_id`` of the first of them.
        turn_id: The originating :class:`~parrot.memory.ConversationTurn` id,
            under the same "first of a merged run" rule as ``chatbot_id``.
    """

    role: Literal["user", "assistant"]
    content: str
    chatbot_id: Optional[str] = None
    turn_id: Optional[str] = None


def _append(out: List[HistoryMessage], message: HistoryMessage) -> None:
    """Append ``message`` to ``out``, merging into the tail on a role clash.

    Strict ``user``/``assistant`` alternation is a hard requirement of several
    providers (Anthropic rejects consecutive same-role messages outright).
    Merging rather than dropping preserves the text of every turn.

    Args:
        out: Accumulator, mutated in place.
        message: The message to add.
    """
    if out and out[-1].role == message.role:
        previous = out[-1]
        out[-1] = HistoryMessage(
            role=previous.role,
            content=f"{previous.content}{_MERGE_SEPARATOR}{message.content}",
            # Keep the identity of the FIRST turn in a merged run: it is the
            # one that anchors the message's position in the conversation.
            chatbot_id=previous.chatbot_id,
            turn_id=previous.turn_id,
        )
        return
    out.append(message)


def render_history(
    history: Optional[ConversationHistory],
    *,
    max_turns: Optional[int] = None,
    current_chatbot_id: Optional[str] = None,
    include_other_agents: bool = True,
    other_agent_label: str = "[agent:{chatbot_id}]",
) -> List[HistoryMessage]:
    """Render a conversation history into alternating provider-neutral messages.

    Args:
        history: The history to render. ``None`` or empty renders to ``[]``.
        max_turns: Keep only the most recent ``N`` turns. ``None`` keeps all.
            Values ``<= 0`` also render to ``[]``.
        current_chatbot_id: The agent doing the asking. Turns whose
            ``chatbot_id`` differs are considered *foreign*; a turn with
            ``chatbot_id is None`` (legacy, pre-attribution) is always treated
            as belonging to the current agent. When ``current_chatbot_id`` is
            ``None`` no turn is foreign.
        include_other_agents: When ``False``, foreign turns are dropped
            entirely. When ``True`` (the default) they are kept and their
            assistant text is prefixed with ``other_agent_label`` so the model
            can tell who said what — the crew/flow shared-history case.
        other_agent_label: Format string for the foreign-turn prefix; receives
            ``chatbot_id`` as its only field.

    Returns:
        A list of :class:`HistoryMessage` with these guarantees:

        * roles strictly alternate; the list starts with ``"user"`` and ends
          with ``"assistant"`` (or is empty);
        * consecutive same-role messages are merged with a blank line;
        * turns whose ``assistant_response`` is empty or whitespace-only
          contribute nothing at all — never an empty assistant message;
        * ``history`` itself is not modified.
    """
    if history is None or not history.turns:
        return []

    if max_turns is not None:
        if max_turns <= 0:
            return []
        turns = history.turns[-max_turns:]
    else:
        turns = history.turns

    rendered: List[HistoryMessage] = []
    for turn in turns:
        assistant_response = turn.assistant_response or ""
        if not assistant_response.strip():
            # An assistant message with no text is not a usable turn: it would
            # either be rejected by the provider or teach the model to answer
            # with silence. Skip the whole turn so alternation stays intact.
            continue

        is_foreign = (
            current_chatbot_id is not None
            and turn.chatbot_id is not None
            and turn.chatbot_id != current_chatbot_id
        )
        if is_foreign and not include_other_agents:
            continue
        if is_foreign:
            label = other_agent_label.format(chatbot_id=turn.chatbot_id)
            assistant_response = f"{label} {assistant_response}"

        _append(
            rendered,
            HistoryMessage(
                role="user",
                content=turn.user_message or "",
                chatbot_id=turn.chatbot_id,
                turn_id=turn.turn_id,
            ),
        )
        _append(
            rendered,
            HistoryMessage(
                role="assistant",
                content=assistant_response,
                chatbot_id=turn.chatbot_id,
                turn_id=turn.turn_id,
            ),
        )

    return rendered
