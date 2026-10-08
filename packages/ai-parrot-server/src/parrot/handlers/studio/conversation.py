"""Conversation-memory backend of Studio-built bots and the Studio assistant.

By default a bot keeps its history in-process (``InMemoryConversation``), which is lost whenever a turn is served by
another gunicorn worker / pod or the idle instance is swept. A host running more than one worker sets
``STUDIO_CONVERSATION_BACKEND=redis`` so any worker can serve any turn: the history lives in Redis under
``(chatbot_id, user_id, session_id)`` and expires after ``STUDIO_CONVERSATION_TTL_SECONDS`` of inactivity.
"""

from __future__ import annotations

import logging
from typing import Any

from navconfig import config

logger = logging.getLogger("Parrot.AgentStudio")

BACKEND_SETTING = "STUDIO_CONVERSATION_BACKEND"
REDIS_URL_SETTING = "STUDIO_CONVERSATION_REDIS_URL"
TTL_SETTING = "STUDIO_CONVERSATION_TTL_SECONDS"
DEFAULT_TTL_SECONDS = 86400
KEY_PREFIX = "studio_conversation"


def studio_conversation_kwargs() -> dict[str, Any]:
    """Bot constructor kwargs selecting the Studio conversation backend (``{}`` keeps the in-process default).

    Settings (environment / navconfig):

    - ``STUDIO_CONVERSATION_BACKEND``: ``memory`` (default) or ``redis``.
    - ``STUDIO_CONVERSATION_REDIS_URL``: Redis URL; default the core history URL (``REDIS_HISTORY_URL``).
    - ``STUDIO_CONVERSATION_TTL_SECONDS``: idle expiry of a conversation (default 86400; ``0`` = never).

    Returns:
        ``{"memory_type": "redis", "memory_config": {...}}`` when the redis backend is selected, else ``{}``.
        An unknown backend value is logged and treated as ``memory``.
    """
    backend = str(config.get(BACKEND_SETTING) or "memory").strip().lower()
    if backend == "memory":
        return {}
    if backend != "redis":
        logger.error("%s=%r is not 'memory' or 'redis'; using memory", BACKEND_SETTING, backend)
        return {}
    memory_config: dict[str, Any] = {"key_prefix": KEY_PREFIX}
    if url := config.get(REDIS_URL_SETTING):
        memory_config["redis_url"] = str(url)
    raw_ttl = config.get(TTL_SETTING)
    try:
        ttl = int(float(raw_ttl)) if raw_ttl not in (None, "") else DEFAULT_TTL_SECONDS
    except (TypeError, ValueError):
        logger.error("%s=%r is not a number; using %s", TTL_SETTING, raw_ttl, DEFAULT_TTL_SECONDS)
        ttl = DEFAULT_TTL_SECONDS
    if ttl > 0:
        memory_config["history_ttl"] = ttl
    return {"memory_type": "redis", "memory_config": memory_config}
