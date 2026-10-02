"""Database-mode draft paths as mixins."""

from __future__ import annotations


from aiohttp import web
from pydantic import ValidationError

from .._base import is_valid_slug
from ..access import _store_record
from ..storage.models import (
    RESERVED_CONFIG_KEY_MESSAGE,
    StudioAgentKey,
    StudioVersionConflict,
    StudioWriteGuard,
)
from ._models import ActivateDraftRequest, SaveDraftRequest


class _StudioDraftsDbMixin:
    """Database-mode GET / POST / DELETE of ``StudioDraftsHandler``."""

    async def _db_get(self, storage, part):
        """Declarative drafts the caller can see; legacy Python drafts are merged on the GLOBAL partition."""
        name = self.request.match_info.get("name")
        svc, access = storage.services.drafts, await self._access()
        if name:
            rec = await svc.get(part, name)
            if rec is None:
                return await self._legacy_get() if part.tenant is None else self._not_found("draft", name)
            if (denied := await self._check_record_access(access, _store_record("draft", rec.draft_id, rec),
                                                          "draft", name)) is not None:
                return denied
            return self.json_response(self._studio_draft_item(rec))
        recs = [r for r in await svc.list(part) if access.can_see(_store_record("draft", r.draft_id, r))]
        items = [self._studio_draft_item(r) for r in recs]
        if part.tenant is None:
            seen = {i["name"] for i in items}
            items += [d for r in await self._get_all_draft_rows() if (d := self._draft_to_dict(r))["name"] not in seen]
        return self.json_response({"drafts": items, "count": len(items)})

    async def _db_post_request(self):
        """Parse the POST body: a ``SaveDraftRequest`` or an error response."""
        if self.request.match_info.get("name"):
            return self._error("Use POST /astudio/drafts (no name in the URL) to save.", status=400,
                               code="invalid_route")
        try:
            payload = await self.request.json()
            return SaveDraftRequest(**(payload or {}))
        except ValidationError as exc:
            if RESERVED_CONFIG_KEY_MESSAGE in str(exc):
                return self._error(f"Invalid request: {exc}", status=400, code="reserved_config_key")
            code = "unsupported_config_key" if any("config" in e["loc"] for e in exc.errors()) else "invalid_request"
            return self._error(f"Invalid request: {exc}", status=422, code=code)
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

    async def _db_save_refusal(self, part, parsed) -> web.Response | None:
        """The refusal (author gate, name, GLOBAL visibility) of a declarative save, or ``None``."""
        if (denied := await self._require_author()) is not None:
            return denied
        name = parsed.name
        if not is_valid_slug(name) or name != parsed.bundle.name:
            return self._error(f"Invalid draft name '{name}'; must match ^[a-z0-9_-]+$ and equal bundle.name.",
                               status=400, code="invalid_name")
        if part.tenant is None and (parsed.visibility != "private" or parsed.allowed_groups):
            return self._tenant_required()  # the GLOBAL partition is always private (FEAT-605 plain-host rule)
        return None

    async def _db_post(self, storage, part):
        """Declarative ``bundle`` → ``StudioDraftService.save_bundle``; Python ``source`` only where the gate allows."""
        parsed = await self._db_post_request()
        if isinstance(parsed, web.Response):
            return parsed
        svc = storage.services.drafts
        if parsed.source is not None:
            if not svc.python_drafts_allowed(part):
                return self._error("Python drafts are not available here; save a declarative bundle.", status=422,
                                   code="declarative_only")
            return await self._legacy_post()
        if (denied := await self._db_save_refusal(part, parsed)) is not None:
            return denied
        name = parsed.name
        existing = await svc.get(part, name)
        if existing is not None and (denied := await self._check_record_access(
                await self._access(), _store_record("draft", existing.draft_id, existing), "draft", name,
                manage=True)) is not None:
            return denied
        user = await self._get_user()
        rec = await self._studio_write(
            lambda guard: svc.save_bundle(part, owner=user.user_id, bundle=parsed.bundle,
                                          visibility=parsed.visibility, allowed_groups=parsed.allowed_groups,
                                          guard=guard),
            record=existing, reread=lambda: svc.get(part, name),
            reauthorize=self._reauthorize("draft", name, key="draft_id"), expected_version=parsed.expected_version,
        )
        if isinstance(rec, web.Response):
            return rec
        return self.json_response({"name": name, "status": rec.status, "file_path": None,
                                   "validation_report": rec.validation, "kind": "declarative",
                                   "version": rec.version}, status=201)

    async def _db_delete(self, storage, part):
        """Guarded delete of a declarative draft; a GLOBAL name that is not a declarative draft is legacy."""
        name = self.request.match_info.get("name")
        svc = storage.services.drafts
        rec = await svc.get(part, name) if name else None
        if rec is None and part.tenant is None:
            return await self._legacy_delete()
        if (denied := await self._require_author()) is not None:
            return denied
        if not name:
            return self._error("Draft name is required.", status=400, code="missing_name")
        if rec is None:
            return self._not_found("draft", name)
        if (denied := await self._check_record_access(await self._access(), _store_record("draft", rec.draft_id, rec),
                                                      "draft", name, manage=True)) is not None:
            return denied
        if (refused := self._refuse_expected_version(self.request.query)) is not None:
            return refused  # §2.9: DELETE /drafts/{name} is not an expected_version route
        deleted = await self._studio_write(
            lambda guard: svc.delete(part, name, guard=guard),
            record=rec, reread=lambda: svc.get(part, name),
            reauthorize=self._reauthorize("draft", name, key="draft_id"), expected_version=None,
        )
        if isinstance(deleted, web.Response):
            return deleted
        return self.json_response({"name": name, "deleted": True}) if deleted else self._not_found("draft", name)


