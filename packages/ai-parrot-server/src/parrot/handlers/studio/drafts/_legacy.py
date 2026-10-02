"""Filesystem-mode (legacy) draft paths — the verbatim ``_legacy_*`` bodies, as mixins."""

from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .._base import is_valid_slug, resolve_safe_path
from ..validation import detect_base_class, validate_draft
from ._mixin import _agents_dir
from ._models import ActivateDraftRequest, SaveDraftRequest


class _StudioDraftsLegacyMixin:
    """Legacy GET / POST / DELETE of ``StudioDraftsHandler``."""

    async def _legacy_get(self):
        name = self.request.match_info.get("name")
        if name:
            return await self._get_one(name)
        return await self._get_all()

    async def _get_one(self, name: str):
        row = await self._get_draft_row(name)
        if row is None:
            return self._error(f"Draft '{name}' not found.", status=404, code="not_found")
        data = self._legacy_draft_view(await self._access(), row)
        draft_path = Path(row.file_path)
        data["source"] = draft_path.read_text() if draft_path.exists() else None
        return self.json_response(data)

    async def _get_all(self):
        rows = await self._get_all_draft_rows()
        access = await self._access()
        return self.json_response({"drafts": [self._legacy_draft_view(access, r) for r in rows], "count": len(rows)})

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

    async def _legacy_delete(self):
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


class _StudioDraftActivateLegacyMixin:
    """Legacy (Python draft) activation of ``StudioDraftActivateHandler``."""

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
        target_path = Path(_agents_dir()) / f"{name}.py"
        try:
            draft_path.replace(target_path)
        except OSError as exc:
            return self._error(f"Failed to move draft file: {exc}", status=500, code="move_failed")

        try:
            registry._import_module_from_path(target_path, base_dir=_agents_dir())
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
