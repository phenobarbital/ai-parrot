"""Codegen-side response models for Admin UI endpoints without a native
Pydantic response model.

``GET /api/v1/bots`` (``parrot.handlers.bots``) builds its JSON payload by
hand from ``dict``s — :class:`BotsListResponse` is a descriptor for the TS
codegen pipeline (TASK-2526) only; it is NOT imported by
``parrot.handlers.bots`` and does not change that handler's behavior.

Kept separate from ``parrot.server.ui.status`` (TASK-2524) because it
describes a different endpoint (``/api/v1/bots``, not
``/api/v1/admin/status``) and has no runtime consumer of its own.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class BotAgentItem(BaseModel):
    """A single agent entry as emitted by ``GET /api/v1/bots``.

    Deliberately permissive: database-backed agents are serialized via
    ``ChatbotHandler._bot_model_to_dict`` (full ``BotModel`` field set),
    while registry-backed agents without a ``bot_config`` fall back to a
    small ad hoc shape (``name``, ``module_path``, ``file_path``,
    ``singleton``, ``at_startup``, ``priority``, ``tags``) — see
    ``parrot.handlers.bots.ChatbotHandler._bot_model_to_dict`` /
    ``._registry_agent_to_dict``. Only ``name`` and ``source`` are pinned
    down here; every other field is allowed but not required.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    source: Literal["database", "registry"]


class BotsListResponse(BaseModel):
    """Response body for ``GET /api/v1/bots`` (``parrot.handlers.bots``)."""

    agents: list[BotAgentItem]
    total: int
