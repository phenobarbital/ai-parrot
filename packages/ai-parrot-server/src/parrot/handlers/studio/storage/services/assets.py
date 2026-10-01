"""StudioAssetService (spec §2.5): text assets in Postgres with per-file caps and a per-agent quota."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from ..models import StudioAssetInput, StudioAssetRecord, StudioPartition, StudioWriteGuard
from ..repositories import StudioRepositories, studio_transaction
from ._common import (
    StudioAgentAssetsQuota,
    StudioLimits,
    StudioToolingGate,
    normalized_tooling_for,
    validate_asset_input,
)

logger = logging.getLogger("Parrot.AgentStudio.Storage")
_NO_GUARD = StudioWriteGuard()


class StudioAssetService:
    """Asset files of a Studio agent. Every write: lock → gate(current tooling) → quota under the lock → write."""

    def __init__(self, repos: StudioRepositories, *, limits: StudioLimits, tooling_gate: StudioToolingGate) -> None:
        self._repos, self._limits, self._gate = repos, limits, tooling_gate

    async def _locked_agent(
        self, conn: Any, part: StudioPartition, agent_name: str, guard: StudioWriteGuard, actor: str | None
    ):
        """Lock the agent (guard checked) and re-check the policy on its CURRENT tooling; returns its head."""
        head = await self._repos.agents.lock(conn, part, agent_name, guard)
        record = await self._repos.agents.get(part, agent_name)
        rows = await self._repos.tooling.list_locked(conn, head.agent_id)
        self._gate.enforce(
            part, normalized_tooling_for(record.definition, rows), agent_id=head.agent_id,
            actor=actor or record.owner, phase="write",
        )
        return head

    async def put(
        self,
        part: StudioPartition,
        agent_name: str,
        asset: StudioAssetInput,
        *,
        actor: str | None,
        guard: StudioWriteGuard,
    ) -> tuple[StudioAssetRecord, int]:
        """Validate, then write one asset; returns the stored record and the agent's post-write version."""
        size = validate_asset_input(self._limits, asset)   # cheap checks first; the quota needs the lock
        digest = hashlib.sha256(asset.content.encode("utf-8")).hexdigest()
        async with studio_transaction(self._repos.pool) as conn:
            head = await self._locked_agent(conn, part, agent_name, guard, actor)
            old = await self._repos.assets.get(part, agent_name, asset.kind, asset.name)
            total = await self._repos.assets.total_size(conn, head.agent_id) + size - (old.size if old else 0)
            if total > self._limits.agent_total_max:
                raise StudioAgentAssetsQuota(f"agent assets would total {total} > {self._limits.agent_total_max} bytes")
            record = await self._repos.assets.put(conn, head.agent_id, asset, sha256=digest)
            version = (await self._repos.agents.lock(conn, part, agent_name, _NO_GUARD)).version
        return record, version

    async def delete(
        self,
        part: StudioPartition,
        agent_name: str,
        kind: str,
        name: str,
        *,
        actor: str | None,
        guard: StudioWriteGuard,
    ) -> tuple[bool, int]:
        """Delete one asset; returns (existed, post-write version)."""
        async with studio_transaction(self._repos.pool) as conn:
            head = await self._locked_agent(conn, part, agent_name, guard, actor)
            existed = await self._repos.assets.delete(conn, head.agent_id, kind, name)
            version = (await self._repos.agents.lock(conn, part, agent_name, _NO_GUARD)).version
        return existed, version

    async def get(self, part: StudioPartition, agent_name: str, kind: str, name: str) -> StudioAssetRecord | None:
        """One asset including its content, or None."""
        return await self._repos.assets.get(part, agent_name, kind, name)

    async def list(self, part: StudioPartition, agent_name: str, kind: str | None = None) -> list[StudioAssetRecord]:
        """Assets of the agent (content omitted), ordered by (kind, name)."""
        return await self._repos.assets.list(part, agent_name, kind)
