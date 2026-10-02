"""Studio draft pipeline — save/list/read/activate/delete (FEAT-467 TASK-2513).

Implements the draft -> validate -> activate safety gate (spec §3 Module
5): a generated Python agent is saved to ``AGENTS_DIR/_drafts/`` and
statically validated (``validation.validate_draft``) on save. It is
imported and registered into the live ``AgentRegistry`` ONLY on an
explicit ``POST .../activate`` call — the ONLY path from generated code
to live code (spec §7 "Draft import side effects": the AST allowlist
must run BEFORE any import).
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from aiohttp import web
from asyncdb.exceptions import NoDataFound
from navigator_auth.decorators import is_authenticated, user_session
from parrot.conf import AGENTS_DIR
from pydantic import BaseModel, ValidationError, model_validator

from ..models.studio_drafts import StudioDraft
from ._base import StudioBaseView, is_valid_slug, resolve_safe_path
from .access import _store_record
from .agents import _StudioAgentsMixin
from .models import StudioError
from .storage.models import RESERVED_CONFIG_KEY_MESSAGE, StudioAgentBundle, StudioAgentKey, StudioVersionConflict, StudioWriteGuard
from .validation import detect_base_class, validate_draft

DRAFTS_SUBDIR = "_drafts"


class SaveDraftRequest(BaseModel):
    """``POST /astudio/drafts`` payload."""

    name: str
    source: str | None = None
    bundle: StudioAgentBundle | None = None
    visibility: str = "private"
    allowed_groups: list[str] = []
    expected_version: int | None = None

    @model_validator(mode="after")
    def _exactly_one_body(self) -> "SaveDraftRequest":
        """A draft is either Python ``source`` or a declarative ``bundle`` — never both, never neither."""
        if (self.source is None) == (self.bundle is None):
            raise ValueError("exactly one of 'source' and 'bundle' is required")
        return self


class ActivateDraftRequest(BaseModel):
    """``POST /astudio/drafts/{name}/activate`` payload."""

    replace: bool = False
    expected_version: int | None = None
    target_expected_version: int | None = None


class _StudioDraftsMixin:
    """Shared helpers for the draft-pipeline views in this module."""

    def _drafts_dir(self) -> Path:
        """Return (creating if needed) ``AGENTS_DIR/_drafts/``.

        Deliberately a subdirectory of ``AGENTS_DIR`` so
        ``AgentRegistry._load_modules_from_directory``'s non-recursive
        ``glob("*.py")`` on ``AGENTS_DIR`` itself never discovers drafts
        (spec Codebase Contract "Does NOT Exist" — drafts must stay
        invisible to the startup loader until activated).
        """
        d = Path(AGENTS_DIR) / DRAFTS_SUBDIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    _dispatch = _StudioAgentsMixin._dispatch  # one database/filesystem switch for every Studio view

    def _registry(self):
        manager = self.request.app.get("bot_manager")
        return manager.registry if manager else None

    async def _get_draft_row(self, name: str) -> StudioDraft | None:
        """Read a draft, refusing unavailable ownership information with HTTP 503."""
        db = self.request.app.get("database")
        if db is None:
            return None
        try:
            async with await db.acquire() as conn:
                StudioDraft.Meta.connection = conn
                try:
                    return await StudioDraft.get(name=name)
                except NoDataFound:
                    return None
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to query draft '%s': %s", name, exc)
            raise web.HTTPServiceUnavailable(
                text=json.dumps(
                    StudioError(message="Draft lookup unavailable.", code="draft_lookup_failed").model_dump()
                ),
                content_type="application/json",
            ) from exc

    async def _get_all_draft_rows(self) -> list[StudioDraft]:
        db = self.request.app.get("database")
        if db is None:
            return []
        try:
            async with await db.acquire() as conn:
                StudioDraft.Meta.connection = conn
                rows = await StudioDraft.filter()
                return rows or []
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to list drafts: %s", exc)
            return []

    async def _upsert_draft_row(self, **fields: Any) -> StudioDraft | None:
        """Insert a new draft row, or update the existing one by name."""
        db = self.request.app.get("database")
        if db is None:
            self.logger.warning("Studio: no database configured; draft state not persisted.")
            return None
        try:
            async with await db.acquire() as conn:
                StudioDraft.Meta.connection = conn
                try:
                    existing = await StudioDraft.get(name=fields["name"])
                except NoDataFound:
                    existing = None
                if existing is not None:
                    for key, value in fields.items():
                        existing.set(key, value)
                    existing.set("updated_at", datetime.now())
                    await existing.update()
                    return existing
                row = StudioDraft(**fields)
                await row.insert()
                return row
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to persist draft row: %s", exc)
            return None

    async def _delete_draft_row(self, row: StudioDraft) -> None:
        """Delete a draft's state row (best-effort — logs, never raises)."""
        db = self.request.app.get("database")
        if db is None:
            return
        try:
            async with await db.acquire() as conn:
                StudioDraft.Meta.connection = conn
                await row.delete()
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to delete draft row '%s': %s", row.name, exc)

    @staticmethod
    def _draft_to_dict(row: StudioDraft) -> dict:
        return {
            "draft_id": str(row.draft_id),
            "name": row.name,
            "file_path": row.file_path,
            "status": row.status,
            "validation_report": row.validation_report,
            "base_class": row.base_class,
            "owner_user_id": row.owner_user_id,
            "kind": "python",
            "tenant": None,
            "visibility": "private",
            "allowed_groups": [],
            "version": None,
        }

    @staticmethod
    def _studio_draft_item(rec) -> dict:
        """JSON item of a declarative draft (§2.9: the legacy keys plus the added ones)."""
        return {
            "draft_id": str(rec.draft_id), "name": rec.name, "file_path": None, "status": rec.status,
            "validation_report": rec.validation, "base_class": None, "owner_user_id": rec.owner,
            "kind": "declarative", "bundle": rec.bundle.model_dump(mode="json"), "tenant": rec.tenant,
            "visibility": rec.visibility, "allowed_groups": list(rec.allowed_groups), "version": rec.version,
        }

    def _error(self, message: str, *, status: int, code: str | None = None):
        """See ``handlers/studio/agents.py::_StudioAgentsMixin._error`` —
        ``BaseHandler.error()`` only maps a fixed status whitelist and
        silently falls back to 400 for 409/422/503."""
        return self.json_response(
            StudioError(message=message, code=code).model_dump(),
            status=status,
        )


