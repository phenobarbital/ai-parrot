"""Agent-level tooling persistence for Agent Studio (FEAT-593). Single writer."""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import jsonschema
from pydantic import ValidationError

from parrot.conf import AGENTS_DIR
from parrot.knowledge.wiki import LLMWikiToolkit
from parrot.security.vault_utils import (
    delete_vault_credential,
    retrieve_vault_credential,
    store_vault_credential,
)
from parrot.tools.config_schema import build_schema_envelope, secret_paths
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.infographic_toolkit import InfographicToolkit
from parrot.tools.spec import (
    MCP_SECRET_FIELDS,
    SECRET_MASK,
    AgentMCPServerSpec,
    NormalizedTooling,
    ToolkitSpec,
    mcp_vault_name,
    normalize_tooling,
    toolkit_vault_name,
)

from ..models import BotModel
from .toolkits import _resolve_toolkit_class

logger = logging.getLogger(__name__)
_EXPLICIT = {"dataset_manager": DatasetManager, "wiki": LLMWikiToolkit, "infographic": InfographicToolkit}
_SERVER_MANAGED = {
    "wiki": frozenset({"pageindex_toolkit", "graphindex_toolkit", "okf_toolkit"}),
    "infographic": frozenset({"artifact_store"}),
}


@dataclass
class ToolingState:
    """Loaded editable tooling state and its persistence source."""

    tooling: NormalizedTooling
    editable: bool
    reason: str | None
    owner: str | None
    source: Literal["database", "registry"]


def _pop_dotted(target: dict[str, Any], dotted: str) -> tuple[bool, Any]:
    """Pop a dotted dict/list value without modifying unrelated siblings."""
    current: Any = target
    parts = dotted.split(".")
    for part in parts[:-1]:
        if isinstance(current, list):
            if not part.isdigit() or int(part) >= len(current):
                return False, None
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    final = parts[-1]
    if isinstance(current, list) and final.isdigit() and int(final) < len(current):
        return True, current.pop(int(final))
    if isinstance(current, dict) and final in current:
        return True, current.pop(final)
    return False, None


