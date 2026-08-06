"""CommCenterHandler — bulk notification sender, Jinja2 template CRUD, and
the placeholder catalog (spec §2, §3 Module 7).

An **instantiable** ``navigator.views.BaseHandler`` subclass registering
every CommCenter route via :meth:`setup`. The handler stays intentionally
thin: it owns auth, content-type dispatch, request/response models, and
HTTP error mapping. All rendering, validation, and publishing logic is
delegated to :mod:`parrot.services.comm_center` (Modules 4-6) — this
handler must never touch Jinja2, Redis, or pandas directly.

Route bodies owned by other tasks (``post_message`` — TASK-2161; the five
templates-CRUD methods — TASK-2160) are registered here as explicit
``NotImplementedError`` stubs so routing is complete end-to-end; those
tasks only need to fill in the method bodies.
"""
import base64
import uuid
from pathlib import Path
from typing import NoReturn

from aiohttp import web
from asyncdb import AsyncDB
from asyncdb.exceptions import NoDataFound
from datamodel.parsers.json import json_encoder
from navconfig.logging import logging
from navigator.views import BaseHandler
from navigator_auth.decorators import is_authenticated
from parrot.conf import default_dsn
from parrot.handlers.comm_center_placeholders import build_catalog
from parrot.handlers.models import NotificationBatchRecipient, NotificationTemplate
from parrot.services.comm_center.dispatch import (
    aggregate_batch_status,
    launch_fan_out,
)
from parrot.services.comm_center.dispatch import retry_batch as dispatch_retry_batch
from parrot.services.comm_center.ingest import (
    MAX_FILE_SIZE,
    FileTooLargeError,
    IngestionError,
    ingest_recipients,
)
from parrot.services.comm_center.models import SenderRequest, SenderResponse
from parrot.services.comm_center.render import RenderError, prepare


class TemplateNotFoundError(LookupError):
    """Raised when ``template_id``/``template_name``/``template_file`` resolve to nothing.

    A dedicated subclass rather than bare ``LookupError`` — Python's
    built-in ``KeyError``/``IndexError`` are themselves ``LookupError``
    subclasses, so mapping on bare ``LookupError`` in :meth:`CommCenterHandler._map_error`
    would silently turn an unrelated ``KeyError`` bug into a misleading
    ``404`` instead of surfacing it.
    """


def _get_db() -> AsyncDB:
    """Construct a fresh ``pg`` :class:`AsyncDB` wrapper for this handler.

    Mirrors the module-private helper in
    :mod:`parrot.services.comm_center.dispatch` — each module that needs a
    connection constructs its own, per the repo's ``AsyncDB('pg', dsn=...)``
    convention (see ``parrot.interfaces.hierarchy``).
    """
    return AsyncDB("pg", dsn=default_dsn)


