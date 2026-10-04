"""Agent Studio access service (FEAT-605 M2): one rule for every Studio record."""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from aiohttp import web

from parrot.handlers.scope import RequestScope, VisibilityLevel, normalize_visibility, scope_grants

logger = logging.getLogger(__name__)

RESERVED_KEYS: frozenset[str] = frozenset({"owner", "created_by", "tenant", "visibility", "allowed_groups"})


class StudioTenantRequired(Exception):
    """Opted in and ``scope.tenant is None`` (handlers: empty list / 404 / 422 ``tenant_required``)."""


@dataclass(frozen=True)
class StudioVisibilityRecord:
    """Storage-neutral view of the fields the access rule needs."""

    kind: Literal["agent", "draft", "skill"]
    key: str
    name: str
    owner: str | None
    tenant: str | None
    visibility: VisibilityLevel
    allowed_groups: tuple[str, ...]
    source: Literal["store", "legacy"]


@dataclass(frozen=True)
class StudioAgentRef:
    """Satisfies FEAT-622 ``AgentScopeView``."""

    agent_id: str | None
    name: str
    owner: str | None
    tenant: str | None
    visibility: VisibilityLevel


@dataclass(frozen=True)
class StudioToolScope:
    """Satisfies FEAT-622 ``ToolScopeView`` — value of ``RequestContext.kwargs['studio_scope']``."""

    caller: RequestScope
    agent: StudioAgentRef | None


def build_tool_scope(scope: RequestScope, agent: StudioAgentRef | None = None) -> StudioToolScope:
    """The one builder for ``studio_scope`` (name frozen for FEAT-622, X11)."""
    return StudioToolScope(caller=scope, agent=agent)


def bot_agent_ref(bot: Any) -> StudioAgentRef | None:
    """The :class:`StudioAgentRef` of a Studio-built bot (``bot._studio_key``), or ``None`` for any other bot."""
    key = getattr(bot, "_studio_key", None)
    if key is None:
        return None
    agent_id = getattr(bot, "_studio_agent_id", None)
    return StudioAgentRef(agent_id=None if agent_id is None else str(agent_id), name=key.name,
                          owner=getattr(bot, "_tooling_owner", None), tenant=key.tenant,
                          visibility=normalize_visibility(getattr(bot, "_studio_visibility", None)))


async def studio_scope_kwargs(app: Any, request: web.Request, chatbot: Any) -> dict:
    """``{"studio_scope": …}`` for ``chatbot.session(...)`` when the host installed a scope resolver; ``{}`` otherwise.

    The scope is the caller's, with the Studio agent reference of ``chatbot`` (``None`` for a non-Studio bot). With no
    resolver nothing is bound, so a tenant-bound tool refuses ``no_scope`` (FEAT-622 M5).
    """
    from parrot.handlers.scope import get_scope_resolver, has_installed_resolver

    if not has_installed_resolver(app):
        return {}
    scope = await get_scope_resolver(app).resolve(request)
    return {"studio_scope": build_tool_scope(scope, bot_agent_ref(chatbot))}


def _store_record(kind: str, key: Any, rec: Any) -> StudioVisibilityRecord:
    """Map a FEAT-621 record (agent/draft/skill) to a visibility record."""
    return StudioVisibilityRecord(
        kind=kind,  # type: ignore[arg-type]
        key=str(key),
        name=rec.name,
        owner=None if rec.owner is None else str(rec.owner),
        tenant=rec.tenant,
        visibility=normalize_visibility(rec.visibility),  # type: ignore[arg-type]
        allowed_groups=tuple(rec.allowed_groups),
        source="store",
    )


def _legacy_record(kind: str, key: Any, name: str, owner: Any) -> StudioVisibilityRecord:
    """A FEAT-467 record: no tenant, private, owner only."""
    return StudioVisibilityRecord(
        kind=kind,  # type: ignore[arg-type]
        key=str(key),
        name=name,
        owner=None if owner is None else str(owner),
        tenant=None,
        visibility="private",
        allowed_groups=(),
        source="legacy",
    )


