"""StudioDraftService (spec §2.5, §2.5a): declarative drafts and atomic activation."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Sequence

from navconfig import config

from ..models import (
    StudioAgentBundle,
    StudioAgentRecord,
    StudioDraftRecord,
    StudioNotFound,
    StudioPartition,
    StudioToolingRecord,
    StudioVersionConflict,
    StudioWriteGuard,
)
from ..repositories import StudioRepositories, studio_transaction
from ._common import StudioToolingGate, validate_visibility
from .agents import StudioAgentService

logger = logging.getLogger("Parrot.AgentStudio.Storage")
_NO_GUARD = StudioWriteGuard()
_ACTIVATABLE = ("draft", "validated")


class StudioDraftService:
    """Declarative drafts of a partition. Validates data; never decides access."""

    def __init__(
        self, repos: StudioRepositories, *, agents: StudioAgentService, tooling_gate: StudioToolingGate
    ) -> None:
        self._repos, self._agents, self._gate = repos, agents, tooling_gate

    def python_drafts_allowed(self, part: StudioPartition) -> bool:
        """``part.tenant is None`` and ``STUDIO_PYTHON_DRAFTS`` is true. The single decision point."""
        return part.tenant is None and bool(config.getboolean("STUDIO_PYTHON_DRAFTS", fallback=True))

    # ---- writes -----------------------------------------------------------------------------------------------
    async def save_bundle(
        self,
        part: StudioPartition,
        *,
        owner: str,
        bundle: StudioAgentBundle,
        visibility: str = "private",
        allowed_groups: Sequence[str] = (),
        guard: StudioWriteGuard = _NO_GUARD,
    ) -> StudioDraftRecord:
        """Create the draft ``bundle.name`` or replace its bundle (guarded). Validated and gated (``write``) first."""
        self._agents.validate_new(
            part, name=bundle.name, owner=owner, definition=bundle.definition, visibility=visibility,
            allowed_groups=allowed_groups, toolkits=bundle.toolkits, mcp_servers=bundle.mcp_servers,
            assets=bundle.assets, phase="write",
        )
        async with studio_transaction(self._repos.pool) as conn:
            if await self._repos.drafts.get(part, bundle.name) is None:
                return await self._repos.drafts.insert(
                    conn, part, name=bundle.name, owner=owner, bundle=bundle, visibility=visibility,
                    allowed_groups=allowed_groups,
                )
            await self._repos.drafts.lock(conn, part, bundle.name, guard)
            return await self._repos.drafts.update_bundle(conn, part, bundle.name, bundle)

    async def update_visibility(
        self, part: StudioPartition, name: str, *, visibility: str, allowed_groups: Sequence[str],
        guard: StudioWriteGuard = _NO_GUARD,
    ) -> StudioDraftRecord:
        """Lock under the guard, then store the visibility the caller decided."""
        validate_visibility(part, visibility, allowed_groups)
        async with studio_transaction(self._repos.pool) as conn:
            await self._repos.drafts.lock(conn, part, name, guard)
            return await self._repos.drafts.update_visibility(
                conn, part, name, visibility=visibility, allowed_groups=allowed_groups
            )

    async def delete(self, part: StudioPartition, name: str, *, guard: StudioWriteGuard = _NO_GUARD) -> bool:
        """Delete the draft under the guard; False when it does not exist."""
        async with studio_transaction(self._repos.pool) as conn:
            try:
                await self._repos.drafts.lock(conn, part, name, guard)
            except StudioNotFound:
                return False
            return await self._repos.drafts.delete(conn, part, name)

    # ---- activation (spec §2.5a) ------------------------------------------------------------------------------
    async def activate(
        self,
        part: StudioPartition,
        name: str,
        *,
        owner: str,
        replace: bool = False,
        guard: StudioWriteGuard = _NO_GUARD,
        target_guard: StudioWriteGuard | None = None,
    ) -> StudioAgentRecord:
        """One transaction over draft + agent: lock draft → validate/gate → insert or replace → mark activated."""
        removed: list[StudioToolingRecord] = []
        async with studio_transaction(self._repos.pool) as conn:
            head = await self._repos.drafts.lock(conn, part, name, guard)
            if head.status not in _ACTIVATABLE:
                raise StudioVersionConflict(f"draft {name!r} is {head.status}, not activatable")
            draft = await self._repos.drafts.get(part, name)
            if draft is None:
                raise StudioNotFound(name)
            bundle = draft.bundle
            self._agents.validate_new(
                part, name=bundle.name, owner=owner, definition=bundle.definition, visibility=draft.visibility,
                allowed_groups=draft.allowed_groups, toolkits=bundle.toolkits, mcp_servers=bundle.mcp_servers,
                assets=bundle.assets, phase="activate",
            )
            if replace:
                record, removed = await self._replace_target(conn, part, draft, target_guard or _NO_GUARD)
            else:
                record = await self._insert_target(conn, part, draft, owner)
            await self._repos.drafts.set_status(conn, part, name, "activated", activated_agent_id=record.agent_id)
        await self._cleanup_removed(record, removed)
        return record

    async def _insert_target(
        self, conn: Any, part: StudioPartition, draft: StudioDraftRecord, owner: str
    ) -> StudioAgentRecord:
        bundle = draft.bundle
        record = await self._agents._insert_with_children(
            conn, part, name=bundle.name, owner=owner, definition=bundle.definition, visibility=draft.visibility,
            allowed_groups=draft.allowed_groups, toolkits=bundle.toolkits, mcp_servers=bundle.mcp_servers,
            assets=bundle.assets,
        )
        return await self._with_current_version(conn, part, record)

    async def _replace_target(
        self, conn: Any, part: StudioPartition, draft: StudioDraftRecord, target_guard: StudioWriteGuard
    ) -> tuple[StudioAgentRecord, list[StudioToolingRecord]]:
        """Lock the target agent (after the draft: §2.5a lock order) and swap definition + ALL children atomically."""
        bundle = draft.bundle
        head = await self._repos.agents.lock(conn, part, bundle.name, target_guard)
        before = await self._repos.tooling.list_locked(conn, head.agent_id)
        await self._repos.agents.update_definition(conn, part, bundle.name, bundle.definition)
        await self._agents._replace_children(
            conn, head.agent_id, toolkits=bundle.toolkits, mcp_servers=bundle.mcp_servers, assets=bundle.assets
        )
        current = await self._repos.agents.get(part, bundle.name)   # committed pre-state: the lock above proved it exists
        if current is None:
            raise StudioNotFound(bundle.name)
        record = dataclasses.replace(current, definition=bundle.definition)
        kept = {("toolkit", s.slug) for s in bundle.toolkits} | {("mcp", s.name) for s in bundle.mcp_servers}
        removed = [row for row in before if (row.kind, row.slug) not in kept]
        return await self._with_current_version(conn, part, record), removed

    async def _with_current_version(
        self, conn: Any, part: StudioPartition, record: StudioAgentRecord
    ) -> StudioAgentRecord:
        """The record carries the post-children version (child writes bump it inside the transaction)."""
        head = await self._repos.agents.lock(conn, part, record.name, _NO_GUARD)
        return dataclasses.replace(record, version=head.version)

    async def _cleanup_removed(self, record: StudioAgentRecord, removed: Sequence[StudioToolingRecord]) -> None:
        """§2.5c: vault entries of the tooling slugs the replacement removed — best effort, after commit."""
        if not removed:
            return
        from parrot.security.vault_utils import delete_vault_credential

        try:
            for row in removed:
                for vault_name in sorted(set(row.secret_refs.values())):
                    await delete_vault_credential(row.vault_owner or record.owner, vault_name)
        except Exception as exc:  # noqa: BLE001 — the replacement is committed; leftovers are logged
            logger.warning("studio activation clean-up for %s failed: %r", record.tooling_ref, exc)

    # ---- reads ------------------------------------------------------------------------------------------------
    async def get(self, part: StudioPartition, name: str) -> StudioDraftRecord | None:
        """The draft, or None."""
        return await self._repos.drafts.get(part, name)

    async def list(self, part: StudioPartition, *, owner: str | None = None) -> list[StudioDraftRecord]:
        """Drafts of the partition (optionally one owner's)."""
        return await self._repos.drafts.list(part, owner=owner)
