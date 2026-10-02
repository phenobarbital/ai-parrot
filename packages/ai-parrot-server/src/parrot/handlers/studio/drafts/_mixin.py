"""Shared helpers of the draft-pipeline views (``_StudioDraftsMixin``)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from aiohttp import web
from asyncdb.exceptions import NoDataFound

from ...models.studio_drafts import StudioDraft
from ..access import _legacy_record, _store_record
from ..agents import _StudioAgentsMixin
from ..models import StudioError
from ._models import DRAFTS_SUBDIR


def _agents_dir() -> Path:
    """``AGENTS_DIR`` read from the package at call time (tests patch ``studio.drafts.AGENTS_DIR``)."""
    from parrot.handlers.studio import drafts as _drafts_pkg

    return _drafts_pkg.AGENTS_DIR


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
        d = Path(_agents_dir()) / DRAFTS_SUBDIR
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
    def _legacy_draft_view(access, row: StudioDraft) -> dict:
        """A legacy draft item plus the additive visibility fields (``access: "global"``, FEAT-605 AC3/AC10)."""
        rec = _legacy_record("draft", row.name, row.name, row.owner_user_id)
        return {**_StudioDraftsMixin._draft_to_dict(row), **access.visibility_fields(rec)}

    def _studio_draft_item_for(self, access, rec) -> dict:
        """The declarative-draft item with the visibility fields the caller's access decision yields (C14)."""
        item = self._studio_draft_item(rec)
        item.update(access.visibility_fields(_store_record("draft", rec.draft_id, rec)))
        return item

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
        """See ``handlers/studio/agents/_mixin.py::_StudioAgentsMixin._error`` —
        ``BaseHandler.error()`` only maps a fixed status whitelist and
        silently falls back to 400 for 409/422/503."""
        return self.json_response(
            StudioError(message=message, code=code).model_dump(),
            status=status,
        )
