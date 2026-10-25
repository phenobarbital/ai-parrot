"""Bulk export of forms as A2UI surfaces / JSON Schema (FEAT-650, spec §3 M3).

The in-memory ``FormRegistry`` view is a cache: :meth:`A2UIExportService.export_tenant`
always hydrates from storage first (codex S7) and never crosses tenants.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic import BaseModel, Field

from ..core.schema import FormSchema
from ..renderers.base import AbstractFormRenderer
from .registry import FormRegistry

logger = logging.getLogger(__name__)


class ExportedSurface(BaseModel):
    """One exported form represented by one NDJSON line."""

    form_uid: str
    form_id: str
    version: str
    dialect: str
    envelope: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class A2UIExportService:
    """Export the forms of one tenant through a configured renderer."""

    def __init__(
        self,
        registry: FormRegistry,
        *,
        renderer: AbstractFormRenderer | None = None,
        dialect: str = "a2ui",
        locale: str = "en",
    ) -> None:
        """Initialize the export service.

        Args:
            registry: Tenant-scoped form registry.
            renderer: Renderer override. When omitted, resolve the requested dialect.
            dialect: Output dialect, either ``"a2ui"`` or ``"json_schema"``.
            locale: Locale forwarded to the renderer.

        Raises:
            RuntimeError: If the optional A2UI renderer is unavailable.
        """
        self.logger = logging.getLogger(__name__)
        self.registry = registry
        self.dialect = dialect
        self.locale = locale
        if renderer is None:
            from ..api.render import get_renderer

            if dialect == "json_schema":
                from ..renderers.jsonschema import JsonSchemaRenderer

                renderer = JsonSchemaRenderer()
            else:
                renderer = get_renderer("a2ui")
            if renderer is None:
                raise RuntimeError("A2UIExportService requires the 'ai-parrot' extra (no 'a2ui' renderer registered)")
        self.renderer = renderer

    async def export_form(self, form_uid: uuid.UUID, *, tenant: str) -> ExportedSurface:
        """Render one form, returning an error row for missing forms or failures.

        Args:
            form_uid: Immutable form identity.
            tenant: Tenant that owns the form.

        Returns:
            The rendered export row or an error row.
        """
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return ExportedSurface(
                form_uid=str(form_uid),
                form_id="",
                version="",
                dialect=self.dialect,
                error="not found",
            )
        return await self._render(form)

    async def export_tenant(
        self,
        tenant: str,
        *,
        form_uids: Sequence[uuid.UUID] | None = None,
        published_only: bool = False,
    ) -> AsyncIterator[ExportedSurface]:
        """Yield exports for one tenant after hydrating its storage cache.

        Args:
            tenant: Tenant whose forms are exported.
            form_uids: Optional allowlist of form identities.
            published_only: Whether to include only published forms.

        Yields:
            One export row per selected form.
        """
        if self.registry.storage is not None:
            await self.registry.load_from_storage(tenant=tenant)
        wanted = {str(form_uid) for form_uid in form_uids} if form_uids is not None else None
        for form in await self.registry.list_forms(tenant=tenant):
            if wanted is not None and str(form.form_uid) not in wanted:
                continue
            if published_only and form.published_version is None:
                continue
            yield await self._render(form)

    async def _render(self, form: FormSchema) -> ExportedSurface:
        """Render a form while isolating renderer failures.

        Args:
            form: Form to render.

        Returns:
            A successful export row or a row containing the renderer error.
        """
        base = {
            "form_uid": str(form.form_uid),
            "form_id": form.form_id,
            "version": form.version,
            "dialect": self.dialect,
        }
        try:
            rendered = await self.renderer.render(form, locale=self.locale)
        except Exception as exc:  # noqa: BLE001 - one failed form must not abort the export stream.
            self.logger.warning("export: render failed for %s: %s", form.form_uid, exc)
            return ExportedSurface(**base, error=str(exc))
        return ExportedSurface(
            **base,
            envelope=rendered.content,
            warnings=[warning.reason for warning in rendered.warnings],
        )
