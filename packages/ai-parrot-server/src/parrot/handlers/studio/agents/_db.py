"""Database-mode agent paths (GET / POST / DELETE / PATCH) as a mixin."""

from __future__ import annotations


from aiohttp import web
from parrot.utils.naming import slugify_name
from pydantic import ValidationError


from .._base import is_valid_slug
from ..access import _store_record
from ..models import CreateAgentRequest
from ..storage.models import (
    RESERVED_CONFIG_KEY_MESSAGE,
    StudioAgentDefinition,
    StudioAgentKey,
    StudioAgentPatch,
    StudioNameConflict,
)


class _StudioAgentsDbMixin:
    """Database-mode GET / POST / DELETE / PATCH of ``StudioAgentsHandler``."""

    async def _db_get(self, storage, part):
        """Studio rows of the partition; the GLOBAL partition also serves legacy agents (unchanged shapes)."""
        name = self.request.match_info.get("name")
        if name:
            rec = await storage.services.agents.get(part, name)
            if rec is None:
                return await self._legacy_get() if part.tenant is None else self._not_found("agent", name)
            if (denied := await self._studio_authorize(rec, name, manage=False)) is not None:
                return denied
            return self.json_response(self._studio_item_for(await self._access(), rec))
        access = await self._access()
        recs = await storage.services.agents.list(part)
        visible = [r for r in recs if access.can_see(_store_record("agent", r.agent_id, r))]
        agents = [self._studio_item_for(access, r) for r in visible]
        if part.tenant is None:
            seen = {a["name"] for a in agents}
            agents += [i for i in await self._legacy_items() if i["name"] not in seen]
        return self.json_response({"agents": agents, "count": len(agents)})

    async def _create_request(self):
        """Parse and validate the POST body: ``(request, slug)`` or an error response."""
        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")
        if (refused := self._refuse_expected_version(payload)) is not None:
            return refused
        try:
            create_request = CreateAgentRequest(**(payload or {}))
            slug = slugify_name(create_request.name)
        except (ValidationError, TypeError) as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")
        except ValueError as exc:
            return self._error(str(exc), status=400, code="invalid_name")
        if not is_valid_slug(create_request.category):
            return self._error(
                f"Invalid category '{create_request.category}'; must match ^[a-z0-9_-]+$.",
                status=400,
                code="invalid_category",
            )
        return create_request, slug

    def _create_refusal(self, access, create_request: CreateAgentRequest):
        """400 ``reserved_config_key`` (config keys the server owns), then the visibility 422s."""
        if (key := access.reject_reserved_keys(create_request.config)) is not None:
            return self._error(f"Reserved config key '{key}'.", status=400, code="reserved_config_key")
        return self._visibility_refusal(access, create_request.visibility, create_request.allowed_groups)

    async def _create_preflight(self, part, slug: str, create_request: CreateAgentRequest):
        """GLOBAL partition: the duplicate check also covers the legacy registry and ``ai_bots``; bot class check."""
        if part.tenant is not None:
            return None  # the tenant allowlist is enforced by the service
        if await self._check_duplicate(slug):
            return self._name_taken(slug)
        manager = self._manager()
        if manager is None:
            return self._error("BotManager unavailable.", status=503, code="unavailable")
        if manager.get_bot_class(create_request.bot_class) is None:
            return self._error(
                f"Unknown bot_class '{create_request.bot_class}'.", status=400, code="invalid_bot_class"
            )
        return None

    async def _db_post(self, storage, part):
        """Create a Studio agent row (always persisted; ``persist: false`` only adds a warning)."""
        if (denied := await self._require_author()) is not None:
            return denied
        if self.request.match_info.get("name"):
            return self._error("Use POST /astudio/agents (no name in the URL) to create.", status=400,
                               code="invalid_route")
        parsed = await self._create_request()
        if isinstance(parsed, web.Response):
            return parsed
        create_request, slug = parsed
        access = await self._access()
        if (denied := self._create_refusal(access, create_request)) is not None:
            return denied
        if (denied := await self._create_preflight(part, slug, create_request)) is not None:
            return denied
        try:
            definition = StudioAgentDefinition.from_create_request(create_request)
        except ValidationError as exc:
            reserved = RESERVED_CONFIG_KEY_MESSAGE in str(exc)
            return self._error(f"Invalid request: {exc}", status=400 if reserved else 422,
                               code="reserved_config_key" if reserved else "unsupported_config_key")
        stamp = access.stamp(visibility=create_request.visibility, allowed_groups=create_request.allowed_groups)
        try:
            rec = await storage.services.agents.create(
                part, name=slug, owner=stamp["owner"], definition=definition,
                visibility=stamp["visibility"], allowed_groups=stamp["allowed_groups"],
            )
        except StudioNameConflict:
            return self._name_taken(slug)
        body = {"name": slug, "persisted": True, "source": "studio", "file_path": None,
                "agent_id": str(rec.agent_id), "version": rec.version, "tenant": rec.tenant}
        if "persist" in create_request.model_fields_set and not create_request.persist:
            body["warnings"] = ["persist ignored: database storage always persists"]
        return self.json_response(body, status=201)

    async def _db_delete(self, storage, part):
        """Guarded delete of a Studio row; a GLOBAL name that is not a Studio row takes the legacy path."""
        name, rec = await self._studio_name_lookup(storage, part)
        if rec is None and part.tenant is None:
            return await self._legacy_delete()
        if (denied := await self._require_author()) is not None:
            return denied
        if not name:
            return self._error("Agent name is required.", status=400, code="missing_name")
        if rec is None:
            return self._not_found("agent", name)
        if (denied := await self._studio_authorize(rec, name, manage=True)) is not None:
            return denied
        svc = storage.services.agents
        deleted = await self._studio_write(
            lambda guard: svc.delete(part, name, guard=guard),
            record=rec, reread=lambda: svc.get(part, name), reauthorize=self._reauthorize("agent", name),
            expected_version=self._expected_version(self.request.query),
        )
        if isinstance(deleted, web.Response):
            return deleted
        if not deleted:
            return self._not_found("agent", name)
        if (runtime := getattr(self._manager(), "studio", None)) is not None:
            runtime.evict(StudioAgentKey(part.tenant, name))
        return self.json_response({"name": name, "deleted": True})

    async def _patch_request(self):
        """Parse the PATCH body: a ``StudioAgentPatch`` or an error response (``name`` is immutable)."""
        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")
        if not isinstance(payload, dict):
            return self._error("The body must be a JSON object.", status=400, code="invalid_request")
        if "name" in payload:
            return self._error("An agent cannot be renamed.", status=422, code="name_immutable")
        if (key := (await self._access()).reject_reserved_keys(payload)) is not None:
            return self._error(f"Reserved key '{key}'.", status=400, code="reserved_config_key")
        try:
            return StudioAgentPatch(**payload)
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=422, code="invalid_request")

    async def _patch_missing(self, part, name: str):
        """No Studio row: a legacy agent is 409 ``not_studio_agent`` (GLOBAL only), anything else the one 404."""
        if part.tenant is None and await self._check_duplicate(name):
            return self._error(f"Agent '{name}' is not a Studio agent.", status=409, code="not_studio_agent")
        return self._not_found("agent", name)

    async def _db_patch(self, storage, part):
        """Edit the General fields of a Studio agent (§2.9a); a legacy agent is 409 ``not_studio_agent``."""
        name, rec = await self._studio_name_lookup(storage, part)
        if not name:
            return self._error("Agent name is required.", status=400, code="missing_name")
        if rec is None:
            return await self._patch_missing(part, name)
        if (denied := await self._studio_authorize(rec, name, manage=True)) is not None:
            return denied  # 404 invisible / 403 not manageable come before authoring_denied
        if (denied := await self._require_author()) is not None:
            return denied
        patch = await self._patch_request()
        if isinstance(patch, web.Response):
            return patch
        user = await self._get_user()
        svc = storage.services.agents
        updated = await self._studio_write(
            lambda guard: svc.patch(part, name, patch, guard=guard, actor=user.user_id),
            record=rec, reread=lambda: svc.get(part, name), reauthorize=self._reauthorize("agent", name),
            expected_version=patch.expected_version,
        )
        if isinstance(updated, web.Response):
            return updated
        return self.json_response(self._studio_item_for(await self._access(), updated))
