"""FormDesigner read client (FEAT-734 M1): list, fetch and render forms over aiohttp."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote

import aiohttp
from pydantic import BaseModel, Field, ValidationError

from parrot_formdesigner.core.schema import FormSchema

MAX_RESPONSE_BYTES: int = 1_048_576


class FormDesignerError(Exception):
    """A FormDesigner read failed (HTTP status, timeout, oversize or malformed body)."""

    def __init__(self, message: str, *, status: int = 0) -> None:
        """Initialise the error with a message and optional HTTP status."""
        super().__init__(message)
        self.status = status


class FormDescriptor(BaseModel):
    """One row of GET {tp}/forms (handlers.py:851) — the picker's choice source."""

    form_uid: uuid.UUID
    form_id: str
    title: str
    description: str | None = None
    version: str | None = None
    source: str | None = None
    created_at: datetime | None = None


class RenderedCard(BaseModel):
    """`?with_meta=true` envelope (render.py:215-236), or the local render's equivalent."""

    content: dict[str, Any]
    content_type: str
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FormReader(Protocol):
    """Structural read surface shared by FormDesignerClient and LocalFormReader."""

    async def list_forms(self, *, tenant: str, bearer_token: str | None) -> list[FormDescriptor]: ...

    async def get_form(self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None) -> FormSchema: ...

    async def get_form_by_slug(self, *, tenant: str, slug: str, bearer_token: str | None) -> FormDescriptor | None: ...


def parse_form_ref(ref: str | uuid.UUID) -> uuid.UUID | str:
    """Return UUID-shaped references as UUIDs and all other references as slugs."""
    if isinstance(ref, uuid.UUID):
        return ref
    text = str(ref).strip()
    try:
        return uuid.UUID(text)
    except ValueError:
        return text


class FormDesignerClient:
    """Async read client for the FormDesigner REST surface (one lazily created session)."""

    def __init__(
        self,
        base_url: str,
        *,
        api_base_path: str = "/api/v1",
        timeout: float = 15.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialise the client with its public origin and optional shared session."""
        self.base_url = base_url.rstrip("/")
        self.api_base_path = "/" + api_base_path.strip("/") if api_base_path.strip("/") else ""
        self.timeout = timeout
        self._session = session
        self._owns_session = session is None
        self.logger = logging.getLogger(__name__)

    def _forms_url(self, tenant: str, *parts: str) -> str:
        """Build a safely quoted URL rooted at the tenant forms endpoint."""
        tail = "".join(f"/{quote(part, safe='')}" for part in parts)
        return f"{self.base_url}{self.api_base_path}/{quote(tenant, safe='')}/forms{tail}"

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the supplied or lazily-created aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def _request_json(
        self, url: str, *, bearer_token: str | None, params: dict[str, str] | None = None
    ) -> Any:
        """GET ``url`` and return a bounded, parsed JSON response for HTTP 200."""
        headers = {"Accept": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        session = await self._get_session()
        try:
            async with session.get(
                url,
                params=params,
                headers=headers,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = await response.content.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise FormDesignerError("response too large", status=response.status)
                if response.status != 200:
                    raise FormDesignerError(f"unexpected HTTP status {response.status}", status=response.status)
                try:
                    return json.loads(b"".join(chunks))
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise FormDesignerError("invalid JSON response", status=response.status) from exc
        except FormDesignerError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise FormDesignerError(type(exc).__name__) from exc

    @staticmethod
    def _coerce_localized(value: Any) -> str | None:
        """Convert server-localized string values into their display text."""
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, dict):
            localized = value.get("en")
            if localized is None:
                localized = next(iter(value.values()), None)
            return str(localized) if localized is not None else None
        return str(value)

    def _parse_descriptors(self, body: Any) -> list[FormDescriptor]:
        """Validate and convert a FormDesigner list response."""
        if not isinstance(body, dict) or not isinstance(body.get("forms"), list):
            raise FormDesignerError("malformed forms response", status=200)
        try:
            descriptors: list[FormDescriptor] = []
            for row in body["forms"]:
                if not isinstance(row, dict):
                    raise TypeError("form descriptor is not an object")
                descriptor = dict(row)
                descriptor["title"] = self._coerce_localized(descriptor.get("title"))
                descriptor["description"] = self._coerce_localized(descriptor.get("description"))
                descriptors.append(FormDescriptor.model_validate(descriptor))
            return descriptors
        except (TypeError, ValidationError) as exc:
            raise FormDesignerError("malformed form descriptor", status=200) from exc

    async def list_forms(self, *, tenant: str, bearer_token: str | None) -> list[FormDescriptor]:
        """GET ``{api}/{tenant}/forms`` and return its descriptors."""
        body = await self._request_json(self._forms_url(tenant), bearer_token=bearer_token)
        return self._parse_descriptors(body)

    async def get_form(self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None) -> FormSchema:
        """GET a full schema by its immutable form UUID."""
        body = await self._request_json(self._forms_url(tenant, str(form_uid)), bearer_token=bearer_token)
        try:
            return FormSchema.model_validate(body)
        except ValidationError as exc:
            raise FormDesignerError("malformed form response", status=200) from exc

    async def get_form_by_slug(self, *, tenant: str, slug: str, bearer_token: str | None) -> FormDescriptor | None:
        """GET the form matching ``slug``, or ``None`` when no such form exists."""
        body = await self._request_json(self._forms_url(tenant), bearer_token=bearer_token, params={"slug": slug})
        descriptors = self._parse_descriptors(body)
        return descriptors[0] if descriptors else None

    async def render_teams(
        self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None, section_index: int | None = None
    ) -> RenderedCard:
        """Render a form as a Teams card, optionally requesting one form section."""
        params = {"with_meta": "true"}
        if section_index is not None:
            params["section_index"] = str(section_index)
        body = await self._request_json(
            self._forms_url(tenant, str(form_uid), "render", "teams"), bearer_token=bearer_token, params=params
        )
        if not isinstance(body, dict) or body.get("content_encoding") == "base64" or not isinstance(body.get("content"), dict):
            raise FormDesignerError("malformed Teams card response", status=200)
        try:
            card = RenderedCard.model_validate(body)
        except ValidationError as exc:
            raise FormDesignerError("malformed Teams card response", status=200) from exc
        if section_index is not None:
            metadata = card.metadata
            if (
                metadata.get("section_index") != section_index
                or not isinstance(metadata.get("total_sections"), int)
                or not isinstance(metadata.get("form_version"), str)
            ):
                raise FormDesignerError("server does not support section rendering", status=200)
        return card

    async def close(self) -> None:
        """Close the session when this client owns it."""
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
