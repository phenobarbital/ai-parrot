"""Shared Pydantic request/response models for ``/api/v1/astudio/*``.

FEAT-467 TASK-2511 (spec §2 Data Models). Handlers import from here
rather than declaring per-endpoint duplicates, so the request/response
contract for the Studio API stays in one place across the
``handlers/studio/`` package.
"""

from __future__ import annotations

from typing import Any

from parrot.skills.models import SkillCategory
from pydantic import BaseModel, Field, SecretStr

# BotManager.reload_agent's return type IS the Studio reload response
# shape (name / reloaded / previous_instance_closed / warnings) — defined
# once in FEAT-467 TASK-2510 and re-exported here rather than duplicated,
# so there is exactly one "ReloadResult" definition to keep in sync.
from parrot.manager.manager import ReloadResult  # noqa: F401


class StudioError(BaseModel):
    """Common Studio error response shape.

    Attributes:
        message: Human-readable error description.
        code: Optional machine-readable error code (e.g. ``"not_found"``).
        details: Optional structured detail payload (validation errors,
            offending fields, etc.).
    """

    message: str
    code: str | None = None
    details: dict[str, Any] | None = None


class CreateAgentRequest(BaseModel):
    """``POST /astudio/agents`` payload (TASK-2512).

    Attributes:
        name: Agent slug — validated against
            :data:`handlers.studio._base.STUDIO_SLUG_RE` by the handler.
        bot_class: Agent base class name (e.g. ``"BasicBot"``, ``"Agent"``).
        llm: Optional ``"provider:model"`` string.
        description: Optional human-readable description.
        persist: When ``True``, also writes an ``agent:``-keyed YAML
            definition via ``AgentRegistry.create_agent_definition``
            (FEAT-467 TASK-2509) under ``AGENTS_DIR/agents/<category>/``.
        category: YAML category sub-directory (only relevant when
            ``persist=True``).
        config: Free-form startup config merged into the agent's kwargs.
    """

    name: str
    bot_class: str = "BasicBot"
    llm: str | None = None
    description: str | None = None
    persist: bool = False
    category: str = "general"
    config: dict[str, Any] = Field(default_factory=dict)


class DraftValidationReport(BaseModel):
    """Static-validation result for a generated draft agent (TASK-2513).

    Attributes:
        passed: ``True`` when the draft cleared AST/import-allowlist/
            single-subclass validation.
        errors: Validation findings — each a dict with ``line``, ``code``,
            and ``message`` keys.
    """

    passed: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)


class SkillPublishRequest(BaseModel):
    """``POST /astudio/skills`` payload (TASK-2515).

    Attributes:
        name: Skill name (unique within the shared org-wide catalog).
        description: Human-readable description.
        category: Constrained to :class:`~parrot.skills.models.SkillCategory`;
            out-of-vocabulary values map to ``general`` (handler-side).
        triggers: Trigger phrases/commands for the skill.
        body: Skill markdown body (including frontmatter).
    """

    name: str
    description: str
    category: SkillCategory
    triggers: list[str] = Field(default_factory=list)
    body: str


class ByokKeyRequest(BaseModel):
    """``POST /astudio/keys`` payload (TASK-2516).

    Attributes:
        provider: LLM provider id — validated against
            ``parrot.clients.factory.SUPPORTED_CLIENTS`` by the handler.
        api_key: The provider API key. ``SecretStr`` so it never appears
            in logs/reprs; never returned in plaintext (spec §7 BYOK
            security).
    """

    provider: str
    api_key: SecretStr


class ToolkitConfigPutRequest(BaseModel):
    """``PUT /astudio/agents/{name}/toolkits/{slug}`` payload (FEAT-593)."""

    params: dict[str, Any] = Field(default_factory=dict)
    user_overridable: list[str] = Field(default_factory=list)


class AgentToolkitsResponse(BaseModel):
    """``GET /astudio/agents/{name}/toolkits`` — specs are masked dumps."""

    agent: str
    editable: bool
    reason: str | None = None
    toolkits: list[dict[str, Any]] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)


class ToolkitPersistResponse(BaseModel):
    """Response of every agent-level tooling write."""

    agent: str
    slug: str | None = None
    reload_required: bool = True
    persisted: bool = True


class AgentMcpServersPutRequest(BaseModel):
    """``PUT /astudio/agents/{name}/mcp-servers`` payload (replaces the list)."""

    servers: list[dict[str, Any]] = Field(default_factory=list)


class AgentMcpServersResponse(BaseModel):
    """``GET /astudio/agents/{name}/mcp-servers`` — masked dumps."""

    agent: str
    editable: bool
    reason: str | None = None
    servers: list[dict[str, Any]] = Field(default_factory=list)


class ToolkitOptionsResponse(BaseModel):
    """``GET …/toolkits/{slug}/options/{param}``."""

    options: list[dict[str, str]] = Field(default_factory=list)
