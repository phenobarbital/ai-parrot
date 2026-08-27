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
from datetime import datetime
from pathlib import Path
from typing import Any

from asyncdb.exceptions import NoDataFound
from navigator_auth.decorators import is_authenticated, user_session
from parrot.conf import AGENTS_DIR
from pydantic import BaseModel, ValidationError

from ..models.studio_drafts import StudioDraft
from ._base import StudioBaseView, is_valid_slug, resolve_safe_path
from .models import StudioError
from .validation import detect_base_class, validate_draft

DRAFTS_SUBDIR = "_drafts"


class SaveDraftRequest(BaseModel):
    """``POST /astudio/drafts`` payload."""
    name: str
    source: str


class ActivateDraftRequest(BaseModel):
    """``POST /astudio/drafts/{name}/activate`` payload."""
    replace: bool = False


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

    def _registry(self):
        manager = self.request.app.get("bot_manager")
        return manager.registry if manager else None

    async def _get_draft_row(self, name: str) -> StudioDraft | None:
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
            return None

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
            self.logger.warning(
                "Studio: no database configured; draft state not persisted."
            )
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
            self.logger.error(
                "Studio: failed to delete draft row '%s': %s", row.name, exc
            )

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
        name = self.request.match_info.get("name")
        if name:
            return await self._get_one(name)
        return await self._get_all()

    async def _get_one(self, name: str):
        row = await self._get_draft_row(name)
        if row is None:
            return self._error(
                f"Draft '{name}' not found.", status=404, code="not_found"
            )
        data = self._draft_to_dict(row)
        draft_path = Path(row.file_path)
        data["source"] = draft_path.read_text() if draft_path.exists() else None
        return self.json_response(data)

    async def _get_all(self):
        rows = await self._get_all_draft_rows()
        return self.json_response(
            {"drafts": [self._draft_to_dict(r) for r in rows], "count": len(rows)}
        )

    async def post(self):
        """Save a draft — validation runs, but the draft is saved either way."""
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
            return self._error(
                f"Invalid request: {exc}", status=400, code="invalid_request"
            )

        if not is_valid_slug(save_request.name):
            return self._error(
                f"Invalid draft name '{save_request.name}'; must match "
                "^[a-z0-9_-]+$.",
                status=400,
                code="invalid_name",
            )

        try:
            file_path = resolve_safe_path(
                self._drafts_dir(), f"{save_request.name}.py"
            )
        except ValueError as exc:
            return self._error(str(exc), status=400, code="invalid_path")

        file_path.write_text(save_request.source)

        # Pure static analysis — NEVER imports/executes the draft.
        report = validate_draft(save_request.source)
        base_class = detect_base_class(save_request.source) if report.passed else None
        status = "validated" if report.passed else "failed"

        user = await self._get_user()
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
        name = self.request.match_info.get("name")
        if not name:
            return self._error(
                "Draft name is required.", status=400, code="missing_name"
            )

        row = await self._get_draft_row(name)
        if row is None:
            return self._error(
                f"Draft '{name}' not found.", status=404, code="not_found"
            )

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
        name = self.request.match_info.get("name")
        if not name:
            return self._error(
                "Draft name is required.", status=400, code="missing_name"
            )

        row = await self._get_draft_row(name)
        if row is None:
            return self._error(
                f"Draft '{name}' not found.", status=404, code="not_found"
            )

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            payload = {}
        try:
            activate_request = ActivateDraftRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(
                f"Invalid request: {exc}", status=400, code="invalid_request"
            )

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
            return self._error(
                "AgentRegistry unavailable.", status=503, code="unavailable"
            )

        if registry.has(name):
            existing_meta = registry.get_metadata(name)
            existing_owner = None
            if existing_meta is not None and existing_meta.bot_config is not None:
                existing_owner = (existing_meta.bot_config.config or {}).get(
                    "created_by"
                )
            if not activate_request.replace:
                return self._error(
                    f"Agent '{name}' is already registered; pass "
                    "replace=true to overwrite.",
                    status=409,
                    code="name_collision",
                )
            if (
                existing_owner is not None
                and str(existing_owner) != str(user.user_id)
                and not user.is_superuser
            ):
                return self._error(
                    f"Agent '{name}' is owned by another user; cannot replace.",
                    status=409,
                    code="not_owner",
                )

        # Move the file into AGENTS_DIR/ so the startup loader also finds
        # it on next boot (spec §7 "Activation moves the file with
        # Path.replace into AGENTS_DIR/").
        target_path = Path(AGENTS_DIR) / f"{name}.py"
        try:
            draft_path.replace(target_path)
        except OSError as exc:
            return self._error(
                f"Failed to move draft file: {exc}", status=500, code="move_failed"
            )

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
                    name, exc,
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

        return self.json_response(
            {"name": name, "activated": True, "file_path": str(target_path)}
        )

