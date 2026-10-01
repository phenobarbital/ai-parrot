"""StudioToolingService (spec §2.5): FEAT-593 validation + secret split, persisted to ai_agent_tooling."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from parrot.handlers.studio.tooling_store import (
    flush_vault_writes,
    reject_server_managed,
    split_mcp_secrets,
    split_toolkit_secrets,
    toolkit_schema_for,
    validate_toolkit_params,
)
from parrot.security.vault_utils import delete_vault_credential
from parrot.tools.spec import AgentMCPServerSpec, NormalizedTooling, ToolkitSpec, toolkit_vault_name

from ..models import StudioAgentRecord, StudioPartition, StudioToolingRecord, StudioWriteGuard
from ..repositories import StudioRepositories, studio_transaction
from ._common import StudioToolingGate, normalized_tooling_for

logger = logging.getLogger("Parrot.AgentStudio.Storage")
_NO_GUARD = StudioWriteGuard()


@dataclass(frozen=True)
class StudioToolingView:
    """A Studio agent record and the tooling the builder would see for it."""

    record: StudioAgentRecord
    tooling: NormalizedTooling


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owner_only_with_refs(spec: Any) -> Any:
    """``vault_owner`` is stored only when the spec carries secret references (policy: none ⇒ no vault trace)."""
    if spec.secret_refs or spec.vault_owner is None:
        return spec
    return spec.model_copy(update={"vault_owner": None})


def toolkit_row(spec: ToolkitSpec) -> StudioToolingRecord:
    """Persisted shape of a toolkit: secret-free ``config``; refs and owner live in their own columns."""
    config = spec.model_dump(exclude={"slug", "secret_refs", "vault_owner"})
    return StudioToolingRecord(None, "toolkit", spec.slug, -1, config, dict(spec.secret_refs), spec.vault_owner, _now())  # type: ignore[arg-type]


def mcp_row(spec: AgentMCPServerSpec) -> StudioToolingRecord:
    """Persisted shape of an MCP server."""
    config = spec.model_dump(exclude={"name", "secret_refs", "vault_owner"})
    return StudioToolingRecord(None, "mcp", spec.name, -1, config, dict(spec.secret_refs), spec.vault_owner, _now())  # type: ignore[arg-type]


class StudioToolingService:
    """Tooling of a Studio agent. Every write: lock → final tooling → gate → vault → replace → commit."""

    def __init__(self, repos: StudioRepositories, *, gate: StudioToolingGate) -> None:
        self._repos = repos
        self._gate = gate

    async def load(self, part: StudioPartition, name: str) -> StudioToolingView | None:
        """The agent and its normalised tooling in the partition, or None."""
        snap = await self._repos.agents.load_snapshot(part, name)
        if snap is None:
            return None
        return StudioToolingView(snap.record, normalized_tooling_for(snap.record.definition, snap.tooling))

    async def _open(self, conn: Any, part: StudioPartition, name: str, guard: StudioWriteGuard):
        """Lock the agent, then return (agent_id, record, current tooling) read under the lock."""
        head = await self._repos.agents.lock(conn, part, name, guard)
        record = await self._repos.agents.get(part, name)
        rows = await self._repos.tooling.list_locked(conn, head.agent_id)
        return head.agent_id, record, normalized_tooling_for(record.definition, rows)

    async def _commit_rows(
        self, conn: Any, part: StudioPartition, name: str, agent_id: UUID, tooling: NormalizedTooling
    ) -> int:
        """Replace the stored rows with ``tooling`` and return the post-write version (still in the transaction)."""
        await self._repos.tooling.replace(
            conn,
            agent_id,
            toolkits=[toolkit_row(s) for s in tooling.toolkits],
            mcp_servers=[mcp_row(s) for s in tooling.mcp_servers],
        )
        return (await self._repos.agents.lock(conn, part, name, _NO_GUARD)).version

    async def put_toolkit(
        self,
        part: StudioPartition,
        name: str,
        slug: str,
        params: dict[str, Any],
        user_overridable: list[str],
        *,
        actor: str | None,
        guard: StudioWriteGuard,
    ) -> int:
        """Lock → final tooling → gate(write) → vault (ref-derived names) → replace → commit. Returns version."""
        async with studio_transaction(self._repos.pool) as conn:
            agent_id, record, current = await self._open(conn, part, name, guard)
            cls, schema = toolkit_schema_for(slug)
            reject_server_managed(schema, params)
            validate_toolkit_params(cls, schema, params)
            previous = next((t for t in current.toolkits if t.slug.lower() == slug.lower()), None)
            spec, writes = split_toolkit_secrets(
                owner=record.owner, ref=record.tooling_ref, slug=slug, schema=schema, params=params,
                user_overridable=user_overridable, previous=previous,
            )
            spec = _owner_only_with_refs(spec)
            current.toolkits = [t for t in current.toolkits if t.slug.lower() != slug.lower()] + [spec]
            self._gate.enforce(part, current, agent_id=agent_id, actor=actor, phase="write")
            await flush_vault_writes(writes)
            return await self._commit_rows(conn, part, name, agent_id, current)

    async def delete_toolkit(
        self, part: StudioPartition, name: str, slug: str, *, actor: str | None, guard: StudioWriteGuard
    ) -> int:
        """Remove one toolkit and its owner-scoped vault entry. Returns the new version."""
        async with studio_transaction(self._repos.pool) as conn:
            agent_id, record, current = await self._open(conn, part, name, guard)
            current.toolkits = [t for t in current.toolkits if t.slug.lower() != slug.lower()]
            self._gate.enforce(part, current, agent_id=agent_id, actor=actor, phase="write")
            await delete_vault_credential(record.owner, toolkit_vault_name(slug, record.tooling_ref))
            return await self._commit_rows(conn, part, name, agent_id, current)

    async def put_mcp_servers(
        self,
        part: StudioPartition,
        name: str,
        servers: Sequence[dict[str, Any]],
        *,
        actor: str | None,
        guard: StudioWriteGuard,
    ) -> int:
        """Replace the complete MCP server list (secret fields vaulted under the tooling ref). Returns the version."""
        async with studio_transaction(self._repos.pool) as conn:
            agent_id, record, current = await self._open(conn, part, name, guard)
            specs, writes = split_mcp_secrets(
                owner=record.owner, ref=record.tooling_ref, servers=list(servers), previous=current.mcp_servers
            )
            current.mcp_servers = [_owner_only_with_refs(spec) for spec in specs]
            self._gate.enforce(part, current, agent_id=agent_id, actor=actor, phase="write")
            await flush_vault_writes(writes)
            return await self._commit_rows(conn, part, name, agent_id, current)

    async def replace_from_state(
        self, part: StudioPartition, name: str, tooling: NormalizedTooling, *, actor: str | None,
        guard: StudioWriteGuard,
    ) -> int:
        """Persist an already-split tooling state (used by ``AgentToolingStore._persist``). Returns the version."""
        async with studio_transaction(self._repos.pool) as conn:
            head = await self._repos.agents.lock(conn, part, name, guard)
            self._gate.enforce(part, tooling, agent_id=head.agent_id, actor=actor, phase="write")
            return await self._commit_rows(conn, part, name, head.agent_id, tooling)