class StudioAccess:
    """Access decisions for one request's scope (spec §2 "Access rule")."""

    def __init__(self, scope: RequestScope, *, opted_in: bool, app: Any = None) -> None:
        self.scope, self.opted_in, self._app = scope, opted_in, app

    # ---- the rule -------------------------------------------------------
    def _in_tenant(self, r: StudioVisibilityRecord) -> bool:
        s = self.scope
        return s.tenant is not None and r.tenant is not None and r.tenant == s.tenant

    def _owns(self, r: StudioVisibilityRecord) -> bool:
        return self._in_tenant(r) and r.owner is not None and str(r.owner) == str(self.scope.user_id)

    def _administers(self, r: StudioVisibilityRecord) -> bool:
        return self._in_tenant(r) and (self.scope.may_administer or self.scope.is_superuser)

    def _grants(self, r: StudioVisibilityRecord) -> bool:
        return scope_grants(tenant=r.tenant, visibility=r.visibility, allowed_groups=r.allowed_groups, scope=self.scope)

    def can_see(self, r: StudioVisibilityRecord) -> bool:
        """Not opted in: always; else owns ∪ administers ∪ grants (tenant-bound)."""
        if not self.opted_in:
            return True
        return self._owns(r) or self._administers(r) or self._grants(r)

    def can_manage(self, r: StudioVisibilityRecord) -> bool:
        """Not opted in: FEAT-467 ``_require_owner``; else owns ∪ administers."""
        if not self.opted_in:
            return self.scope.is_superuser or (r.owner is not None and str(r.owner) == str(self.scope.user_id))
        return self._owns(r) or self._administers(r)

    def access_tag(self, r: StudioVisibilityRecord) -> str:
        """``global`` | ``owner`` | ``admin`` | ``tenant`` | ``groups``."""
        if not self.opted_in:
            return "global"
        if self._owns(r):
            return "owner"
        if self._administers(r):
            return "admin"
        return "tenant" if r.visibility == "tenant" else "groups"

    def visibility_fields(self, r: StudioVisibilityRecord) -> dict:
        """tenant, owner, visibility, allowed_groups, access, can_manage (C14, AC10)."""
        return {"tenant": r.tenant, "owner": r.owner, "visibility": r.visibility,
                "allowed_groups": list(r.allowed_groups), "access": self.access_tag(r),
                "can_manage": self.can_manage(r)}

    def agent_ref(self, r: StudioVisibilityRecord) -> StudioAgentRef:
        """Build the agent reference bound into ``studio_scope``."""
        return StudioAgentRef(agent_id=r.key if r.source == "store" else None, name=r.name,
                              owner=r.owner, tenant=r.tenant, visibility=r.visibility)

    # ---- write-side helpers --------------------------------------------
    @staticmethod
    def reject_reserved_keys(payload: Mapping[str, Any]) -> str | None:
        """Return the first reserved key present (⇒ 400 reserved_config_key), else None."""
        if not isinstance(payload, Mapping):
            return None
        return next((k for k in sorted(RESERVED_KEYS) if k in payload), None)

    def stamp(self, *, visibility: str, allowed_groups: list[str]) -> dict:
        """Server-owned owner/tenant/visibility/allowed_groups for a store write (AC8).

        Raises:
            ValueError: ``scope.user_id`` is empty (never stamp an ownerless row).
        """
        if not self.scope.user_id:
            raise ValueError("cannot stamp a record without an authenticated user_id")
        return {"owner": self.scope.user_id, "tenant": self.scope.tenant,
                "visibility": normalize_visibility(visibility), "allowed_groups": list(allowed_groups)}

    def validate_visibility(self, *, visibility: str, allowed_groups: list[str]) -> str | None:
        """Return ``tenant_required`` | ``groups_required`` | ``groups_not_allowed``, or None."""
        level = normalize_visibility(visibility)
        if level == "private":
            return None
        if self.scope.tenant is None:
            return "tenant_required"
        if level != "groups":
            return None
        if not allowed_groups:
            return "groups_required"
        if self.scope.may_administer or self.scope.is_superuser:
            return None
        return None if set(allowed_groups) <= self.scope.groups else "groups_not_allowed"

    # ---- lookups --------------------------------------------------------
    def _repos(self) -> Any:
        storage = self._app.get("studio_storage") if self._app is not None else None
        return getattr(storage, "repos", None)

    def _partition(self) -> Any:
        from .storage.models import StudioPartition

        if self.scope.tenant is None:
            raise StudioTenantRequired
        return StudioPartition.from_scope(self.scope)

    async def agent(self, name: str) -> StudioVisibilityRecord | None:
        """Tenant path: store row (scope.tenant, name). Legacy path: FEAT-467 lookup (DB row, then registry)."""
        if not self.opted_in:
            return await self._legacy_agent(name)
        repos = self._repos()
        rec = await repos.agents.get(self._partition(), name) if repos is not None else None
        return None if rec is None else _store_record("agent", rec.agent_id, rec)

    async def draft(self, name: str) -> StudioVisibilityRecord | None:
        """Tenant path: draft row (scope.tenant, name). Legacy path: ``StudioDraft`` row."""
        if not self.opted_in:
            return await self._legacy_draft(name)
        repos = self._repos()
        rec = await repos.drafts.get(self._partition(), name) if repos is not None else None
        return None if rec is None else _store_record("draft", rec.draft_id, rec)

    async def skill(self, skill_id: str) -> StudioVisibilityRecord | None:
        """Tenant path: skill row by id. Legacy path: ``SkillCatalogEntry`` row."""
        if not self.opted_in:
            return await self._legacy_skill(skill_id)
        try:
            sid = UUID(str(skill_id))
        except ValueError:
            return None
        repos = self._repos()
        rec = await repos.skills.get(self._partition(), sid) if repos is not None else None
        return None if rec is None else _store_record("skill", rec.skill_id, rec)

    async def _legacy_row(self, model: Any, **where: Any) -> Any:
        """Fetch one legacy row: ``None`` when absent or no database; HTTP 503 on a DB error (fail closed).

        ``model.Meta.connection`` is the class-attribute pattern every FEAT-467 handler uses (pre-existing).
        """
        from asyncdb.exceptions import NoDataFound

        db = self._app.get("database") if self._app is not None else None
        if db is None:
            return None
        try:
            async with await db.acquire() as conn:
                model.Meta.connection = conn
                try:
                    return await model.get(**where)
                except NoDataFound:
                    return None
        except Exception as exc:  # noqa: BLE001 - never turn a DB error into "absent"/404
            logger.error("Studio access: legacy lookup failed: %s", exc)
            raise web.HTTPServiceUnavailable(
                text=json.dumps({"message": "Ownership lookup unavailable.", "code": "lookup_unavailable"}),
                content_type="application/json",
            ) from exc

    async def _legacy_agent(self, name: str) -> StudioVisibilityRecord | None:
        from ..models import BotModel

        row = await self._legacy_row(BotModel, name=name)
        if row is not None:
            return _legacy_record("agent", name, name, getattr(row, "created_by", None))
        manager = self._app.get("bot_manager") if self._app is not None else None
        registry = getattr(manager, "registry", None)
        meta = registry.get_metadata(name) if registry is not None else None
        if meta is None:
            return None
        config = getattr(getattr(meta, "bot_config", None), "config", None) or {}
        return _legacy_record("agent", name, name, config.get("created_by"))

    async def _legacy_draft(self, name: str) -> StudioVisibilityRecord | None:
        from ..models.studio_drafts import StudioDraft

        row = await self._legacy_row(StudioDraft, name=name)
        return None if row is None else _legacy_record("draft", name, name, row.owner_user_id)

    async def _legacy_skill(self, skill_id: str) -> StudioVisibilityRecord | None:
        from ..models.skills_catalog import SkillCatalogEntry

        row = await self._legacy_row(SkillCatalogEntry, skill_id=skill_id)
        if row is None:
            return None
        return _legacy_record("skill", skill_id, str(getattr(row, "name", skill_id)), row.owner)
