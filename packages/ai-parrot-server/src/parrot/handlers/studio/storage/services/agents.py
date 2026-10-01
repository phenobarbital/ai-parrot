"""StudioAgentService (spec §2.5). Validates data; never decides access."""

from __future__ import annotations

import logging
from typing import Any, Sequence
from uuid import UUID

from pydantic import ValidationError

from parrot.tools.spec import (
    AgentMCPServerSpec,
    NormalizedTooling,
    ToolkitSpec,
    normalize_tooling,
    toolkit_override_vault_name,
)

from ..models import (
    StudioAgentBundle,
    StudioAgentDefinition,
    StudioAgentHead,
    StudioAgentPatch,
    StudioAgentRecord,
    StudioAgentSnapshot,
    StudioAssetInput,
    StudioNotFound,
    StudioPartition,
    StudioWriteGuard,
)
from ..repositories import StudioRepositories, studio_transaction
from ._common import (
    StudioAgentAssetsQuota,
    StudioClassAllowlist,
    StudioLimits,
    StudioToolingGate,
    StudioValidationError,
    normalized_tooling_for,
    validate_asset_input,
    validate_definition_for,
    validate_visibility,
)
from .tooling import StudioToolingService, mcp_row, toolkit_row

logger = logging.getLogger("Parrot.AgentStudio.Storage")
MAX_NAME_LENGTH = 64


def validate_agent_name(name: str) -> None:
    """The name is a slug (``^[a-z0-9_-]+$``, at most 64 characters); ``':'`` can never appear in it."""
    from parrot.handlers.studio._base import STUDIO_SLUG_RE

    if not name or len(name) > MAX_NAME_LENGTH or not STUDIO_SLUG_RE.match(name):
        raise StudioValidationError(f"invalid agent name {name!r}", code="invalid_name", status=400)


def merge_general_fields(base: StudioAgentDefinition, patch: StudioAgentPatch) -> StudioAgentDefinition:
    """Merge-patch of the General fields: ``None`` leaves a field unchanged; ``model_params`` merges field-wise."""
    changes: dict[str, Any] = {
        key: value
        for key in ("description", "llm", "system_prompt", "category")
        if (value := getattr(patch, key)) is not None
    }
    if patch.model_params is not None:
        given = patch.model_params.model_dump(exclude_unset=True, exclude_none=True)
        changes["model_params"] = base.model_params.model_copy(update=given)
    return base.model_copy(update=changes)


def _combined_guard(patch: StudioAgentPatch, guard: StudioWriteGuard) -> StudioWriteGuard:
    """A body ``expected_version`` applies when the caller's guard carries none."""
    if guard.expected_version is not None or patch.expected_version is None:
        return guard
    return StudioWriteGuard(authorized_version=guard.authorized_version, expected_version=patch.expected_version)