class AgentToolingStore:
    """Load and persist agent-level toolkit / MCP configuration (DB row or agent YAML)."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler

    async def load(self, name: str) -> ToolingState:
        """Load agent tooling, raising ``LookupError`` when the agent is unknown."""
        row = await self.handler._get_db_agent(name)
        if row is not None:
            owner = str(row.created_by) if row.created_by is not None else None
            state = ToolingState(
                tooling=normalize_tooling([], mcp_servers=row.mcp_servers, toolkit_config=row.toolkit_config),
                editable=owner is not None,
                reason=None if owner is not None else "agent has no owner; cannot store secrets",
                owner=owner,
                source="database",
            )
            state._row = row
            return state

        registry = self.handler._registry()
        meta = registry.get_metadata(name) if registry is not None else None
        if meta is None:
            raise LookupError(name)
        bot_config = getattr(meta, "bot_config", None)
        owner = self.handler._registry_agent_owner(meta)
        reason = self._registry_read_only_reason(name, meta, bot_config)
        if reason is None and owner is None:
            reason = "agent has no owner; cannot store secrets"
        state = ToolingState(
            tooling=normalize_tooling(
                [],
                toolkits=getattr(bot_config, "toolkits", []),
                mcp_servers=getattr(bot_config, "mcp_servers", []),
            ),
            editable=reason is None,
            reason=reason,
            owner=owner,
            source="registry",
        )
        state._registry = registry
        return state

    @staticmethod
    def _registry_read_only_reason(name: str, meta: Any, bot_config: Any) -> str | None:
        """Return the same editability failure that registry persistence would raise."""
        if bot_config is None:
            return f"Agent '{name}' has no declarative bot_config to rewrite."
        path = Path(meta.file_path).resolve() if getattr(meta, "file_path", None) else None
        if path is None:
            return f"Agent '{name}' has no on-disk file_path to rewrite."
        if path.suffix not in (".yaml", ".yml"):
            return f"Agent '{name}' is not defined by a YAML file ({path.name}); refusing to edit."
        if not path.is_relative_to(AGENTS_DIR.resolve()):
            return f"Agent '{name}' definition {path} is outside AGENTS_DIR; refusing to edit."
        if path.stem != name.lower():
            return f"Agent '{name}' definition file does not match the expected agent name."
        return None

    def schema_for(self, slug: str) -> tuple[type, dict[str, Any]]:
        """Return the class and JSON schema for ``slug``."""
        cls = _EXPLICIT.get(slug) or _resolve_toolkit_class(slug)
        if cls is None:
            raise LookupError(slug)
        envelope = build_schema_envelope(slug, cls, server_managed=_SERVER_MANAGED.get(slug, frozenset()))
        return cls, envelope.schema

    @staticmethod
    def _validate(cls: type, schema: dict[str, Any], params: dict[str, Any]) -> None:
        """Validate client params after masked secret values have been removed."""
        masked = copy.deepcopy(params)
        for path in secret_paths(schema, masked):
            found, value = _pop_dotted(masked, path)
            if found and value == SECRET_MASK:
                continue
            if found:
                # Secrets are opaque to structural validation; they have already been classified.
                _pop_dotted(masked, path)
        try:
            config_model = getattr(cls, "config_model", None)
            if config_model is not None:
                config_model(**masked)
            else:
                jsonschema.Draft202012Validator(schema).validate(masked)
        except (ValidationError, jsonschema.ValidationError) as exc:
            raise ValueError(f"Invalid toolkit parameters: {exc}") from exc

    @staticmethod
    def _reject_server_managed(schema: dict[str, Any], params: dict[str, Any]) -> None:
        """Reject top-level fields reserved for server construction."""
        forbidden = [
            key
            for key, value in params.items()
            if schema.get("properties", {}).get(key, {}).get("x-server-managed") is True
        ]
        if forbidden:
            raise ValueError(f"Server-managed parameters cannot be set: {', '.join(sorted(forbidden))}")

    async def put_toolkit(
        self, name: str, slug: str, params: dict[str, Any], user_overridable: list[str]
    ) -> ToolkitSpec:
        """Validate, vault secrets under the owner, and persist a toolkit specification."""
        state = await self.load(name)
        if not state.editable:
            raise PermissionError(state.reason or "agent tooling is read-only")
        cls, schema = self.schema_for(slug)
        self._reject_server_managed(schema, params)
        self._validate(cls, schema, params)
        spec = await self._split_secrets(state, slug, name, schema, params, user_overridable)
        state.tooling.toolkits = [item for item in state.tooling.toolkits if item.slug.lower() != slug.lower()]
        state.tooling.toolkits.append(spec)
        await self._persist(name, state)
        return spec

    async def delete_toolkit(self, name: str, slug: str) -> None:
        """Remove one toolkit specification and its owner-scoped vault entry."""
        state = await self.load(name)
        if not state.editable:
            raise PermissionError(state.reason or "agent tooling is read-only")
        state.tooling.toolkits = [item for item in state.tooling.toolkits if item.slug.lower() != slug.lower()]
        if state.owner is None:
            raise PermissionError("agent has no owner; cannot store secrets")
        await delete_vault_credential(state.owner, toolkit_vault_name(slug, name))
        await self._persist(name, state)

    async def put_mcp_servers(self, name: str, servers: list[dict[str, Any]]) -> list[AgentMCPServerSpec]:
        """Vault MCP secret fields and replace the agent's complete server list."""
        state = await self.load(name)
        if not state.editable or state.owner is None:
            raise PermissionError(state.reason or "agent has no owner; cannot store secrets")
        previous = {item.name: item for item in state.tooling.mcp_servers}
        specs: list[AgentMCPServerSpec] = []
        for raw in servers:
            payload = copy.deepcopy(raw)
            params = dict(payload.pop("params", {}))
            for field in MCP_SECRET_FIELDS:
                if field in payload:
                    params[field] = payload.pop(field)
            try:
                candidate = AgentMCPServerSpec.model_validate({**payload, "params": params})
            except ValidationError as exc:
                raise ValueError(f"Invalid MCP server parameters: {exc}") from exc
            vault_name = mcp_vault_name(candidate.name, name)
            prior = previous.get(candidate.name)
            refs = dict(prior.secret_refs) if prior is not None else {}
            clean = dict(candidate.params)
            merged: dict[str, Any] = {}
            for field in MCP_SECRET_FIELDS:
                if field not in clean:
                    continue
                value = clean.pop(field)
                if value == SECRET_MASK:
                    if field in refs:
                        continue
                else:
                    merged[field] = value
                    refs[field] = vault_name
            if merged:
                try:
                    current = await retrieve_vault_credential(state.owner, vault_name)
                except KeyError:
                    current = {}
                current.update(merged)
                await store_vault_credential(state.owner, vault_name, current)
            specs.append(candidate.model_copy(update={"params": clean, "secret_refs": refs, "vault_owner": state.owner}))
        state.tooling.mcp_servers = specs
        await self._persist(name, state)
        return specs

    async def _split_secrets(
        self,
        state: ToolingState,
        slug: str,
        name: str,
        schema: dict[str, Any],
        params: dict[str, Any],
        user_overridable: list[str],
    ) -> ToolkitSpec:
        """Move x-secret values into the owner-scoped toolkit vault entry."""
        if state.owner is None:
            raise PermissionError("agent has no owner; cannot store secrets")
        previous = next((item for item in state.tooling.toolkits if item.slug.lower() == slug.lower()), None)
        vault_name = toolkit_vault_name(slug, name)
        clean = copy.deepcopy(params)
        refs = dict(previous.secret_refs) if previous is not None else {}
        merged: dict[str, Any] = {}
        for path in secret_paths(schema, params):
            found, value = _pop_dotted(clean, path)
            if not found:
                continue
            if value == SECRET_MASK:
                if path in refs:
                    continue
            else:
                merged[path] = value
                refs[path] = vault_name
        if merged:
            try:
                current = await retrieve_vault_credential(state.owner, vault_name)
            except KeyError:
                current = {}
            current.update(merged)
            await store_vault_credential(state.owner, vault_name, current)
        return ToolkitSpec(
            slug=slug,
            params=clean,
            user_overridable=user_overridable,
            secret_refs=refs,
            vault_owner=state.owner,
        )

    async def _persist(self, name: str, state: ToolingState) -> None:
        """Persist normalized specs to either the DB row or agent-owned YAML."""
        if state.source == "database":
            db = self.handler.request.app.get("database")
            if db is None:
                raise RuntimeError("database unavailable")
            async with await db.acquire():
                row: BotModel = state._row
                row.set(
                    "toolkit_config",
                    {item.slug: item.model_dump(exclude={"slug"}) for item in state.tooling.toolkits},
                )
                row.set("mcp_servers", [item.model_dump(exclude_defaults=True) for item in state.tooling.mcp_servers])
                await row.update()
        else:
            state._registry.update_agent_tooling(
                name,
                toolkits=state.tooling.toolkits,
                mcp_servers=state.tooling.mcp_servers,
            )
