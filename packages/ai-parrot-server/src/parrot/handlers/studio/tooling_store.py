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
from parrot.security.vault_utils import (
    delete_vault_credential,
    retrieve_vault_credential,
    store_vault_credential,
)
from parrot.tools.config_schema import build_schema_envelope, secret_paths
from parrot.tools.resolver import get_toolkit_resolver
from parrot.tools.tooling_policy import ToolingSubject, enforce_tenant_tooling
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
from .storage.models import StudioStorageUnavailable, StudioWriteGuard

logger = logging.getLogger(__name__)


@dataclass
class ToolingState:
    """Loaded editable tooling state and its persistence source."""

    tooling: NormalizedTooling
    editable: bool
    reason: str | None
    owner: str | None
    source: Literal["database", "registry", "studio"]
    tooling_ref: str = ""   # tooling identity (spec §2.5c): == name for database/registry; studio-agent:<id> for studio


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


@dataclass(frozen=True)
class VaultWrite:
    """A pending owner-scoped vault merge: ``values`` are merged into the entry ``vault_name``."""

    owner: str
    vault_name: str
    values: dict[str, Any]


async def flush_vault_writes(writes: list[VaultWrite]) -> None:
    """Merge every pending write into its vault entry (read-merge-store, as FEAT-593 always did)."""
    for write in writes:
        try:
            current = await retrieve_vault_credential(write.owner, write.vault_name)
        except KeyError:
            current = {}
        current.update(write.values)
        await store_vault_credential(write.owner, write.vault_name, current)


def toolkit_schema_for(slug: str) -> tuple[type, dict[str, Any]]:
    """Return the class and JSON schema for ``slug`` (``LookupError`` when the toolkit is unknown)."""
    cls = get_toolkit_resolver().resolve(slug)
    if cls is None:
        raise LookupError(slug)
    envelope = build_schema_envelope(slug, cls)
    return cls, envelope.schema_


def validate_toolkit_params(cls: type, schema: dict[str, Any], params: dict[str, Any]) -> None:
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


class ServerManagedParamsRejected(ValueError):
    """A client supplied constructor parameters the server fills (HTTP 422 ``server_managed``)."""

    def __init__(self, params: list[str]) -> None:
        self.params = params
        super().__init__(f"Server-managed parameters cannot be set: {', '.join(params)}")


def reject_server_managed(schema: dict[str, Any], params: dict[str, Any]) -> None:
    """Reject top-level fields reserved for server construction (``ServerManagedParamsRejected``)."""
    forbidden = [
        key for key, value in params.items() if schema.get("properties", {}).get(key, {}).get("x-server-managed") is True
    ]
    if forbidden:
        raise ServerManagedParamsRejected(sorted(forbidden))


def split_toolkit_secrets(
    *,
    owner: str | None,
    ref: str,
    slug: str,
    schema: dict[str, Any],
    params: dict[str, Any],
    user_overridable: list[str],
    previous: ToolkitSpec | None,
) -> tuple[ToolkitSpec, list[VaultWrite]]:
    """Pure split of x-secret values out of ``params``: the spec to persist and the vault writes to perform."""
    if owner is None:
        raise PermissionError("agent has no owner; cannot store secrets")
    vault_name = toolkit_vault_name(slug, ref)
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
    spec = ToolkitSpec(
        slug=slug, params=clean, user_overridable=user_overridable, secret_refs=refs, vault_owner=owner
    )
    return spec, [VaultWrite(owner, vault_name, merged)] if merged else []


def _split_one_mcp(
    raw: dict[str, Any], owner: str, ref: str, previous: dict[str, AgentMCPServerSpec]
) -> tuple[AgentMCPServerSpec, list[VaultWrite]]:
    payload = copy.deepcopy(raw)
    params = dict(payload.pop("params", {}))
    for field in MCP_SECRET_FIELDS:
        if field in payload:
            params[field] = payload.pop(field)
    try:
        candidate = AgentMCPServerSpec.model_validate({**payload, "params": params})
    except ValidationError as exc:
        raise ValueError(f"Invalid MCP server parameters: {exc}") from exc
    vault_name = mcp_vault_name(candidate.name, ref)
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
    spec = candidate.model_copy(update={"params": clean, "secret_refs": refs, "vault_owner": owner})
    return spec, [VaultWrite(owner, vault_name, merged)] if merged else []


