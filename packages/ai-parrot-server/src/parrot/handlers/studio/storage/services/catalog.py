"""StudioSkillCatalogService (spec §2.5): partitioned catalogue + derived per-pod search index location."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

from ..models import (
    StudioAssetInput,
    StudioAssetRecord,
    StudioNotFound,
    StudioPartition,
    StudioSkillRecord,
    StudioWriteGuard,
)
from ..repositories import StudioRepositories, studio_transaction
from ._common import studio_runtime_dir, validate_visibility
from .assets import StudioAssetService

logger = logging.getLogger("Parrot.AgentStudio.Storage")
SHARED_NAMESPACE_SUFFIX = "_shared"


def shared_index_location(part: StudioPartition, org_id: str) -> tuple[str, Path]:
    """Namespace and persistence directory of the DERIVED shared search index of a partition (spec §2.8).

    The namespace is ``<tenant or org_id>/_shared``; the directory is
    ``STUDIO_RUNTIME_DIR/_shared/<tenant or ->/skills`` — never under ``AGENTS_DIR``.
    """
    namespace = f"{part.tenant or org_id}/{SHARED_NAMESPACE_SUFFIX}"
    return namespace, studio_runtime_dir() / SHARED_NAMESPACE_SUFFIX / (part.tenant or "-") / "skills"


class StudioSkillCatalogService:
    """The shared skills catalogue of a partition. Validates data; never decides access."""

    def __init__(self, repos: StudioRepositories, *, assets: StudioAssetService) -> None:
        self._repos, self._assets = repos, assets

    def shared_index_location(self, part: StudioPartition, org_id: str) -> tuple[str, Path]:
        """See the module-level :func:`shared_index_location`."""
        return shared_index_location(part, org_id)

    # ---- writes -----------------------------------------------------------------------------------------------
    async def publish(
        self,
        part: StudioPartition,
        *,
        owner: str,
        name: str,
        description: str,
        body: str,
        category: str = "general",
        triggers: Sequence[Any] = (),
        visibility: str = "private",
        allowed_groups: Sequence[str] = (),
    ) -> StudioSkillRecord:
        """Insert a skill; ``StudioNameConflict`` when the name is taken in the partition (tenant NULL included)."""
        validate_visibility(part, visibility, allowed_groups)
        async with studio_transaction(self._repos.pool) as conn:
            return await self._repos.skills.insert(
                conn, part, owner=owner, name=name, description=description, body=body, category=category,
                triggers=triggers, visibility=visibility, allowed_groups=allowed_groups,
            )

    async def update(
        self,
        part: StudioPartition,
        skill_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        triggers: Sequence[Any] | None = None,
        body: str | None = None,
        status: str | None = None,
    ) -> StudioSkillRecord:
        """Update the given fields (``None`` = unchanged); ``StudioNotFound`` when absent from the partition."""
        async with studio_transaction(self._repos.pool) as conn:
            record = await self._repos.skills.update(
                conn, part, skill_id, name=name, description=description, category=category, triggers=triggers,
                body=body, status=status,
            )
        if record is None:
            raise StudioNotFound(str(skill_id))
        return record

    async def update_visibility(
        self, part: StudioPartition, skill_id: UUID, *, visibility: str, allowed_groups: Sequence[str]
    ) -> StudioSkillRecord:
        """Store the visibility the caller decided; the non-tenant partition is always ``private``."""
        validate_visibility(part, visibility, allowed_groups)
        async with studio_transaction(self._repos.pool) as conn:
            record = await self._repos.skills.update_visibility(
                conn, part, skill_id, visibility=visibility, allowed_groups=allowed_groups
            )
        if record is None:
            raise StudioNotFound(str(skill_id))
        return record

    async def delete(self, part: StudioPartition, skill_id: UUID) -> bool:
        """Delete the skill; False when it does not exist in the partition."""
        async with studio_transaction(self._repos.pool) as conn:
            return await self._repos.skills.delete(conn, part, skill_id)

    async def mark_stale(self, part: StudioPartition, skill_id: UUID, stale: bool = True) -> bool:
        """Flag (or clear) ``search_index_stale``; False when the skill does not exist."""
        async with studio_transaction(self._repos.pool) as conn:
            return await self._repos.skills.mark_stale(conn, part, skill_id, stale)

    async def import_to_agent(
        self, part: StudioPartition, skill_id: UUID, agent_name: str, *, actor: str | None, guard: StudioWriteGuard
    ) -> tuple[StudioAssetRecord, int]:
        """Write the skill as ``skills/<name>.md`` of the agent, under the agent lock, through the asset service."""
        from parrot.handlers.studio.skills_catalog import _compose_skill_markdown

        skill = await self._repos.skills.get(part, skill_id)
        if skill is None:
            raise StudioNotFound(str(skill_id))
        asset = StudioAssetInput(kind="skills", name=f"{skill.name}.md", content=_compose_skill_markdown(skill))
        return await self._assets.put(part, agent_name, asset, actor=actor, guard=guard)

    # ---- reads ------------------------------------------------------------------------------------------------
    async def get(self, part: StudioPartition, skill_id: UUID) -> StudioSkillRecord | None:
        """The skill, or None."""
        return await self._repos.skills.get(part, skill_id)

    async def list(
        self, part: StudioPartition, *, category: str | None = None, owner: str | None = None
    ) -> list[StudioSkillRecord]:
        """Skills of the partition, ordered by name."""
        return await self._repos.skills.list(part, category=category, owner=owner)

    async def list_stale(self, part: StudioPartition) -> list[StudioSkillRecord]:
        """Skills whose derived search index needs a refresh."""
        return await self._repos.skills.list_stale(part)