@is_authenticated()
@user_session()
class StudioDraftsHandler(_StudioDraftsMixin, StudioBaseView):
    """``/api/v1/astudio/drafts`` and ``/api/v1/astudio/drafts/{name}``.

    GET (list/single incl. source + validation report), POST (save +
    validate), DELETE (owner-enforced).
    """

    async def get(self):
        """List/read drafts: the declarative store (database mode) plus legacy Python drafts on GLOBAL."""
        return await self._dispatch(self._legacy_get, self._db_get)

    async def _legacy_get(self):
        name = self.request.match_info.get("name")
        if name:
            return await self._get_one(name)
        return await self._get_all()

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

    async def _get_one(self, name: str):
        row = await self._get_draft_row(name)
        if row is None:
            return self._error(f"Draft '{name}' not found.", status=404, code="not_found")
        data = self._draft_to_dict(row)
        draft_path = Path(row.file_path)
        data["source"] = draft_path.read_text() if draft_path.exists() else None
        return self.json_response(data)

    async def _get_all(self):
        rows = await self._get_all_draft_rows()
        return self.json_response({"drafts": [self._draft_to_dict(r) for r in rows], "count": len(rows)})

    async def post(self):
        """Save a draft: a declarative ``bundle`` (database mode) or legacy Python ``source``."""
        gate = lambda: self._pbac_gate("drafts", "astudio:drafts:create")  # noqa: E731
        return await self._dispatch(self._legacy_post, self._db_post, gate)

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
        if (denied := await self._require_author()) is not None:
            return denied
        name = parsed.name
        if not is_valid_slug(name) or name != parsed.bundle.name:
            return self._error(f"Invalid draft name '{name}'; must match ^[a-z0-9_-]+$ and equal bundle.name.",
                               status=400, code="invalid_name")
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

    async def _legacy_post(self):
        """Save a draft — validation runs, but the draft is saved either way."""
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("drafts", "astudio:drafts:create")) is not None:
            return denied

        if self.request.match_info.get("name"):
            return self._error(
                "Use POST /astudio/drafts (no name in the URL) to save.",
                status=400,
                code="invalid_route",
            )

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            save_request = SaveDraftRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        if not is_valid_slug(save_request.name):
            return self._error(
                f"Invalid draft name '{save_request.name}'; must match " "^[a-z0-9_-]+$.",
                status=400,
                code="invalid_name",
            )

        try:
            file_path = resolve_safe_path(self._drafts_dir(), f"{save_request.name}.py")
        except ValueError as exc:
            return self._error(str(exc), status=400, code="invalid_path")

        user = await self._get_user()
        existing = await self._get_draft_row(save_request.name)
        if existing is not None and str(existing.owner_user_id) != str(user.user_id) and not user.is_superuser:
            return self._name_taken(save_request.name)

        file_path.write_text(save_request.source)

        # Pure static analysis — NEVER imports/executes the draft.
        report = validate_draft(save_request.source)
        base_class = detect_base_class(save_request.source) if report.passed else None
        status = "validated" if report.passed else "failed"

        await self._upsert_draft_row(
            name=save_request.name,
            file_path=str(file_path),
            status=status,
            validation_report=report.model_dump(),
            base_class=base_class,
            owner_user_id=user.user_id,
        )

        return self.json_response(
            {
                "name": save_request.name,
                "status": status,
                "file_path": str(file_path),
                "validation_report": report.model_dump(),
            },
            status=201,
        )

    async def delete(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("drafts", "astudio:drafts:delete")) is not None:
            return denied

        name = self.request.match_info.get("name")
        if not name:
            return self._error("Draft name is required.", status=400, code="missing_name")

        row = await self._get_draft_row(name)
        if row is None:
            return self._error(f"Draft '{name}' not found.", status=404, code="not_found")

        user = await self._get_user()
        self._require_owner(row.owner_user_id, user)  # raises 403 on denial

        file_path = Path(row.file_path)
        if file_path.exists():
            file_path.unlink()

        await self._delete_draft_row(row)

        return self.json_response({"name": name, "deleted": True})


