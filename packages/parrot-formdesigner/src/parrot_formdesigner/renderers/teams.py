"""MS Teams renderer for FormSchema — Adaptive Card + ``_formdesigner`` submit envelope (FEAT-551).

The renderer returns JSON only. The Teams bot (ai-parrot-integrations) unwraps the envelope and
POSTs the answers to ``submit_url``; see docs/formdesigner-msteams-renderer.md.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

from ..core.file_envelope import UPLOAD_FIELD_TYPES           # verified: file_envelope.py:44-51
from ..core.schema import (                                   # verified: schema.py:401, :671, :195, :650
    FormField,
    FormSchema,
    FormSubsection,
    RenderedForm,
    RenderWarning,
)
from ..core.style import StyleSchema                          # verified: style.py:52
from .adaptive_card import AdaptiveCardRenderer, _AC_FALLBACK_TYPES, _resolve   # verified: adaptive_card.py:121, :95, :45

logger = logging.getLogger(__name__)

ENVELOPE_KEY: str = "_formdesigner"
RESERVED_CONTROL_KEYS: frozenset[str] = frozenset({"_action", ENVELOPE_KEY})
PUBLIC_URL_ENV: str = "FORMDESIGNER_PUBLIC_URL"

UPLOAD_NOTICE_TEXT: dict[str, str] = {
    "en": "Attachments can't be uploaded from Teams. Open the web form to add files.",
    "es": "No se pueden adjuntar archivos desde Teams. Abre el formulario web para agregarlos.",
}
UPLOAD_WARNING_REASON: str = "file/image upload unsupported in Teams cards — web form link rendered"
# FILE and IMAGE are NOT in `_AC_FALLBACK_TYPES`, so the base class's own warning loop
# never surfaces them; IMAGE_DROPZONE/MULTI_UPLOAD ARE in `_AC_FALLBACK_TYPES` and are
# already warned about by the base loop (with renderer=self.RENDERER_NAME == "teams"),
# so `_upload_warnings` only needs to cover the remainder to avoid double warnings.
_TEAMS_ONLY_UPLOAD_TYPES: frozenset = UPLOAD_FIELD_TYPES - _AC_FALLBACK_TYPES


class TeamsSubmitEnvelope(BaseModel):
    """Routing envelope carried in ``Action.Submit.data["_formdesigner"]`` (spec §2 Data Models)."""
    v: Literal[1] = 1
    wire: Literal["legacy"] = "legacy"
    form_uid: uuid.UUID
    tenant: str = Field(min_length=1)
    form_version: str
    is_public: bool
    submit_url: HttpUrl
    form_url: HttpUrl
    sig: str | None = None

    def canonical_payload(self) -> bytes:
        """Bytes that ``sign``/``verify`` cover: every field except ``sig``, sorted keys, compact separators."""
        return json.dumps(self.model_dump(mode="json", exclude={"sig"}), sort_keys=True, separators=(",", ":")).encode("utf-8")

    def sign(self, secret: str) -> "TeamsSubmitEnvelope":
        """Return a copy whose ``sig`` is the HMAC-SHA256 hex digest of ``canonical_payload()``."""
        digest = hmac.new(secret.encode("utf-8"), self.canonical_payload(), hashlib.sha256).hexdigest()
        return self.model_copy(update={"sig": digest})

    def verify(self, secret: str) -> bool:
        """Constant-time check of ``sig``; ``False`` when ``sig`` is ``None``."""
        if self.sig is None:
            return False
        expected = hmac.new(secret.encode("utf-8"), self.canonical_payload(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, self.sig)


class TeamsRenderConfigError(ValueError):
    """Raised when absolute URLs cannot be built (no public base URL or no tenant)."""


class TeamsFormRenderer(AdaptiveCardRenderer):
    """FormSchema -> MS Teams Adaptive Card whose terminal Submit carries a TeamsSubmitEnvelope."""
    RENDERER_NAME = "teams"
    accepts_tenant = True

    def __init__(self, public_base_url: str | None = None, *, api_base_path: str = "/api/v1",
                 ui_base_path: str = "", signing_secret: str | None = None, version: str | None = None) -> None:
        """``public_base_url`` falls back to env ``FORMDESIGNER_PUBLIC_URL``; trailing slashes are stripped."""
        super().__init__(version=version)
        self.public_base_url = (public_base_url or os.environ.get(PUBLIC_URL_ENV) or "").rstrip("/") or None
        self.api_base_path = api_base_path.rstrip("/")
        self.ui_base_path = ui_base_path.rstrip("/")
        self.signing_secret = signing_secret
        self._current_tenant: str | None = None
        self._current_form_url: str | None = None

    def build_envelope(self, form: FormSchema, tenant: str) -> TeamsSubmitEnvelope:
        """Compose submit_url/form_url from the configured base URL; raises TeamsRenderConfigError when unset."""
        if not self.public_base_url:
            raise TeamsRenderConfigError(f"{PUBLIC_URL_ENV} / public_base_url is not configured")
        env = TeamsSubmitEnvelope(
            form_uid=form.form_uid,
            tenant=tenant,
            form_version=form.published_version or form.version,
            is_public=form.is_public,
            submit_url=f"{self.public_base_url}{self.api_base_path}/{tenant}/forms/{form.form_uid}/data",
            form_url=f"{self.public_base_url}{self.ui_base_path}/{tenant}/forms/{form.form_uid}"
        )
        return env.sign(self.signing_secret) if self.signing_secret else env

    async def render(self, form: FormSchema, style: StyleSchema | None = None, *, locale: str = "en",
                     prefilled: dict[str, Any] | None = None, errors: dict[str, str] | None = None,
                     tenant: str | None = None) -> RenderedForm:
        """Render via the base class, then attach ``metadata`` with the envelope (spec §3 M1)."""
        resolved = tenant or form.tenant
        if not resolved:
            raise TeamsRenderConfigError("tenant is required (pass tenant= or set FormSchema.tenant)")
        self._current_tenant = resolved
        # Build the envelope BEFORE super().render() so _build_upload_element (called
        # synchronously inside the base builder) can read self._current_form_url.
        env = self.build_envelope(form, resolved)
        self._current_form_url = str(env.form_url)
        result = await super().render(form, style, locale=locale, prefilled=prefilled, errors=errors)
        result.warnings = [*result.warnings, *self._upload_warnings(form)]
        result.metadata = {
            "channel": "msteams",
            "envelope": env.model_dump(mode="json"),
            "envelope_version": 1
        }
        return result

    async def render_section(self, form: FormSchema, section_index: int, style: StyleSchema | None = None, *,
                             locale: str = "en", prefilled: dict[str, Any] | None = None,
                             errors: dict[str, str] | None = None, show_back: bool = False,
                             show_skip: bool = False, tenant: str | None = None) -> RenderedForm:
        """Render a wizard step via the base class; the terminal step's Submit carries the envelope.

        Mirrors ``render()``'s tenant-resolution pattern (spec §7): ``_current_tenant`` and
        ``_current_form_url`` are set immediately before delegating to the base builder so
        ``_submit_action_data``/``_build_upload_element`` can use them synchronously.
        """
        resolved = tenant or form.tenant
        if not resolved:
            raise TeamsRenderConfigError("tenant is required (pass tenant= or set FormSchema.tenant)")
        self._current_tenant = resolved
        self._current_form_url = str(self.build_envelope(form, resolved).form_url)
        return await super().render_section(
            form, section_index, style, locale=locale, prefilled=prefilled, errors=errors,
            show_back=show_back, show_skip=show_skip,
        )

    def _submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]:
        """Terminal Submit -> {"_action": "submit", "_formdesigner": <envelope>}; otherwise the base default."""
        if not terminal or form is None or self._current_tenant is None:
            return super()._submit_action_data(form, terminal=terminal)
        env = self.build_envelope(form, self._current_tenant)
        return {"_action": "submit", ENVELOPE_KEY: env.model_dump(mode="json")}

    def _build_upload_element(self, field: FormField, value: Any, locale: str) -> dict[str, Any] | None:
        """Teams cannot upload files: render a notice + Action.OpenUrl to the web form (spec §3 M2)."""
        lang = locale.split("-")[0]
        notice = UPLOAD_NOTICE_TEXT.get(lang, UPLOAD_NOTICE_TEXT["en"])
        title = _resolve(field.label, locale) or "Open web form"
        return {
            "type": "Container",
            "items": [
                {"type": "TextBlock", "text": notice, "isSubtle": True, "wrap": True, "size": "Small"},
                {"type": "ActionSet", "actions": [{"type": "Action.OpenUrl", "title": title, "url": self._current_form_url}]},
            ],
        }

    def _upload_warnings(self, form: FormSchema) -> list[RenderWarning]:
        """One warning per upload-type field not already covered by the base fallback loop.

        Walks sections and subsections the same way ``_build_section_body`` does. FILE and
        IMAGE are not in ``_AC_FALLBACK_TYPES``, so they need a warning here; IMAGE_DROPZONE
        and MULTI_UPLOAD are already warned about by the base class (renderer=self.RENDERER_NAME).
        """
        warnings: list[RenderWarning] = []
        for section in form.sections:
            for item in section.fields:
                fields = item.fields if isinstance(item, FormSubsection) else [item]
                for field in fields:
                    if field.field_type in _TEAMS_ONLY_UPLOAD_TYPES:
                        warnings.append(
                            RenderWarning(
                                field_id=field.field_id,
                                field_uid=field.field_uid,
                                field_type=field.field_type.value,
                                renderer=self.RENDERER_NAME,
                                reason=UPLOAD_WARNING_REASON,
                            )
                        )
        return warnings