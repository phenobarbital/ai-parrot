"""CommCenterHandler — bulk notification sender, Jinja2 template CRUD, and
the placeholder catalog (spec §2, §3 Module 7).

An **instantiable** ``navigator.views.BaseHandler`` subclass registering
every CommCenter route via :meth:`setup`. The handler stays intentionally
thin: it owns auth, content-type dispatch, request/response models, and
HTTP error mapping. All rendering, validation, and publishing logic is
delegated to :mod:`parrot.services.comm_center` (Modules 4-6) — this
handler must never touch Jinja2, Redis, or pandas directly.

Templates CRUD (``list_templates``/``get_template``/``create_template``/
``update_template``/``delete_template``) is hand-written on this same
class per spec §8 — not a ``ModelView`` — backed by the
``NotificationTemplate`` model (TASK-2153).

``post_message`` (spec G13 / Module 8) is a thin arity-1 caller over the
same shared :func:`~parrot.services.comm_center.render.prepare` the bulk
endpoint uses, publishing synchronously via
:func:`~parrot.services.comm_center.dispatch.publish_one` — no background
task for a single ``xadd``.
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
from navigator_session import get_session
from parrot.conf import PARROT_SCHEMA, default_dsn
from parrot.handlers.comm_center_placeholders import build_catalog
from parrot.handlers.models import NotificationBatchRecipient, NotificationTemplate
from parrot.services.comm_center.dispatch import (
    aggregate_batch_status,
    launch_fan_out,
    publish_one,
)
from parrot.services.comm_center.dispatch import retry_batch as dispatch_retry_batch
from parrot.services.comm_center.ingest import (
    MAX_FILE_SIZE,
    FileTooLargeError,
    IngestionError,
    ingest_recipients,
)
from parrot.services.comm_center.models import (
    RecipientIn,
    SenderRequest,
    SenderResponse,
    SingleMessageRequest,
    SingleMessageResponse,
)
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


def _looks_like_unique_violation(exc: Exception) -> bool:
    """Detect a Postgres unique-constraint violation from an insert error.

    Prefers a precise ``asyncpg.exceptions.UniqueViolationError`` check
    (verified live: this repo's ``pg`` driver is asyncpg-based) and falls
    back to a message-content heuristic in case ``asyncdb`` re-wraps the
    original exception into one of its own types.

    Args:
        exc: The exception raised by ``NotificationTemplate.insert()``.

    Returns:
        ``True`` if ``exc`` looks like a duplicate-``name`` violation.
    """
    try:
        import asyncpg.exceptions as pg_exceptions

        if isinstance(exc, pg_exceptions.UniqueViolationError):
            return True
    except ImportError:
        pass
    message = str(exc).lower()
    return "unique" in message or "duplicate key" in message


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
                raise IngestionError("multipart/form-data request must include an uploaded file")
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
                raise IngestionError("JSON request body must include 'recipients' or 'file_b64'")
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
            raise ValueError("Exactly one of template_id, template_name, template, " "template_file must be provided")

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
            template_source, default_subject = await self._resolve_template_source(sender_request)
            subject = sender_request.subject or default_subject

            prepared = await prepare(
                recipients=recipients,
                provider=sender_request.provider,
                template_source=template_source,
                subject=subject,
                dry_run=sender_request.dry_run,
            )
        except Exception as exc:  # noqa: BLE001 -- centralized error mapping
            return self._map_error(exc)

        if prepared.dry_run:
            # Spec §3 Module 9 / G14: stop before any xadd and before any
            # tracking write. No DB connection, no NotifyClient, no batch_id.
            self.logger.info("Dry run for /sender — publishing nothing")
            response = SenderResponse(
                batch_id=None,
                status="dry_run",
                total=len(prepared.queued) + len(prepared.skipped),
                queued=len(prepared.queued),
                skipped=len(prepared.skipped),
                resolved_functions=prepared.resolved_functions,
                skipped_details=[{"row": s.row, "reason": s.reason} for s in prepared.skipped],
                preview=prepared.preview,
            )
            return self.json_response(response.to_dict(), status=200)

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
                    recipient_address=(msg.recipient.email or msg.recipient.phone or msg.recipient.address),
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
        return self.json_response(response.to_dict(), status=202)

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
        return self.json_response(result, status=200)

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
        result = await dispatch_retry_batch(uuid.UUID(batch_id), force=_as_bool(qs.get("force")))
        return self.json_response(result, status=200)

    @is_authenticated()
    async def get_batches(self, request: web.Request) -> web.Response:
        """``GET /api/v1/comm_center/sender`` — paginated batch list (FEAT-445 TASK-2319).

        The tracking table (``navigator.notification_batch_recipients``) is
        flat — one row per recipient, ``batch_id`` repeated — so batch-level
        metadata (totals, timestamps, status breakdown) is derived by
        aggregation, mirroring :func:`aggregate_batch_status`'s single-batch
        query but grouped across every batch.

        Query params: ``limit`` (default 25, clamped to 100), ``offset``
        (default 0), ``status`` (batches with at least one row in this
        status), ``provider`` (batches with at least one row for this
        provider), ``created_after`` / ``created_before`` (batches with at
        least one row whose ``created_at`` falls in this ISO-8601 range).
        All four filters select whole *batches* via a
        ``batch_id IN (SELECT ...)`` predicate rather than filtering rows
        directly, so a matching batch's own aggregate counts always
        reflect every row in that batch — never just the rows that
        happened to match the filter (code-review fix: the date filters
        originally filtered rows before ``GROUP BY``, which could silently
        truncate a batch's own counts if its rows did not share an
        identical ``created_at``).
        """
        qs = self.query_parameters(request)
        limit = min(int(qs.get("limit", 25)), 100)
        offset = int(qs.get("offset", 0))
        status_filter = qs.get("status")
        provider_filter = qs.get("provider")
        created_after = qs.get("created_after")
        created_before = qs.get("created_before")

        table = f"{PARROT_SCHEMA}.{NotificationBatchRecipient.Meta.name}"
        where_clauses: list = []
        params: list = []

        if status_filter:
            params.append(status_filter)
            where_clauses.append(f"batch_id IN (SELECT batch_id FROM {table} WHERE status = ${len(params)})")
        if provider_filter:
            params.append(provider_filter)
            where_clauses.append(f"batch_id IN (SELECT batch_id FROM {table} WHERE provider = ${len(params)})")
        if created_after:
            # Batch-level, like status/provider above (not a row-level
            # predicate before GROUP BY): a batch's rows share one insert
            # transaction but are not guaranteed byte-identical created_at
            # values, so filtering rows directly here could truncate a
            # matching batch's own aggregate counts instead of
            # selecting/excluding it wholesale (code-review finding).
            params.append(created_after)
            where_clauses.append(f"batch_id IN (SELECT batch_id FROM {table} WHERE created_at >= ${len(params)})")
        if created_before:
            params.append(created_before)
            where_clauses.append(f"batch_id IN (SELECT batch_id FROM {table} WHERE created_at <= ${len(params)})")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        list_query = f"""
            SELECT batch_id,
                   MIN(created_at) AS created_at,
                   MIN(created_by) AS created_by,
                   MIN(template_ref) AS template_ref,
                   MIN(provider) AS provider,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'queued') AS queued,
                   COUNT(*) FILTER (WHERE status = 'skipped') AS skipped,
                   COUNT(*) FILTER (WHERE status = 'publish_failed') AS publish_failed,
                   COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                   COUNT(*) FILTER (WHERE status = 'publishing') AS publishing
            FROM {table}
            {where_sql}
            GROUP BY batch_id
            ORDER BY MIN(created_at) DESC
            LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """
        count_query = f"""
            SELECT COUNT(*) AS total FROM (
                SELECT batch_id FROM {table} {where_sql} GROUP BY batch_id
            ) sub
        """

        db = _get_db()
        async with await db.connection() as conn:
            # asyncdb's signature is fetchall(sentence, *args): a tuple counts as ONE
            # argument, so passing (*params, limit, offset) made every request fail with
            # "the server expects 2 arguments for this query, 1 was passed" before this
            # endpoint could ever return a 200. Splat them.
            rows = await conn.fetchall(list_query, *params, limit, offset)
            count_rows = await conn.fetchall(count_query, *params)
        total = count_rows[0]["total"] if count_rows else 0

        batches = [
            {
                "batch_id": str(row["batch_id"]),
                "created_at": (
                    row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"]
                ),
                "created_by": row["created_by"],
                "total": row["total"],
                "queued": row["queued"],
                "skipped": row["skipped"],
                "publish_failed": row["publish_failed"],
                "pending": row["pending"],
                "publishing": row["publishing"],
                "template_ref": row["template_ref"],
                "provider": row["provider"],
            }
            for row in (rows or [])
        ]
        return self.json_response(
            {"batches": batches, "total": total, "limit": limit, "offset": offset},
            status=200,
        )

    # ------------------------------------------------------------------
    # Placeholders (static catalog)
    # ------------------------------------------------------------------

    @is_authenticated()
    async def get_placeholders(self, request: web.Request) -> web.Response:
        """``GET /api/v1/comm_center/placeholders`` — the cached catalog."""
        return self.json_response(self._placeholder_catalog, status=200)

    # ------------------------------------------------------------------
    # Single-recipient send (spec G13 / Module 8)
    # ------------------------------------------------------------------

    @is_authenticated()
    async def post_message(self, request: web.Request) -> web.Response:
        """``POST /api/v1/comm_center/message`` — single-recipient send.

        A thin arity-1 caller over the shared :func:`prepare` — it does
        **not** re-implement template resolution, rendering, provider
        resolution, or validation (spec §2 "Shared-core requirement").
        Publishes synchronously via :func:`publish_one` (no background
        task — a single ``xadd`` does not justify one) and persists
        exactly one tracking row, so ``GET /sender/{batch_id}`` and
        ``POST /sender/{batch_id}/retry`` work identically for it.

        Deliberate divergence from the bulk endpoint (spec §3 Module 8):
        an invalid recipient or a publish failure returns an error status
        directly (``400``/``502``) instead of a `202` with a `skipped`/
        `publish_failed` row — with one recipient there is no "rest of the
        batch" to protect, so failing loudly is correct.
        """
        try:
            body = await self.get_json(request) or {}
            if not body.get("recipient"):
                raise ValueError("'recipient' is required")
            recipient = RecipientIn(**body["recipient"])

            message_request = SingleMessageRequest(
                **{
                    key: value
                    for key, value in {
                        "provider": body.get("provider"),
                        "recipient": recipient,
                        "template_id": body.get("template_id"),
                        "template_name": body.get("template_name"),
                        "template": body.get("template"),
                        "template_file": body.get("template_file"),
                        "subject": body.get("subject"),
                        "dry_run": _as_bool(body.get("dry_run")),
                    }.items()
                    if value is not None
                }
            )
            template_source, default_subject = await self._resolve_template_source(message_request)
            subject = message_request.subject or default_subject

            prepared = await prepare(
                recipients=[recipient],
                provider=message_request.provider,
                template_source=template_source,
                subject=subject,
                dry_run=message_request.dry_run,
            )
        except Exception as exc:  # noqa: BLE001 -- centralized error mapping
            return self._map_error(exc)

        if prepared.dry_run:
            # Spec §3 Module 9 / G14: stop before any xadd and before any
            # tracking write, on THIS endpoint too. Takes priority over the
            # divergent invalid-recipient 400 below -- dry-run reports the
            # skip as data, it does not error.
            self.logger.info("Dry run for /message — publishing nothing")
            reason = prepared.skipped[0].reason if prepared.skipped else None
            response = SingleMessageResponse(
                batch_id=None,
                message_id=None,
                status="dry_run",
                reason=reason,
                resolved_functions=prepared.resolved_functions,
                preview=prepared.preview,
            )
            return self.json_response(response.to_dict(), status=200)

        if prepared.skipped:
            # Deliberate divergence: 400 + reason, never 202/skipped (spec Module 8).
            raise web.HTTPBadRequest(
                text=json_encoder(
                    {
                        "reason": prepared.skipped[0].reason,
                        "resolved_functions": prepared.resolved_functions,
                    }
                ),
                content_type="application/json",
            )

        msg = prepared.queued[0]
        batch_id = uuid.uuid4()
        db = _get_db()
        async with await db.connection() as conn:
            NotificationBatchRecipient.Meta.connection = conn
            row = NotificationBatchRecipient(
                batch_id=batch_id,
                row_number=0,
                provider=msg.payload.get("provider"),
                recipient_name=recipient.name,
                recipient_address=(recipient.email or recipient.phone or recipient.address),
                status="pending",
                template_ref=template_source,
                subject=subject,
            )
            await row.insert()

        try:
            # dry_run is always False here (the dry-run branch above already
            # returned) -- passed through explicitly anyway so publish_one's
            # own defense-in-depth guard is exercised on this call site too,
            # not just relied upon implicitly.
            message_id = await publish_one(batch_id, msg.payload, row.id, dry_run=prepared.dry_run)
        except Exception as exc:
            raise web.HTTPBadGateway(
                text=json_encoder(
                    {
                        "batch_id": str(batch_id),
                        "status": "publish_failed",
                        "reason": str(exc),
                    }
                ),
                content_type="application/json",
            ) from exc

        response = SingleMessageResponse(
            batch_id=batch_id,
            message_id=message_id,
            status="queued",
            resolved_functions=prepared.resolved_functions,
        )
        return self.json_response(response.to_dict(), status=202)

    # ------------------------------------------------------------------
    # Templates CRUD (spec §8 — hand-written on this class, not a ModelView)
    # ------------------------------------------------------------------

    async def _get_user_id(self, request: web.Request) -> int | None:
        """Resolve the authenticated user's id from the request session.

        Mirrors ``handlers/bots.py:109``'s ``get_userid(session=self._session)``
        pattern; this handler is method-based (not ``ModelView``), so it has
        no ``self._session`` populated automatically and resolves the
        session directly from the method's own ``request`` instead.

        Args:
            request: The incoming request.

        Returns:
            The session's ``user_id``, or ``None`` if it cannot be resolved.
        """
        session = await get_session(request)
        return await self.get_userid(session=session)

    @is_authenticated()
    async def list_templates(self, request: web.Request) -> web.Response:
        """``GET /api/v1/comm_center/templates``.

        Optional filters: ``is_active`` (bool), ``tags`` (comma-separated,
        any-overlap match), ``name`` (case-insensitive substring match).
        """
        qs = self.query_parameters(request)
        db_filters = {}
        if "is_active" in qs:
            db_filters["is_active"] = _as_bool(qs["is_active"])

        db = _get_db()
        async with await db.connection() as conn:
            NotificationTemplate.Meta.connection = conn
            rows = await NotificationTemplate.filter(**db_filters) if db_filters else await NotificationTemplate.all()

        tags_filter = None
        if qs.get("tags"):
            tags_filter = {t.strip() for t in qs["tags"].split(",") if t.strip()}
        name_filter = qs.get("name")

        results = []
        for row in rows or []:
            if tags_filter and not (tags_filter & set(row.tags or [])):
                continue
            if name_filter and name_filter.lower() not in (row.name or "").lower():
                continue
            results.append(row.to_dict())

        return self.json_response({"templates": results}, status=200)

    @is_authenticated()
    async def get_template(self, request: web.Request) -> web.Response:
        """``GET /api/v1/comm_center/templates/{template_id}`` — one row, or 404."""
        template_id = request.match_info["template_id"]
        db = _get_db()
        async with await db.connection() as conn:
            NotificationTemplate.Meta.connection = conn
            try:
                tpl = await NotificationTemplate.get(template_id=uuid.UUID(template_id))
            except NoDataFound as exc:
                raise web.HTTPNotFound(
                    text=json_encoder({"message": "Template not found"}),
                    content_type="application/json",
                ) from exc
        return self.json_response(tpl.to_dict(), status=200)

    @is_authenticated()
    async def create_template(self, request: web.Request) -> web.Response:
        """``POST /api/v1/comm_center/templates`` — create; ``409`` on duplicate name."""
        body = await self.get_json(request) or {}
        if not body.get("name"):
            raise web.HTTPBadRequest(
                text=json_encoder({"message": "'name' is required"}),
                content_type="application/json",
            )
        if not body.get("template_string"):
            raise web.HTTPBadRequest(
                text=json_encoder({"message": "'template_string' is required"}),
                content_type="application/json",
            )

        user_id = await self._get_user_id(request)
        tpl = NotificationTemplate(
            name=body["name"],
            template_string=body["template_string"],
            subject=body.get("subject"),
            provider=body.get("provider"),
            description=body.get("description"),
            tags=body.get("tags") or [],
            is_active=body.get("is_active", True),
            created_by=user_id,
            updated_by=user_id,
        )

        db = _get_db()
        async with await db.connection() as conn:
            NotificationTemplate.Meta.connection = conn
            try:
                await tpl.insert()
            except Exception as exc:
                if _looks_like_unique_violation(exc):
                    raise web.HTTPConflict(
                        text=json_encoder({"message": f"Template name {body['name']!r} already exists"}),
                        content_type="application/json",
                    ) from exc
                raise

        return self.json_response(tpl.to_dict(), status=201)

    @is_authenticated()
    async def update_template(self, request: web.Request) -> web.Response:
        """``PUT``/``PATCH /api/v1/comm_center/templates/{template_id}``.

        ``PUT`` is treated as a full update, ``PATCH`` as partial — both
        are routed to this same method (spec §2 routes table). ``updated_at``
        is never set here; the DB trigger (TASK-2153's DDL) owns it.
        """
        template_id = request.match_info["template_id"]
        body = await self.get_json(request) or {}
        user_id = await self._get_user_id(request)

        db = _get_db()
        async with await db.connection() as conn:
            NotificationTemplate.Meta.connection = conn
            try:
                tpl = await NotificationTemplate.get(template_id=uuid.UUID(template_id))
            except NoDataFound as exc:
                raise web.HTTPNotFound(
                    text=json_encoder({"message": "Template not found"}),
                    content_type="application/json",
                ) from exc

            for field in (
                "name",
                "template_string",
                "subject",
                "provider",
                "description",
                "tags",
                "is_active",
            ):
                if field in body:
                    setattr(tpl, field, body[field])
            tpl.updated_by = user_id

            try:
                await tpl.update()
            except Exception as exc:
                if _looks_like_unique_violation(exc):
                    raise web.HTTPConflict(
                        text=json_encoder({"message": f"Template name {body.get('name')!r} already exists"}),
                        content_type="application/json",
                    ) from exc
                raise

        return self.json_response(tpl.to_dict(), status=200)

    @is_authenticated()
    async def delete_template(self, request: web.Request) -> web.Response:
        """``DELETE /api/v1/comm_center/templates/{template_id}`` — or 404."""
        template_id = request.match_info["template_id"]
        db = _get_db()
        async with await db.connection() as conn:
            NotificationTemplate.Meta.connection = conn
            try:
                tpl = await NotificationTemplate.get(template_id=uuid.UUID(template_id))
            except NoDataFound as exc:
                raise web.HTTPNotFound(
                    text=json_encoder({"message": "Template not found"}),
                    content_type="application/json",
                ) from exc
            await tpl.delete()
        return self.json_response(
            {"message": "Template deleted", "template_id": template_id},
            status=200,
        )

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def setup(self, app: web.Application) -> None:
        """Register every CommCenter route (spec §2). Repo convention, not inherited."""
        r = app.router
        r.add_route("POST", "/api/v1/comm_center/sender", self.post_sender)
        r.add_route("GET", "/api/v1/comm_center/sender", self.get_batches)
        r.add_route("GET", "/api/v1/comm_center/sender/{batch_id}", self.get_batch)
        r.add_route(
            "POST",
            "/api/v1/comm_center/sender/{batch_id}/retry",
            self.retry_batch,
        )
        r.add_route("POST", "/api/v1/comm_center/message", self.post_message)
        r.add_route("GET", "/api/v1/comm_center/templates", self.list_templates)
        r.add_route("GET", "/api/v1/comm_center/templates/{template_id}", self.get_template)
        r.add_route("POST", "/api/v1/comm_center/templates", self.create_template)
        r.add_route("PUT", "/api/v1/comm_center/templates/{template_id}", self.update_template)
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