@is_authenticated()
@user_session()
class StudioDraftActivateHandler(_StudioDraftsMixin, StudioBaseView):
    """``POST /api/v1/astudio/drafts/{name}/activate``.

    The ONLY path from a generated draft to a live, registered agent.
    Refuses (409) unless the draft's LATEST on-disk content re-validates
    clean, and unless any registered-name collision is explicitly
    consented to (``replace=true``) by the owner (or an admin).
    """

    async def post(self):
        """Activate a declarative draft atomically (database mode) or import a Python draft (legacy)."""
        gate = lambda: self._pbac_gate("drafts", "astudio:drafts:activate")  # noqa: E731
        return await self._dispatch(self._legacy_post, self._db_post, gate)

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

    async def _db_post(self, storage, part):
        """One transaction over draft + agent (§2.5a); a GLOBAL name that is not a declarative draft is legacy."""
        name = self.request.match_info.get("name")
        svc = storage.services.drafts
        rec = await svc.get(part, name) if name else None
        if rec is None and part.tenant is None:
            return await self._legacy_post()
        if (denied := await self._require_author()) is not None:
            return denied
        if not name:
            return self._error("Draft name is required.", status=400, code="missing_name")
        if rec is None:
            return self._not_found("draft", name)
        parsed = await self._activate_request()
        if isinstance(parsed, web.Response):
            return parsed
        if rec.status not in ("draft", "validated"):  # already activated (or failed): nothing to race over
            return self._studio_error(StudioVersionConflict(f"draft {name!r} is {rec.status}, not activatable"))
        if (denied := await self._check_record_access(await self._access(), _store_record("draft", rec.draft_id, rec),
                                                      "draft", name, manage=True)) is not None:
            return denied
        target, refusal = await self._activation_target(storage.services.agents, part, name, parsed.replace)
        if refusal is not None:
            return refusal
        user = await self._get_user()
        target_guard = StudioWriteGuard(authorized_version=target.version if target else None,
                                        expected_version=parsed.target_expected_version)
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

    async def _legacy_post(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("drafts", "astudio:drafts:activate")) is not None:
            return denied

        name = self.request.match_info.get("name")
        if not name:
            return self._error("Draft name is required.", status=400, code="missing_name")

        row = await self._get_draft_row(name)
        if row is None:
            return self._error(f"Draft '{name}' not found.", status=404, code="not_found")

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            payload = {}
        try:
            activate_request = ActivateDraftRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        user = await self._get_user()
        self._require_owner(row.owner_user_id, user)  # raises 403 on denial

        draft_path = Path(row.file_path)
        if not draft_path.exists():
            return self._error(
                f"Draft '{name}' has no source file on disk.",
                status=409,
                code="missing_source",
            )

        # Re-validate the CURRENT on-disk content — it may have been
        # edited since the last save (spec §7 "Key Constraints": "only
        # activate does [import], and only after a fresh re-validation").
        source = draft_path.read_text()
        report = validate_draft(source)
        if not report.passed:
            await self._upsert_draft_row(
                name=name,
                file_path=str(draft_path),
                status="failed",
                validation_report=report.model_dump(),
                base_class=row.base_class,
                owner_user_id=row.owner_user_id,
            )
            return self._error(
                f"Draft '{name}' failed validation and cannot be activated.",
                status=409,
                code="validation_failed",
            )

        registry = self._registry()
        if registry is None:
            return self._error("AgentRegistry unavailable.", status=503, code="unavailable")

        if registry.has(name):
            existing_meta = registry.get_metadata(name)
            existing_owner = None
            if existing_meta is not None and existing_meta.bot_config is not None:
                existing_owner = (existing_meta.bot_config.config or {}).get("created_by")
            if not activate_request.replace:
                return self._name_taken(name)
            if not user.is_superuser and (existing_owner is None or str(existing_owner) != str(user.user_id)):
                return self._name_taken(name)

        # Move the file into AGENTS_DIR/ so the startup loader also finds
        # it on next boot (spec §7 "Activation moves the file with
        # Path.replace into AGENTS_DIR/").
        target_path = Path(AGENTS_DIR) / f"{name}.py"
        try:
            draft_path.replace(target_path)
        except OSError as exc:
            return self._error(f"Failed to move draft file: {exc}", status=500, code="move_failed")

        try:
            registry._import_module_from_path(target_path, base_dir=AGENTS_DIR)
        except Exception as exc:  # pylint: disable=broad-except
            # Best-effort rollback: move the file back to _drafts/ so a
            # failed activate does not silently vanish the draft.
            with contextlib.suppress(OSError):
                target_path.replace(draft_path)
            return self._error(
                f"Failed to import draft '{name}': {exc}",
                status=422,
                code="import_failed",
            )

        if not registry.has(name):
            with contextlib.suppress(OSError):
                target_path.replace(draft_path)
            return self._error(
                f"Draft '{name}' did not register any agent on import "
                "(missing @register_agent, or its decorator did not pass "
                "replace=True).",
                status=422,
                code="not_registered",
            )

        # Stamp ownership on the freshly-registered metadata (mirrors
        # TASK-2512's create flow — owner lives in bot_config.config).
        metadata = registry.get_metadata(name)
        if metadata is not None and metadata.bot_config is not None:
            metadata.bot_config.config["created_by"] = user.user_id

        manager = self.request.app.get("bot_manager")
        if manager is not None:
            try:
                bot_instance = await registry.get_instance(name)
                if bot_instance is not None:
                    if not getattr(bot_instance, "is_configured", False):
                        await bot_instance.configure(self.request.app)
                    manager.add_bot(bot_instance)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning(
                    "Studio: draft '%s' activated but instantiation failed: %s",
                    name,
                    exc,
                )

        await self._upsert_draft_row(
            name=name,
            file_path=str(target_path),
            status="activated",
            validation_report=report.model_dump(),
            base_class=row.base_class,
            owner_user_id=row.owner_user_id,
            activated_at=datetime.now(),
        )

        return self.json_response({"name": name, "activated": True, "file_path": str(target_path)})