class StudioAgentService:
    """Agents of a partition. Create and activation share ``_insert_with_children``/``_replace_children``."""

    def __init__(
        self,
        repos: StudioRepositories,
        *,
        limits: StudioLimits,
        class_allowlist: StudioClassAllowlist,
        tooling: StudioToolingService,
        tooling_gate: StudioToolingGate,
    ) -> None:
        self._repos, self._limits, self._allow = repos, limits, class_allowlist
        self._tooling, self._gate = tooling, tooling_gate

    # ---- validation -------------------------------------------------------------------------------------------
    def validate_new(
        self,
        part: StudioPartition,
        *,
        name: str,
        owner: str,
        definition: StudioAgentDefinition,
        visibility: str,
        allowed_groups: Sequence[str],
        toolkits: Sequence[ToolkitSpec],
        mcp_servers: Sequence[AgentMCPServerSpec],
        assets: Sequence[StudioAssetInput],
        phase: str = "write",
    ) -> NormalizedTooling:
        """Everything ``create`` checks before the first write; returns the FINAL normalised tooling (gated)."""
        validate_agent_name(name)
        validate_definition_for(
            part, definition, allowlist=self._allow, visibility=visibility, allowed_groups=allowed_groups
        )
        try:
            StudioAgentBundle(
                name=name, definition=definition, toolkits=list(toolkits), mcp_servers=list(mcp_servers)
            )
        except ValidationError as exc:
            raise StudioValidationError(str(exc), code="secrets_not_allowed") from exc
        self.validate_assets(assets)
        tooling = normalize_tooling(definition.tools, list(toolkits), list(mcp_servers))
        self._gate.enforce(part, tooling, agent_id=None, actor=owner, phase=phase)  # type: ignore[arg-type]
        return tooling

    def validate_assets(self, assets: Sequence[StudioAssetInput]) -> None:
        """Per-asset rules, no duplicates, and the per-agent quota over the whole set."""
        seen: set[tuple[str, str]] = set()
        total = 0
        for asset in assets:
            if (asset.kind, asset.name) in seen:
                raise StudioValidationError(f"duplicate asset {asset.kind}/{asset.name}", code="duplicate_asset")
            seen.add((asset.kind, asset.name))
            total += validate_asset_input(self._limits, asset)
        if total > self._limits.agent_total_max:
            raise StudioAgentAssetsQuota(f"assets total {total} > {self._limits.agent_total_max} bytes")

    # ---- in-transaction steps (also used by draft activation) ------------------------------------------------
    async def _replace_children(
        self,
        conn: Any,
        agent_id: UUID,
        *,
        toolkits: Sequence[ToolkitSpec],
        mcp_servers: Sequence[AgentMCPServerSpec],
        assets: Sequence[StudioAssetInput],
    ) -> None:
        """Replace tooling rows and assets of ``agent_id`` with exactly the given ones (caller holds the lock)."""
        await self._repos.tooling.replace(
            conn,
            agent_id,
            toolkits=[toolkit_row(s) for s in toolkits],
            mcp_servers=[mcp_row(s) for s in mcp_servers],
        )
        await self._repos.assets.replace_all(conn, agent_id, list(assets))

    async def _insert_with_children(
        self,
        conn: Any,
        part: StudioPartition,
        *,
        name: str,
        owner: str,
        definition: StudioAgentDefinition,
        visibility: str,
        allowed_groups: Sequence[str],
        toolkits: Sequence[ToolkitSpec],
        mcp_servers: Sequence[AgentMCPServerSpec],
        assets: Sequence[StudioAssetInput],
    ) -> StudioAgentRecord:
        """Insert the agent, then its tooling and assets, inside the caller's transaction."""
        record = await self._repos.agents.insert(
            conn, part, name=name, owner=owner, definition=definition, visibility=visibility,
            allowed_groups=allowed_groups,
        )
        if toolkits or mcp_servers or assets:
            await self._replace_children(
                conn, record.agent_id, toolkits=toolkits, mcp_servers=mcp_servers, assets=assets
            )
        return record

    # ---- writes -----------------------------------------------------------------------------------------------
    async def create(
        self,
        part: StudioPartition,
        *,
        name: str,
        owner: str,
        definition: StudioAgentDefinition,
        visibility: str = "private",
        allowed_groups: Sequence[str] = (),
        toolkits: Sequence[ToolkitSpec] = (),
        mcp_servers: Sequence[AgentMCPServerSpec] = (),
        assets: Sequence[StudioAssetInput] = (),
    ) -> StudioAgentRecord:
        """Validate, gate, then insert agent + tooling + assets in ONE transaction (name conflicts raise)."""
        self.validate_new(
            part, name=name, owner=owner, definition=definition, visibility=visibility,
            allowed_groups=allowed_groups, toolkits=toolkits, mcp_servers=mcp_servers, assets=assets,
        )
        async with studio_transaction(self._repos.pool) as conn:
            return await self._insert_with_children(
                conn, part, name=name, owner=owner, definition=definition, visibility=visibility,
                allowed_groups=allowed_groups, toolkits=toolkits, mcp_servers=mcp_servers, assets=assets,
            )

    async def create_from_bundle(
        self,
        part: StudioPartition,
        *,
        owner: str,
        bundle: StudioAgentBundle,
        visibility: str = "private",
        allowed_groups: Sequence[str] = (),
    ) -> StudioAgentRecord:
        """``create`` with the bundle's name, definition, tooling and assets."""
        return await self.create(
            part, name=bundle.name, owner=owner, definition=bundle.definition, visibility=visibility,
            allowed_groups=allowed_groups, toolkits=bundle.toolkits, mcp_servers=bundle.mcp_servers,
            assets=bundle.assets,
        )

    async def patch(
        self, part: StudioPartition, name: str, patch: StudioAgentPatch, *, guard: StudioWriteGuard,
        actor: str | None = None,
    ) -> StudioAgentRecord:
        """Lock → merge General fields → validate as create → gate on the CURRENT tooling → update_definition."""
        async with studio_transaction(self._repos.pool) as conn:
            head = await self._repos.agents.lock(conn, part, name, _combined_guard(patch, guard))
            record = await self._repos.agents.get(part, name)
            definition = merge_general_fields(record.definition, patch)
            validate_definition_for(part, definition, allowlist=self._allow, visibility=record.visibility,
                                    allowed_groups=record.allowed_groups)
            rows = await self._repos.tooling.list_locked(conn, head.agent_id)
            self._gate.enforce(part, normalized_tooling_for(definition, rows), agent_id=head.agent_id,
                               actor=actor or record.owner, phase="write")
            return await self._repos.agents.update_definition(conn, part, name, definition)

    async def update_visibility(
        self, part: StudioPartition, name: str, *, visibility: str, allowed_groups: Sequence[str],
        guard: StudioWriteGuard,
    ) -> StudioAgentRecord:
        """Lock under the guard, then store the visibility the caller (FEAT-605) decided."""
        validate_visibility(part, visibility, allowed_groups)
        async with studio_transaction(self._repos.pool) as conn:
            await self._repos.agents.lock(conn, part, name, guard)
            return await self._repos.agents.update_visibility(
                conn, part, name, visibility=visibility, allowed_groups=allowed_groups
            )

    async def delete(self, part: StudioPartition, name: str, *, guard: StudioWriteGuard) -> bool:
        """Delete under the guard; clean vault entries and overrides after commit (best effort, logged)."""
        async with studio_transaction(self._repos.pool) as conn:
            try:
                await self._repos.agents.lock(conn, part, name, guard)
            except StudioNotFound:
                return False
            snapshot = await self._repos.agents.delete(conn, part, name)
        if snapshot is None:
            return False
        await self._cleanup_after_delete(snapshot)
        return True

    async def _cleanup_after_delete(self, snapshot: StudioAgentSnapshot) -> None:
        """§2.5c: stored vault names under their ``vault_owner``, then every user's override and its ``…_user`` entry."""
        from parrot.handlers.toolkit_persistence import ToolkitConfigService
        from parrot.security.vault_utils import delete_vault_credential

        ref = snapshot.record.tooling_ref
        try:
            for row in snapshot.tooling:
                for vault_name in sorted(set(row.secret_refs.values())):
                    await delete_vault_credential(row.vault_owner or snapshot.record.owner, vault_name)
            for override in await ToolkitConfigService().purge_agent(ref):
                await delete_vault_credential(override.user_id, toolkit_override_vault_name(override.slug, ref))
        except Exception as exc:  # noqa: BLE001 — best effort: the agent is already gone, ids are never reused
            logger.warning("studio delete clean-up for %s failed: %r", ref, exc)

    # ---- reads ------------------------------------------------------------------------------------------------
    async def get(self, part: StudioPartition, name: str) -> StudioAgentRecord | None:
        """The agent, or None."""
        return await self._repos.agents.get(part, name)

    async def get_version(self, part: StudioPartition, name: str) -> StudioAgentHead | None:
        """Revalidation query (§2.6)."""
        return await self._repos.agents.get_version(part, name)

    async def list(self, part: StudioPartition, *, owner: str | None = None) -> list[StudioAgentRecord]:
        """Agents of the partition."""
        return await self._repos.agents.list(part, owner=owner)