class _StudioDraftActivateDbMixin:
    """Database-mode activation of ``StudioDraftActivateHandler``."""

    async def _activate_request(self):
        """Parse the optional activation body: an ``ActivateDraftRequest`` or an error response."""
        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            payload = {}
        try:
            return ActivateDraftRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

    async def _activation_target(self, svc_agents, part, name: str, replace: bool):
        """``(target, refusal)``: the agent the draft would replace, or a 409 ``name_taken`` for a collision."""
        target = await svc_agents.get(part, name)
        legacy = part.tenant is None and (reg := self._registry()) is not None and reg.has(name)
        if legacy or (target is not None and not replace):
            return None, self._name_taken(name)
        if target is not None and not (await self._access()).can_manage(_store_record("agent", target.agent_id, target)):
            return None, self._name_taken(name)
        return target, None

    async def _activation_precheck(self, svc, part, name):
        """``(draft, refusal)``: the draft the caller may manage — access runs BEFORE any 409/400 (no leaks)."""
        if (denied := await self._require_author()) is not None:
            return None, denied
        if not name:
            return None, self._error("Draft name is required.", status=400, code="missing_name")
        rec = await svc.get(part, name)
        denied = await self._check_record_access(
            await self._access(), _store_record("draft", rec.draft_id, rec) if rec else None, "draft", name,
            manage=True)
        return (None, denied) if denied is not None else (rec, None)

    async def _db_post(self, storage, part):
        """One transaction over draft + agent (§2.5a); a GLOBAL name that is not a declarative draft is legacy."""
        name = self.request.match_info.get("name")
        svc = storage.services.drafts
        if part.tenant is None and (name is None or await svc.get(part, name) is None):
            return await self._legacy_post()
        rec, refusal = await self._activation_precheck(svc, part, name)
        if refusal is not None:
            return refusal
        parsed = await self._activate_request()
        if isinstance(parsed, web.Response):
            return parsed
        if rec.status not in ("draft", "validated"):  # already activated (or failed): nothing to race over
            return self._studio_error(StudioVersionConflict(f"draft {name!r} is {rec.status}, not activatable"))
        target, refusal = await self._activation_target(storage.services.agents, part, name, parsed.replace)
        if refusal is not None:
            return refusal
        user = await self._get_user()
        target_guard = StudioWriteGuard.for_record(target, expected_version=parsed.target_expected_version)
        agent = await self._studio_write(
            lambda guard: svc.activate(part, name, owner=user.user_id, replace=target is not None, guard=guard,
                                       target_guard=target_guard),
            record=rec, reread=lambda: svc.get(part, name),
            reauthorize=self._reauthorize("draft", name, key="draft_id"), expected_version=parsed.expected_version,
        )
        return agent if isinstance(agent, web.Response) else self._activated_response(part, name, agent)

    def _activated_response(self, part, name: str, agent) -> web.Response:
        """Evict the cached runtime of the (re)activated agent and answer the activation body."""
        if (runtime := getattr(self.request.app.get("bot_manager"), "studio", None)) is not None:
            runtime.evict(StudioAgentKey(part.tenant, name))
        return self.json_response({"name": name, "activated": True, "file_path": None,
                                   "agent_id": str(agent.agent_id), "version": agent.version})
