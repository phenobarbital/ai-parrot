"""Agent tooling specs (FEAT-593): the one shape for toolkit / MCP configuration."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from parrot.security.vault_utils import retrieve_vault_credential

logger = logging.getLogger(__name__)

SECRET_MASK: str = "********"
MCP_SECRET_FIELDS: tuple[str, ...] = ("headers", "auth_config", "env")


class ToolkitSpec(BaseModel):
    """Agent-level (or per-user override) configuration of one toolkit."""

    model_config = ConfigDict(extra="forbid")
    slug: str
    params: dict[str, Any] = Field(default_factory=dict)
    user_overridable: list[str] = Field(default_factory=list)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    vault_owner: str | None = None


class AgentMCPServerSpec(BaseModel):
    """Agent-level MCP server; ``headers``/``auth_config``/``env`` live in the vault."""

    model_config = ConfigDict(extra="forbid")
    name: str
    transport: str = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    description: str | None = None
    auth_type: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    vault_owner: str | None = None


class NormalizedTooling(BaseModel):
    """Output of :func:`normalize_tooling`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    tools: list[Any] = Field(default_factory=list)
    toolkits: list[ToolkitSpec] = Field(default_factory=list)
    mcp_servers: list[AgentMCPServerSpec] = Field(default_factory=list)


def toolkit_vault_name(slug: str, agent_name: str) -> str:
    """Return ``f"toolkit_{slug}_{agent_name}"``."""
    return f"toolkit_{slug}_{agent_name}"


def mcp_vault_name(server: str, agent_name: str) -> str:
    """Return ``f"mcp_agent_{server}_{agent_name}"`` (never collides with per-user ``mcp_``)."""
    return f"mcp_agent_{server}_{agent_name}"


def normalize_tooling(
    tools: Sequence[Any] | None,
    toolkits: Sequence[Any] | None = None,
    mcp_servers: Sequence[Any] | None = None,
    *,
    toolkit_config: dict[str, dict[str, Any]] | None = None,
) -> NormalizedTooling:
    """Merge every legacy shape into (tools, toolkit specs, mcp specs).

    Bare strings in ``toolkits`` become ``ToolkitSpec(slug=s)``; dicts are validated.
    ``toolkit_config`` is the DB JSONB map ``{slug: spec-dict}`` (``slug`` key optional).
    A slug that is both a plain tool name and a spec is emitted once, as the spec.
    Duplicate specs for one slug: the last one wins (WARNING). Invalid entries → WARNING, dropped.
    """
    specs: dict[str, ToolkitSpec] = {}

    def add_spec(candidate: Any) -> None:
        """Validate and retain one toolkit specification."""
        try:
            spec = candidate if isinstance(candidate, ToolkitSpec) else ToolkitSpec.model_validate(candidate)
        except ValidationError:
            logger.warning("Dropping invalid toolkit specification")
            return
        except (TypeError, ValueError):
            logger.warning("Dropping invalid toolkit specification")
            return

        key = spec.slug.lower()
        if key in specs:
            logger.warning("Duplicate toolkit specification for slug %s; using the last entry", spec.slug)
        specs[key] = spec

    for entry in toolkits or ():
        add_spec({"slug": entry} if isinstance(entry, str) else entry)

    for slug, config in (toolkit_config or {}).items():
        if not isinstance(config, dict):
            logger.warning("Dropping invalid toolkit configuration for slug %s", slug)
            continue
        entry = dict(config)
        entry.setdefault("slug", slug)
        add_spec(entry)

    plain = [tool for tool in tools or () if not isinstance(tool, str) or tool.lower() not in specs]
    mcp: list[AgentMCPServerSpec] = []
    for entry in mcp_servers or ():
        try:
            if isinstance(entry, AgentMCPServerSpec):
                mcp.append(entry)
                continue
            if not isinstance(entry, dict):
                raise TypeError("MCP server specification must be a dict")
            config = dict(entry)
            params = dict(config.pop("params", {}))
            for field in MCP_SECRET_FIELDS:
                if field in config:
                    params[field] = config.pop(field)
            config["params"] = params
            mcp.append(AgentMCPServerSpec.model_validate(config))
        except (TypeError, ValueError, ValidationError):
            logger.warning("Dropping invalid MCP server specification")

    return NormalizedTooling(tools=plain, toolkits=list(specs.values()), mcp_servers=mcp)


def tooling_revision(toolkits: Sequence[ToolkitSpec], mcp_servers: Sequence[AgentMCPServerSpec]) -> str:
    """sha256 of the canonical JSON of both lists (secret values are never in a spec)."""
    payload = {
        "toolkits": [toolkit.model_dump(mode="json") for toolkit in toolkits],
        "mcp": [server.model_dump(mode="json") for server in mcp_servers],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _set_dotted(target: dict[str, Any], dotted: str, value: Any) -> None:
    """Set ``value`` at ``a.0.b`` inside nested dicts/lists (list indexes are ints)."""
    parts = dotted.split(".")
    current: Any = target
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        if isinstance(current, list):
            list_index = int(part)
            while len(current) <= list_index:
                current.append({})
            if is_last:
                current[list_index] = value
                return
            current = current[list_index]
            continue

        if is_last:
            current[part] = value
            return
        next_part = parts[index + 1]
        current = current.setdefault(part, [] if next_part.isdigit() else {})


async def hydrate_params(spec: ToolkitSpec) -> dict[str, Any]:
    """Return a deep copy of ``spec.params`` with vault secrets restored.

    Raises KeyError (missing vault entry) / RuntimeError (vault unconfigured). Never logs values.
    """
    params = copy.deepcopy(spec.params)
    if not spec.secret_refs:
        return params

    grouped_refs: dict[str, list[str]] = {}
    for dotted, vault_name in spec.secret_refs.items():
        grouped_refs.setdefault(vault_name, []).append(dotted)
    for vault_name, dotted_keys in grouped_refs.items():
        secrets = await retrieve_vault_credential(spec.vault_owner or "", vault_name)
        for dotted in dotted_keys:
            _set_dotted(params, dotted, secrets[dotted])
    return params


async def hydrate_mcp(spec: AgentMCPServerSpec) -> dict[str, Any]:
    """Return ``MCPServerConfig`` kwargs with headers/auth_config/env restored from the vault."""
    base = spec.model_dump(exclude={"params", "secret_refs", "vault_owner"}, exclude_none=True)
    base.update(spec.params)
    grouped_fields: dict[str, list[str]] = {}
    for field, vault_name in spec.secret_refs.items():
        grouped_fields.setdefault(vault_name, []).append(field)
    for vault_name, fields in grouped_fields.items():
        secrets = await retrieve_vault_credential(spec.vault_owner or "", vault_name)
        for field in fields:
            base[field] = secrets[field]
    return base


def mask_spec(spec: ToolkitSpec) -> dict[str, Any]:
    """API dump: every ``secret_refs`` key rendered as ``SECRET_MASK`` inside ``params``."""
    data = spec.model_dump(mode="json")
    for dotted in spec.secret_refs:
        _set_dotted(data["params"], dotted, SECRET_MASK)
    return data


def mask_mcp(spec: AgentMCPServerSpec) -> dict[str, Any]:
    """API dump of an MCP spec: each vaulted field rendered as ``SECRET_MASK``."""
    data = spec.model_dump(mode="json")
    for field in spec.secret_refs:
        data[field] = SECRET_MASK
    return data
