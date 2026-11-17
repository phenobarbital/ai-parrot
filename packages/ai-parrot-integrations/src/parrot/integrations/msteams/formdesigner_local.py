"""In-process FormDesigner reader for mode="local" (FEAT-734): authorize, then FormRegistry + TeamsFormRenderer."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.renderers.adaptive_card import _resolve
from parrot_formdesigner.renderers.teams import TeamsFormRenderer

from .formdesigner_client import FormDescriptor, FormDesignerError, RenderedCard
from .formdesigner_identity import LocalFormAuthorizer


class LocalFormReader:
    """FormReader over an embedded FormRegistry; membership is checked before every registry call."""

    def __init__(
        self,
        registry: Any,
        *,
        authorizer: LocalFormAuthorizer | None,
        user_id_resolver: Callable[[], str | None],
        public_base_url: str | None,
        signing_secret: str | None,
        api_base_path: str = "/api/v1",
    ) -> None:
        """Store collaborators; nothing is read until a method passes ``_authorize``."""
        self._registry = registry
        self._authorizer = authorizer
        self._user_id_resolver = user_id_resolver
        self._public_base_url = public_base_url
        self._signing_secret = signing_secret
        self._api_base_path = api_base_path
        self.logger = logging.getLogger(__name__)

    async def _authorize(self, tenant: str, bearer_token: str | None) -> None:
        """Deny (403) unless the injected authorizer confirms membership for the resolved user."""
        user_id = self._user_id_resolver()
        if self._authorizer is None or not bearer_token or not user_id:
            raise FormDesignerError("access denied", status=403)
        try:
            await self._authorizer.require_membership(tenant=tenant, bearer_token=bearer_token, user_id=user_id)
        except Exception as exc:  # PermissionError, authority outage — all deny
            self.logger.info("local formdesigner: membership denied for tenant %s (%s)", tenant, type(exc).__name__)
            raise FormDesignerError("access denied", status=403) from exc

    @staticmethod
    def _descriptor(form: FormSchema) -> FormDescriptor:
        return FormDescriptor(
            form_uid=form.form_uid,
            form_id=form.form_id,
            title=_resolve(form.title, "en"),
            description=_resolve(form.description, "en") if form.description else None,
            version=form.published_version or form.version,
            source="memory",
        )

    async def list_forms(self, *, tenant: str, bearer_token: str | None) -> list[FormDescriptor]:
        """List the tenant's forms after the membership check."""
        await self._authorize(tenant, bearer_token)
        return [self._descriptor(f) for f in await self._registry.list_forms(tenant=tenant)]

    async def get_form(self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None) -> FormSchema:
        """Fetch one form by uid after the membership check; 404 when absent."""
        await self._authorize(tenant, bearer_token)
        form = await self._registry.get(form_uid, tenant=tenant)
        if form is None:
            raise FormDesignerError("form not found", status=404)
        return form

    async def get_form_by_slug(self, *, tenant: str, slug: str, bearer_token: str | None) -> FormDescriptor | None:
        """Resolve a slug to a descriptor after the membership check; ``None`` when absent."""
        await self._authorize(tenant, bearer_token)
        form = await self._registry.get_by_slug(slug, tenant=tenant)
        return self._descriptor(form) if form is not None else None

    async def render_teams(
        self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None, section_index: int | None = None
    ) -> RenderedCard:
        """Render with a fresh, signing TeamsFormRenderer; refuse when unsigned output would result."""
        if not self._signing_secret or not self._public_base_url:
            raise FormDesignerError("local mode requires formdesigner_signing_secret and public URL", status=500)
        form = await self.get_form(tenant=tenant, form_uid=form_uid, bearer_token=bearer_token)
        if section_index is not None and not 0 <= section_index < len(form.sections):
            raise FormDesignerError("section_index out of range", status=400)
        renderer = TeamsFormRenderer(
            self._public_base_url, api_base_path=self._api_base_path, signing_secret=self._signing_secret
        )
        try:
            if section_index is None:
                rendered = await renderer.render(form, tenant=tenant)
                metadata = dict(rendered.metadata or {})
            else:
                rendered = await renderer.render_section(
                    form, section_index, tenant=tenant, show_back=False, show_skip=False
                )
                metadata = {
                    **(rendered.metadata or {}),
                    "section_index": section_index,
                    "total_sections": len(form.sections),
                    "form_version": form.published_version or form.version,
                }
            metadata["envelope"] = renderer.build_envelope(form, tenant).model_dump(mode="json")
        except ValueError as exc:  # TeamsRenderConfigError
            raise FormDesignerError(str(exc), status=500) from exc
        return RenderedCard(
            content=rendered.content,
            content_type=rendered.content_type,
            warnings=[w.model_dump(mode="json") for w in rendered.warnings],
            metadata=metadata,
        )
