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

from ..core.schema import FormSchema, RenderedForm            # verified: schema.py:401, :671
from ..core.style import StyleSchema                          # verified: style.py:52
from .adaptive_card import AdaptiveCardRenderer               # verified: adaptive_card.py:121

logger = logging.getLogger(__name__)

ENVELOPE_KEY: str = "_formdesigner"
RESERVED_CONTROL_KEYS: frozenset[str] = frozenset({"_action", ENVELOPE_KEY})
PUBLIC_URL_ENV: str = "FORMDESIGNER_PUBLIC_URL"


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
        result = await super().render(form, style, locale=locale, prefilled=prefilled, errors=errors)
        env = self.build_envelope(form, resolved)
        result.metadata = {
            "channel": "msteams",
            "envelope": env.model_dump(mode="json"),
            "envelope_version": 1
        }
        return result

    def _submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]:
        """Terminal Submit -> {"_action": "submit", "_formdesigner": <envelope>}; otherwise the base default."""
        if not terminal or form is None or self._current_tenant is None:
            return super()._submit_action_data(form, terminal=terminal)
        env = self.build_envelope(form, self._current_tenant)
        return {"_action": "submit", ENVELOPE_KEY: env.model_dump(mode="json")}