def _as_bool(value) -> bool:
    """Coerce a query-string / form-field value to ``bool``.

    Args:
        value: A ``bool``, ``str``, ``None``, or any other value.

    Returns:
        ``True`` for ``True`` or a case-insensitive ``"true"``/``"1"``/
        ``"yes"`` string; ``False`` otherwise.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes")


class CommCenterHandler(BaseHandler):
    """Bulk notification sender + Jinja2 template CRUD + placeholder catalog.

    Method-based handler (mirrors ``ScrapingInfoHandler`` — every endpoint
    is a named ``async def (self, request) -> web.Response``, registered
    individually via :meth:`setup`, not aiohttp's ``web.View`` dispatch).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger("Parrot.CommCenterHandler")
        # Cached once — the catalog is static (spec §3 Module 3).
        self._placeholder_catalog = build_catalog()

    # ------------------------------------------------------------------
    # Sender (bulk) — spec §2 routes
    # ------------------------------------------------------------------

    async def _ingest_from_request(self, request: web.Request) -> tuple:
        """Normalize any of the three transports into recipients + request meta.

        Args:
            request: The incoming ``POST /sender`` request.

        Returns:
            ``(recipients, meta)`` — ``recipients`` is a
            ``list[RecipientIn]``; ``meta`` is a dict of the remaining
            request fields (``provider``, ``template*``, ``subject``,
            ``dry_run``), sourced from either the JSON body or the
            multipart form fields.

        Raises:
            IngestionError: The transport is missing required data, or the
                content type is unsupported.
            FileTooLargeError: The uploaded payload exceeds the size cap.
        """
        content_type = request.content_type
        if content_type == "multipart/form-data":
            files, form = await self.handle_upload(request)
            file_entries = None
            for entries in files.values():
                file_entries = entries
                break
            if not file_entries:
                raise IngestionError(
                    "multipart/form-data request must include an uploaded file"
                )
            recipients = await ingest_recipients(file_path=file_entries[0]["file_path"])
            return recipients, form

        if content_type == "application/json":
            body = await self.get_json(request) or {}
            if body.get("recipients") is not None:
                recipients = await ingest_recipients(rows=body["recipients"])
            elif body.get("file_b64"):
                recipients = await ingest_recipients(
                    file_bytes=base64.b64decode(body["file_b64"]),
                    filename=body.get("filename") or "upload.csv",
                )
            else:
                raise IngestionError(
                    "JSON request body must include 'recipients' or 'file_b64'"
                )
            return recipients, body

        raise IngestionError(f"Unsupported Content-Type: {content_type!r}")

    async def _resolve_template_source(self, meta: dict) -> tuple:
        """Resolve the template body from exactly one of the four sources.

        Args:
            meta: A :class:`SenderRequest` (or any object exposing the same
                ``template_id``/``template_name``/``template``/
                ``template_file`` attributes).

        Returns:
            ``(template_body, default_subject)`` — ``default_subject`` is
            only populated when resolving a stored template.

        Raises:
            ValueError: Not exactly one template source was given, or a
                resolved stored template is inactive.
            TemplateNotFoundError: ``template_id``/``template_name``/
                ``template_file`` did not match anything.
        """
        template_id = meta.template_id
        template_name = meta.template_name
        template = meta.template
        template_file = meta.template_file
        provided = [v for v in (template_id, template_name, template, template_file) if v]
        if len(provided) != 1:
            raise ValueError(
                "Exactly one of template_id, template_name, template, "
                "template_file must be provided"
            )

        if template:
            return template, None

        if template_file:
            try:
                from notify.conf import TEMPLATE_DIR
            except ImportError as exc:
                raise RuntimeError(
                    "async-notify is required for CommCenter. "
                    "Install with: pip install 'ai-parrot-server[comm-center]'"
                ) from exc
            path = Path(TEMPLATE_DIR) / template_file
            if not path.exists():
                raise TemplateNotFoundError(f"template_file not found: {template_file!r}")
            return path.read_text(), None

        db = _get_db()
        async with await db.connection() as conn:
            NotificationTemplate.Meta.connection = conn
            try:
                if template_id:
                    tpl = await NotificationTemplate.get(template_id=template_id)
                else:
                    tpl = await NotificationTemplate.get(name=template_name)
            except NoDataFound as exc:
                raise TemplateNotFoundError("Template not found") from exc
        if not tpl.is_active:
            raise ValueError(f"Template {tpl.name!r} is inactive")
        return tpl.template_string, tpl.subject

    def _map_error(self, exc: Exception) -> NoReturn:
        """Map a service-layer exception to the spec §2 Edge Cases status table.

        Raises the matching ``aiohttp.web.HTTPException`` directly rather
        than via ``BaseHandler.error()``. Verified live:
        ``BaseHandler.error()`` only recognizes a fixed status whitelist
        (400/401/403/404/406/412/428 — ``navigator/views/base.py:205-220``)
        and silently falls back to ``HTTPBadRequest`` (400) for anything
        else, which would otherwise turn every 413/503 this feature's spec
        requires into a misleading 400. Every ``web.HTTPException`` raised
        here is caught by aiohttp's own dispatch and converted into the
        response — this method never returns.

        Args:
            exc: The exception raised while processing the request.

        Raises:
            web.HTTPException: The status-mapped response.
        """
        body = json_encoder({"message": str(exc)})
        if isinstance(exc, FileTooLargeError):
            raise web.HTTPRequestEntityTooLarge(
                max_size=MAX_FILE_SIZE,
                actual_size=0,
                text=body,
                content_type="application/json",
            )
        if isinstance(exc, TemplateNotFoundError):
            raise web.HTTPNotFound(text=body, content_type="application/json")
        if isinstance(exc, RuntimeError):
            raise web.HTTPServiceUnavailable(text=body, content_type="application/json")
        if isinstance(exc, (IngestionError, RenderError, ValueError)):
            raise web.HTTPBadRequest(text=body, content_type="application/json")
        self.logger.error("Unhandled CommCenter error: %s", exc)
        raise web.HTTPBadRequest(text=body, content_type="application/json")

    @is_authenticated()
    async def post_sender(self, request: web.Request) -> web.Response:
        """``POST /api/v1/comm_center/sender`` — bulk notification send.

        Accepts recipients via any of three transports (inline JSON,
        ``multipart/form-data``, base64), resolves the template, renders
        and validates via :func:`prepare`, persists one tracking row per
        recipient, and backgrounds the fan-out. Returns ``202`` before any
        publishing has necessarily completed.
        """
        try:
            recipients, meta = await self._ingest_from_request(request)
            sender_request = SenderRequest(
                **{
                    key: value
                    for key, value in {
                        "provider": meta.get("provider"),
                        "template_id": meta.get("template_id"),
                        "template_name": meta.get("template_name"),
                        "template": meta.get("template"),
                        "template_file": meta.get("template_file"),
                        "subject": meta.get("subject"),
                        "dry_run": _as_bool(meta.get("dry_run")),
                    }.items()
                    if value is not None
                }
            )
            template_source, default_subject = await self._resolve_template_source(
                sender_request
            )
            subject = sender_request.subject or default_subject

            prepared = await prepare(
                recipients=recipients,
                provider=sender_request.provider,
                template_source=template_source,
                subject=subject,
            )
        except Exception as exc:  # noqa: BLE001 -- centralized error mapping
            return self._map_error(exc)

        batch_id = uuid.uuid4()
        payloads: list = []
        db = _get_db()
        async with await db.connection() as conn:
            NotificationBatchRecipient.Meta.connection = conn
            for msg in prepared.queued:
                row = NotificationBatchRecipient(
                    batch_id=batch_id,
                    row_number=msg.row_number,
                    provider=msg.payload.get("provider"),
                    recipient_name=msg.recipient.name,
                    recipient_address=(
                        msg.recipient.email or msg.recipient.phone or msg.recipient.address
                    ),
                    status="pending",
                    template_ref=template_source,
                    subject=subject,
                )
                await row.insert()
                payloads.append((row.id, msg.payload))
            for skip in prepared.skipped:
                row = NotificationBatchRecipient(
                    batch_id=batch_id,
                    row_number=skip.row,
                    provider=sender_request.provider,
                    status="skipped",
                    reason=skip.reason,
                )
                await row.insert()

        launch_fan_out(batch_id, payloads)

        response = SenderResponse(
            batch_id=batch_id,
            status="publishing",
            total=len(prepared.queued) + len(prepared.skipped),
            queued=len(prepared.queued),
            skipped=len(prepared.skipped),
            resolved_functions=prepared.resolved_functions,
            skipped_details=[{"row": s.row, "reason": s.reason} for s in prepared.skipped],
        )
        return self.json_response(response.to_dict(), dumps=json_encoder, status=202)

    @is_authenticated()
    async def get_batch(self, request: web.Request) -> web.Response:
        """``GET /api/v1/comm_center/sender/{batch_id}`` — batch progress.

        Query params: ``details`` (bool, default ``false``), ``status``
        (filter), ``limit`` (default 100, clamped to 1000), ``offset``.
        """
        batch_id = request.match_info["batch_id"]
        qs = self.query_parameters(request)
        result = await aggregate_batch_status(
            uuid.UUID(batch_id),
            details=_as_bool(qs.get("details")),
            status=qs.get("status"),
            limit=int(qs.get("limit", 100)),
            offset=int(qs.get("offset", 0)),
        )
        return self.json_response(result, dumps=json_encoder, status=200)

    @is_authenticated()
    async def retry_batch(self, request: web.Request) -> web.Response:
        """``POST /api/v1/comm_center/sender/{batch_id}/retry``.

        Query param: ``force`` (bool, default ``false``) — also
        re-publishes rows stuck in ``publishing``.

        Named ``retry_batch`` per spec §2 New Public Interfaces; the
        module-level function of the same name from
        :mod:`parrot.services.comm_center.dispatch` is imported aliased as
        ``dispatch_retry_batch`` purely for readability at the call site
        below — Python resolves the unqualified name via module globals,
        not the enclosing class, so there is no actual name collision.
        """
        batch_id = request.match_info["batch_id"]
        qs = self.query_parameters(request)
        result = await dispatch_retry_batch(
            uuid.UUID(batch_id), force=_as_bool(qs.get("force"))
        )
        return self.json_response(result, dumps=json_encoder, status=200)

    # ------------------------------------------------------------------
    # Placeholders (static catalog)
    # ------------------------------------------------------------------

    @is_authenticated()
    async def get_placeholders(self, request: web.Request) -> web.Response:
        """``GET /api/v1/comm_center/placeholders`` — the cached catalog."""
        return self.json_response(self._placeholder_catalog, dumps=json_encoder, status=200)

    # ------------------------------------------------------------------
    # Single-recipient send (TASK-2161) — stub
    # ------------------------------------------------------------------

    @is_authenticated()
    async def post_message(self, request: web.Request) -> web.Response:
        """``POST /api/v1/comm_center/message`` — single-recipient send.

        Stub — implemented by TASK-2161.
        """
        raise NotImplementedError("post_message is implemented by TASK-2161")

    # ------------------------------------------------------------------
    # Templates CRUD (TASK-2160) — stubs
    # ------------------------------------------------------------------

    @is_authenticated()
    async def list_templates(self, request: web.Request) -> web.Response:
        """``GET /api/v1/comm_center/templates``. Stub — TASK-2160."""
        raise NotImplementedError("list_templates is implemented by TASK-2160")

    @is_authenticated()
    async def get_template(self, request: web.Request) -> web.Response:
        """``GET /api/v1/comm_center/templates/{template_id}``. Stub — TASK-2160."""
        raise NotImplementedError("get_template is implemented by TASK-2160")

    @is_authenticated()
    async def create_template(self, request: web.Request) -> web.Response:
        """``POST /api/v1/comm_center/templates``. Stub — TASK-2160."""
        raise NotImplementedError("create_template is implemented by TASK-2160")

    @is_authenticated()
    async def update_template(self, request: web.Request) -> web.Response:
        """``PUT``/``PATCH /api/v1/comm_center/templates/{template_id}``. Stub — TASK-2160."""
        raise NotImplementedError("update_template is implemented by TASK-2160")

    @is_authenticated()
    async def delete_template(self, request: web.Request) -> web.Response:
        """``DELETE /api/v1/comm_center/templates/{template_id}``. Stub — TASK-2160."""
        raise NotImplementedError("delete_template is implemented by TASK-2160")

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def setup(self, app: web.Application) -> None:
        """Register every CommCenter route (spec §2). Repo convention, not inherited."""
        r = app.router
        r.add_route("POST", "/api/v1/comm_center/sender", self.post_sender)
        r.add_route("GET", "/api/v1/comm_center/sender/{batch_id}", self.get_batch)
        r.add_route(
            "POST",
            "/api/v1/comm_center/sender/{batch_id}/retry",
            self.retry_batch,
        )
        r.add_route("POST", "/api/v1/comm_center/message", self.post_message)
        r.add_route("GET", "/api/v1/comm_center/templates", self.list_templates)
        r.add_route(
            "GET", "/api/v1/comm_center/templates/{template_id}", self.get_template
        )
        r.add_route("POST", "/api/v1/comm_center/templates", self.create_template)
        r.add_route(
            "PUT", "/api/v1/comm_center/templates/{template_id}", self.update_template
        )
        r.add_route(
            "PATCH",
            "/api/v1/comm_center/templates/{template_id}",
            self.update_template,
        )
        r.add_route(
            "DELETE",
            "/api/v1/comm_center/templates/{template_id}",
            self.delete_template,
        )
        r.add_route("GET", "/api/v1/comm_center/placeholders", self.get_placeholders)