def split_mcp_secrets(
    *, owner: str | None, ref: str, servers: list[dict[str, Any]], previous: list[AgentMCPServerSpec]
) -> tuple[list[AgentMCPServerSpec], list[VaultWrite]]:
    """Pure split of MCP secret fields: the complete server list to persist and the vault writes to perform."""
    if owner is None:
        raise PermissionError("agent has no owner; cannot store secrets")
    by_name = {item.name: item for item in previous}
    specs: list[AgentMCPServerSpec] = []
    writes: list[VaultWrite] = []
    for raw in servers:
        spec, pending = _split_one_mcp(raw, owner, ref, by_name)
        specs.append(spec)
        writes.extend(pending)
    return specs, writes


class AgentToolingStore:
    """Load and persist agent-level toolkit / MCP configuration (DB row or agent YAML)."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler

    async def load(self, name: str) -> ToolingState:
        """Load agent tooling, raising ``LookupError`` when the agent is unknown."""
        studio = await self._load_studio(name)
        if studio is not None:
            return studio
        row = await self.handler._get_db_agent(name)
        if row is not None:
            owner = str(row.created_by) if row.created_by is not None else None
            state = ToolingState(
                tooling=normalize_tooling([], mcp_servers=row.mcp_servers, toolkit_config=row.toolkit_config),
                editable=owner is not None,
                reason=None if owner is not None else "agent has no owner; cannot store secrets",
                owner=owner,
                source="database",
                tooling_ref=name,
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
            tooling_ref=name,
        )
        state._registry = registry
        return state

    async def _load_studio(self, name: str) -> ToolingState | None:
        """A Studio agent of this request's partition, when the database backend serves it (spec §2.5)."""
        locate = getattr(self.handler, "_studio_storage", None)
        if locate is None:
            return None
        try:
            storage = locate()
        except StudioStorageUnavailable:
            return None
        if getattr(storage, "backend", None) != "database":
            return None
        part = await self.handler._studio_partition()
        service = storage.services.tooling
        view = await service.load(part, name)
        if view is None:
            return None
        record = view.record
        has_owner = record.owner is not None
        state = ToolingState(
            tooling=view.tooling, editable=has_owner,
            reason=None if has_owner else "agent has no owner; cannot store secrets",
            owner=record.owner, source="studio", tooling_ref=record.tooling_ref,
        )
        state._studio = (part, record, service)
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
        return toolkit_schema_for(slug)

    @staticmethod
    def _validate(cls: type, schema: dict[str, Any], params: dict[str, Any]) -> None:
        """Validate client params after masked secret values have been removed."""
        validate_toolkit_params(cls, schema, params)

    @staticmethod
    def _reject_server_managed(schema: dict[str, Any], params: dict[str, Any]) -> None:
        """Reject top-level fields reserved for server construction."""
        reject_server_managed(schema, params)

    async def put_toolkit(
        self,
        name: str,
        slug: str,
        params: dict[str, Any],
        user_overridable: list[str],
        *,
        guard: StudioWriteGuard | None = None,
        actor: str | None = None,
    ) -> ToolkitSpec:
        """Validate, vault secrets under the owner, and persist a toolkit specification.

        ``guard``/``actor`` apply to Studio rows only; legacy sources ignore them.
        """
        state = await self.load(name)
        if not state.editable:
            raise PermissionError(state.reason or "agent tooling is read-only")
        cls, schema = self.schema_for(slug)
        self._reject_server_managed(schema, params)
        self._validate(cls, schema, params)
        if state.source == "studio":
            return await self._studio_put_toolkit(state, name, slug, params, user_overridable, guard, actor)
        spec, writes = self._toolkit_candidate(state, slug, schema, params, user_overridable)
        toolkits = [item for item in state.tooling.toolkits if item.slug.lower() != slug.lower()] + [spec]
        await self._enforce(state, state.tooling.model_copy(update={"toolkits": toolkits}), actor=actor)
        await flush_vault_writes(writes)
        state.tooling.toolkits = toolkits
        await self._persist(name, state)
        return spec

    async def delete_toolkit(
        self, name: str, slug: str, *, guard: StudioWriteGuard | None = None, actor: str | None = None
    ) -> None:
        """Remove one toolkit specification and its owner-scoped vault entry (``guard``/``actor``: Studio rows)."""
        state = await self.load(name)
        if not state.editable:
            raise PermissionError(state.reason or "agent tooling is read-only")
        if state.source == "studio":
            part, record, service = state._studio
            await service.delete_toolkit(
                part, name, slug, actor=actor if actor is not None else record.owner, guard=guard or self._guard(record)
            )
            return
        remaining = [item for item in state.tooling.toolkits if item.slug.lower() != slug.lower()]
        await self._enforce(state, state.tooling.model_copy(update={"toolkits": remaining}), actor=actor)
        state.tooling.toolkits = remaining
        if state.owner is None:
            raise PermissionError("agent has no owner; cannot store secrets")
        await delete_vault_credential(state.owner, toolkit_vault_name(slug, state.tooling_ref))
        await self._persist(name, state)

    async def put_mcp_servers(
        self,
        name: str,
        servers: list[dict[str, Any]],
        *,
        guard: StudioWriteGuard | None = None,
        actor: str | None = None,
    ) -> list[AgentMCPServerSpec]:
        """Vault MCP secret fields and replace the complete server list (``guard``/``actor``: Studio rows)."""
        state = await self.load(name)
        if not state.editable or state.owner is None:
            raise PermissionError(state.reason or "agent has no owner; cannot store secrets")
        if state.source == "studio":
            part, record, service = state._studio
            await service.put_mcp_servers(
                part, name, servers, actor=actor if actor is not None else record.owner,
                guard=guard or self._guard(record),
            )
            return (await service.load(part, name)).tooling.mcp_servers
        specs, writes = split_mcp_secrets(
            owner=state.owner, ref=state.tooling_ref, servers=servers, previous=state.tooling.mcp_servers
        )
        await self._enforce(state, state.tooling.model_copy(update={"mcp_servers": specs}), actor=actor)
        await flush_vault_writes(writes)
        state.tooling.mcp_servers = specs
        await self._persist(name, state)
        return specs

    @staticmethod
    def _guard(record: Any) -> StudioWriteGuard:
        return StudioWriteGuard.for_record(record)

    async def _studio_put_toolkit(
        self,
        state: ToolingState,
        name: str,
        slug: str,
        params: dict[str, Any],
        user_overridable: list[str],
        guard: StudioWriteGuard | None = None,
        actor: str | None = None,
    ) -> ToolkitSpec:
        """Studio rows: the service gates the FINAL tooling BEFORE any vault write (spec §2.5b), then commits."""
        part, record, service = state._studio
        await service.put_toolkit(
            part, name, slug, params, user_overridable,
            actor=actor if actor is not None else record.owner, guard=guard or self._guard(record),
        )
        view = await service.load(part, name)
        return next(item for item in view.tooling.toolkits if item.slug.lower() == slug.lower())

    def _toolkit_candidate(
        self,
        state: ToolingState,
        slug: str,
        schema: dict[str, Any],
        params: dict[str, Any],
        user_overridable: list[str],
    ) -> tuple[ToolkitSpec, list[VaultWrite]]:
        """Pure split of x-secret values: the spec to persist and the owner-scoped vault writes (no I/O)."""
        previous = next((item for item in state.tooling.toolkits if item.slug.lower() == slug.lower()), None)
        return split_toolkit_secrets(
            owner=state.owner,
            ref=state.tooling_ref,
            slug=slug,
            schema=schema,
            params=params,
            user_overridable=user_overridable,
            previous=previous,
        )

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
        spec, writes = self._toolkit_candidate(state, slug, schema, params, user_overridable)
        await flush_vault_writes(writes)
        return spec

    async def _enforce(self, state: ToolingState, tooling: NormalizedTooling, *, actor: str | None = None) -> None:
        """Tenant tooling policy (phase ``write``) on the COMPLETE resulting tooling, before any vault write (M7)."""
        from .storage.services.tooling import _owner_only_with_refs  # lazy: that module imports this one

        locate = getattr(self.handler, "_studio_partition", None)
        part = await locate() if locate is not None else None
        subject = ToolingSubject(
            tenant=getattr(part, "tenant", None), agent_id=None, actor=actor or state.owner, phase="write"
        )
        resulting = NormalizedTooling(
            tools=list(tooling.tools),
            toolkits=[_owner_only_with_refs(item) for item in tooling.toolkits],
            mcp_servers=[_owner_only_with_refs(item) for item in tooling.mcp_servers],
        )
        enforce_tenant_tooling(self.handler.request.app, resulting, subject=subject)

    async def _persist(self, name: str, state: ToolingState) -> None:
        """Persist normalized specs to the Studio rows, the DB row or agent-owned YAML."""
        if state.source == "studio":
            part, record, service = state._studio
            await service.replace_from_state(
                part, name, state.tooling, actor=record.owner, guard=StudioWriteGuard.for_record(record)
            )
        elif state.source == "database":
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
