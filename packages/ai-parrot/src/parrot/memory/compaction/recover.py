"""``read_omitted_content`` recovery tool for per-turn conversation compaction (FEAT-525).

Recovers omitted bytes through one plain async function bound to a
:class:`~parrot.memory.abstract.ConversationMemory`, registered on the
bot's ``ToolManager`` exactly like the ``search_tools`` meta-tool (the
bot-side registration happens in ``AbstractBot._register_recovery_tool``,
TASK-2830). The function resolves its session key from three ContextVars
and **fails closed** on any ``None`` — it never touches the store unless
the full scope is known.

Leaf-module rule: this module imports :mod:`parrot.observability.context`
and :mod:`parrot.memory.*` only — never :mod:`parrot.tools` (registration
is the bot's job).
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from parrot.memory.abstract import ConversationMemory
from parrot.memory.compaction.omission import EXPIRED_MESSAGE
from parrot.observability.context import current_memory_key_id, current_session_id, current_user_id

logger = logging.getLogger(__name__)

READ_OMITTED_CONTENT_NAME: str = "read_omitted_content"

READ_OMITTED_CONTENT_DESCRIPTION: str = (
    "Recover the exact original bytes of a tool output that was omitted from "
    "conversation history. Call this when you see a `<tool-output-omitted "
    'tool="..." chars="..." id="om_..."/>` notice and need the full content: '
    "pass its `content_id` to recover just that output, or a turn's `turn_id` "
    "to recover every output omitted from that turn."
)

READ_OMITTED_CONTENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "content_id": {
            "type": "string",
            "description": "The `om_...` id from a `<tool-output-omitted .../>` notice.",
        },
        "turn_id": {
            "type": "string",
            "description": "Recover every output omitted from this turn instead of a single id.",
        },
    },
    "required": [],
}

#: Returned when the ContextVar scope (memory key, user, session) is not
#: fully bound — the store is never touched in this case.
UNAVAILABLE_MESSAGE: str = "read_omitted_content is unavailable in this context (no active conversation scope)."

#: Returned when neither ``content_id`` nor ``turn_id`` is given.
NO_ARGS_MESSAGE: str = "Provide content_id (om_…) or turn_id."


def bind_read_omitted_content(memory: ConversationMemory) -> Callable[..., Awaitable[str]]:
    """Bind a ``read_omitted_content`` function to a specific memory backend.

    Args:
        memory: The :class:`ConversationMemory` whose omission store and
            ``omission_key`` scoping this function will use.

    Returns:
        An ``async def read_omitted_content(content_id=None, turn_id=None) -> str``
        closure, named and documented for ``ToolManager.register_tool``.
    """

    async def read_omitted_content(content_id: Optional[str] = None, turn_id: Optional[str] = None) -> str:
        """Return the exact bytes of an omitted tool output (by content_id) or every omitted block of a turn.

        Args:
            content_id: The ``om_...`` id from a ``<tool-output-omitted
                .../>`` notice.
            turn_id: Recover every output omitted from this turn instead
                of a single id.

        Returns:
            The recovered content (or a fixed message when unavailable,
            expired, or no arguments were given). Never raises.
        """
        key_id = current_memory_key_id.get()
        user_id = current_user_id.get()
        session_id = current_session_id.get()
        if key_id is None or user_id is None or session_id is None:
            logger.debug(
                "read_omitted_content called with an incomplete scope "
                "(memory_key_id=%r, user_id=%r, session_id=%r); failing closed.",
                key_id,
                user_id,
                session_id,
            )
            return UNAVAILABLE_MESSAGE

        session_key = memory.omission_key(user_id, session_id, key_id)
        store = memory.omission_store

        if content_id:
            found = await store.get(session_key, content_id)
            if found is None:
                return EXPIRED_MESSAGE.format(content_id=content_id)
            return found

        if turn_id:
            ids = await store.list_by_turn(session_key, turn_id)
            blocks: List[str] = []
            for cid in ids:
                content = await store.get(session_key, cid)
                if content is not None:
                    blocks.append(f'<omitted id="{cid}">\n{content}\n</omitted>')
            if not blocks:
                return f"No omitted content is known for turn {turn_id} — it may have expired; re-run the tool."
            return "\n".join(blocks)

        return NO_ARGS_MESSAGE

    read_omitted_content.__name__ = READ_OMITTED_CONTENT_NAME
    return read_omitted_content
