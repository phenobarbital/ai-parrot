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

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class ToolInfo(BaseModel):
    """A single tool entry as emitted by ``GET /api/v1/agent_tools``
    (``parrot.handlers.bots.ToolList``) — codegen descriptor only, not
    imported by the handler (see module docstring)."""

    tool_name: str
    module_path: str
    description: str | None = None


class ToolsListResponse(BaseModel):
    """Response body for ``GET /api/v1/agent_tools``."""

    tools: dict[str, ToolInfo]


class BotWritePayload(BaseModel):
    """Body accepted by ``PUT /api/v1/bots`` (create) and
    ``POST /api/v1/bots/{name}`` (update).

    Mirrors the user-editable ``BotModel`` fields (``parrot.handlers.
    models.bots.BotModel``); codegen descriptor only — ``ChatbotHandler``
    reads its payload as a plain dict, never this model. All fields are
    optional except ``name`` on create (enforced by the handler, not here).

    ``model_config`` is a reserved attribute name on ``pydantic.BaseModel``,
    so the wire field is declared as ``model_config_`` with an alias; with
    ``populate_by_name=True`` the generated JSON Schema/TS type still
    exposes the wire name ``model_config``.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    storage: Literal["database"] | None = None  # create only
    name: str | None = None
    description: str | None = None
    avatar: str | None = None
    enabled: bool | None = None
    timezone: str | None = None
    language: str | None = None
    disclaimer: str | None = None
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    rationale: str | None = None
    capabilities: str | None = None
    system_prompt_template: str | None = None
    human_prompt_template: str | None = None
    pre_instructions: list[str] | None = None
    prompt_config: dict[str, Any] | None = None
    llm: str | None = None
    model_config_: dict[str, Any] | None = Field(default=None, alias="model_config")
    tools_enabled: bool | None = None
    auto_tool_detection: bool | None = None
    tool_threshold: float | None = None
    tools: list[str] | None = None
    operation_mode: Literal["conversational", "agentic", "adaptive"] | None = None
    use_kb: bool | None = None
    kb: list[dict[str, Any]] | None = None
    custom_kbs: list[str] | None = None
    use_vector: bool | None = None
    vector_store_config: dict[str, Any] | None = None
    reranker_config: dict[str, Any] | None = None
    parent_searcher_config: dict[str, Any] | None = None
    context_search_limit: int | None = None
    context_score_threshold: float | None = None
    memory_type: Literal["memory", "file", "redis"] | None = None
    memory_config: dict[str, Any] | None = None
    max_context_turns: int | None = None
    use_conversation_history: bool | None = None
    bot_class: str | None = None
    permissions: dict[str, Any] | list[dict[str, Any]] | None = None


class BotMutationResponse(BaseModel):
    """Response body shared by ``PUT``/``POST``/``DELETE`` on
    ``ChatbotHandler`` (create/update/delete)."""

    message: str
    name: str
    source: str | None = None
    chatbot_id: str | None = None  # create only
    vector_store_status: str | None = None  # create only
    vector_store_error: str | None = None
