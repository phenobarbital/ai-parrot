"""Provider-neutral rendering of a :class:`ConversationHistory` (FEAT-524).

This module is the **single** place that decides how stored conversation
turns become messages for an LLM.  ``AbstractBot`` calls :func:`render_history`
and hands the result to the client as ``history=``; the client only maps the
neutral :class:`HistoryMessage` list onto its provider's message shape (see
``AbstractClient._format_history``).

Design constraints (spec §2 "Data Models", §7 "Patterns to Follow"):

* :func:`render_history` is a **pure function** — same inputs always produce
  the same output, the input ``history``/views are never mutated, and
  nothing here performs I/O, computes an id, or touches a store.
* This is a **leaf module**: it imports only from :mod:`parrot.memory.abstract`
  at runtime (the :class:`~parrot.memory.compaction.models.TurnView` type is
  imported under ``TYPE_CHECKING`` only), never from the storage backends
  (``.redis`` / ``.file`` / ``.mem``) or from :mod:`parrot.memory.compaction`.
  That is what lets :mod:`parrot.clients` type against ``HistoryMessage``
  without dragging Redis, aiofiles or tiktoken into the client dependency set.
* Text only.  File attachments and provider-native ``tool_use`` /
  ``tool_result`` blocks are explicitly out of scope — ``ConversationTurn``
  does not store them.

This function is also the extension point per-turn compaction (FEAT-525)
uses: :func:`render_history`'s first parameter accepts either a
:class:`ConversationHistory` (unchanged, byte-identical output) or a
``Sequence[TurnView]`` produced by
:func:`parrot.memory.compaction.compact.compact_history`, in which case the
already-materialized ``assistant_suffix`` (tool activity / omission notices)
is appended to each assistant message before the usual merge/alternation
logic runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, List, Literal, Optional, Sequence, Tuple, Union

from .abstract import ConversationHistory

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Never imported at runtime — keeps this module a leaf that does not
    # pull in parrot.memory.compaction (orjson/tiktoken) for every consumer.
    from .compaction.models import TurnView

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


def _iter_rows(
    source: Union[Optional[ConversationHistory], Sequence["TurnView"]],
    max_turns: Optional[int],
) -> Iterable[Tuple[str, Optional[str], str, str]]:
    """Yield ``(turn_id, chatbot_id, user_text, assistant_text)`` rows.

    Dispatches by duck-typing: an object with a ``.turns`` attribute is
    treated as a :class:`ConversationHistory` (``max_turns`` applies as
    before); any other (non-``None``) source is treated as a
    ``Sequence[TurnView]`` (``max_turns`` is ignored — compaction already
    applied the ceiling). For views, ``assistant_text`` already carries the
    view's ``assistant_suffix`` appended, *unless* the view's own text is
    blank — a blank view renders as a blank row exactly like a turn with a
    blank ``assistant_response``, so the suffix never rescues it.

    Args:
        source: A :class:`ConversationHistory`, a ``Sequence[TurnView]``, or
            ``None``.
        max_turns: Applies only to the history path; ``None`` keeps all.

    Yields:
        One row per turn/view, oldest to newest.
    """
    if source is None:
        return

    if hasattr(source, "turns"):
        turns = source.turns
        if not turns:
            return
        if max_turns is not None:
            if max_turns <= 0:
                return
            turns = turns[-max_turns:]
        for turn in turns:
            yield turn.turn_id, turn.chatbot_id, turn.user_message or "", turn.assistant_response or ""
        return

    for view in source:
        assistant_text = view.assistant_text or ""
        row_assistant = f"{assistant_text}{view.assistant_suffix}" if assistant_text.strip() else ""
        yield view.turn_id, view.chatbot_id, view.user_text or "", row_assistant


def render_history(
    history: Union[Optional[ConversationHistory], Sequence["TurnView"]],
    *,
    max_turns: Optional[int] = None,
    current_chatbot_id: Optional[str] = None,
    include_other_agents: bool = True,
    other_agent_label: str = "[agent:{chatbot_id}]",
) -> List[HistoryMessage]:
    """Render a conversation history (or turn views) into alternating messages.

    Args:
        history: A :class:`ConversationHistory` to render, or a
            ``Sequence[TurnView]`` (e.g. from
            :func:`parrot.memory.compaction.compact.compact_history`).
            ``None`` or an empty history/sequence renders to ``[]``. For a
            view sequence, each view's ``assistant_suffix`` (already
            rendered tool activity / omission notices) is appended to its
            assistant message before the merge/alternation logic below;
            plain-history output is unaffected and byte-identical.
        max_turns: Keep only the most recent ``N`` turns. ``None`` keeps all.
            Values ``<= 0`` also render to ``[]``. Ignored for a view
            sequence — compaction already applied its own ceiling.
        current_chatbot_id: The agent doing the asking. Turns/views whose
            ``chatbot_id`` differs are considered *foreign*; one with
            ``chatbot_id is None`` (legacy, pre-attribution) is always treated
            as belonging to the current agent. When ``current_chatbot_id`` is
            ``None`` no turn is foreign.
        include_other_agents: When ``False``, foreign turns/views are dropped
            entirely. When ``True`` (the default) they are kept and their
            assistant text is prefixed with ``other_agent_label`` so the model
            can tell who said what — the crew/flow shared-history case. The
            label precedes both the assistant text and its suffix.
        other_agent_label: Format string for the foreign-turn prefix; receives
            ``chatbot_id`` as its only field.

    Returns:
        A list of :class:`HistoryMessage` with these guarantees:

        * roles strictly alternate; the list starts with ``"user"`` and ends
          with ``"assistant"`` (or is empty);
        * consecutive same-role messages are merged with a blank line;
        * a turn/view whose assistant text is empty or whitespace-only
          contributes nothing at all — never an empty assistant message,
          and never rescued by a non-empty ``assistant_suffix``;
        * the input ``history``/views are not modified.
    """
    rendered: List[HistoryMessage] = []

    for turn_id, chatbot_id, user_text, assistant_text in _iter_rows(history, max_turns):
        if not assistant_text.strip():
            # An assistant message with no text is not a usable turn: it would
            # either be rejected by the provider or teach the model to answer
            # with silence. Skip the whole row so alternation stays intact.
            continue

        is_foreign = (
            current_chatbot_id is not None and chatbot_id is not None and chatbot_id != current_chatbot_id
        )
        if is_foreign and not include_other_agents:
            continue
        if is_foreign:
            label = other_agent_label.format(chatbot_id=chatbot_id)
            assistant_text = f"{label} {assistant_text}"

        _append(
            rendered,
            HistoryMessage(role="user", content=user_text, chatbot_id=chatbot_id, turn_id=turn_id),
        )
        _append(
            rendered,
            HistoryMessage(role="assistant", content=assistant_text, chatbot_id=chatbot_id, turn_id=turn_id),
        )

    return rendered
