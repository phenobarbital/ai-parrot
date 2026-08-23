"""Fan-out, status state machine, aggregation and retry (spec §3 Module 6).

This is the only module in CommCenter that talks to Redis. It publishes one
``xadd`` per recipient via ``NotifyClient.stream()``, drives the per-row
duplicate-delivery-containment state machine (spec §2), and provides batch
aggregation and retry over the flat ``NotificationBatchRecipient`` table.

``async-notify`` is lazy-imported (spec G11): importing this module never
requires it, and a clear, actionable error is raised only when a function
that actually needs it is called without the ``comm-center`` extra
installed.
"""

import asyncio
import importlib.metadata
import logging
import uuid
from datetime import UTC, datetime

from asyncdb import AsyncDB
from packaging.version import Version
from parrot.conf import PARROT_SCHEMA, default_dsn
from parrot.handlers.models import NotificationBatchRecipient

from .models import RecipientIn
from .render import (
    _CHANNEL_PROVIDERS,
    _EMAIL_PROVIDERS,
    _SMS_PROVIDERS,
    _TELEGRAM_PROVIDERS,
    build_wire_payload,
)

logger = logging.getLogger("Parrot.CommCenterDispatch")

#: Default page size for paginated batch details (spec §2 routes table).
DEFAULT_DETAILS_LIMIT = 100
#: Hard clamp on `limit`, regardless of what the caller asks for.
MAX_DETAILS_LIMIT = 1000

#: Statuses eligible for retry without `?force=true` (spec §2 state machine).
_RETRYABLE_STATUSES = ("pending", "publish_failed")
#: Never retried under any circumstances.
_TERMINAL_STATUSES = ("queued", "skipped")

#: Minimum async-notify version CommCenter requires (FEAT-445 TASK-2318).
#: async-notify < 1.6.0 silently ignores the inline Jinja2 ``template`` key
#: this module publishes in the xadd payload — it looks for a
#: ``template_file`` in ``TEMPLATE_DIR`` instead, finds none, and delivers
#: an empty body with no error on either side. async-notify 1.6.0 shipped
#: FEAT-003 ("Inline Jinja2 template source for send()"), the exact
#: capability CommCenter relies on.
MIN_ASYNC_NOTIFY_VERSION = "1.6.0"

#: Cached result of :func:`_check_async_notify_version` — set once the
#: installed version has been confirmed to satisfy the floor, so the check
#: runs at most once per process instead of on every request.
_ASYNC_NOTIFY_VERSION_OK: bool | None = None


def _check_async_notify_version() -> None:
    """Raise if the installed async-notify is older than the CommCenter floor.

    Sits immediately after the "is it installed at all" lazy-import guard
    in :func:`_get_notify_client` — an old-but-present async-notify would
    otherwise pass that check and then silently drop every template body
    (see :data:`MIN_ASYNC_NOTIFY_VERSION`). Cached after the first
    successful check so this does not re-run on every request.

    Raises:
        RuntimeError: The installed async-notify is older than
            :data:`MIN_ASYNC_NOTIFY_VERSION`.
    """
    global _ASYNC_NOTIFY_VERSION_OK
    if _ASYNC_NOTIFY_VERSION_OK:
        return
    installed = importlib.metadata.version("async-notify")
    if Version(installed) < Version(MIN_ASYNC_NOTIFY_VERSION):
        raise RuntimeError(
            f"CommCenter requires async-notify >= {MIN_ASYNC_NOTIFY_VERSION} for "
            f"inline Jinja2 template support (installed: {installed}). Upgrade "
            f"with: pip install 'async-notify>={MIN_ASYNC_NOTIFY_VERSION}'"
        )
    _ASYNC_NOTIFY_VERSION_OK = True


def _get_notify_client():
    """Lazily import and construct a ``NotifyClient`` (spec G11).

    Returns:
        A fresh, not-yet-connected ``NotifyClient``.

    Raises:
        RuntimeError: ``async-notify`` is not installed (actionable — names
            the ``comm-center`` extra), or it is installed but older than
            :data:`MIN_ASYNC_NOTIFY_VERSION`.
    """
    try:
        from notify.server import NotifyClient
    except ImportError as exc:
        raise RuntimeError(
            "async-notify is required for CommCenter. " "Install with: pip install 'ai-parrot-server[comm-center]'"
        ) from exc
    _check_async_notify_version()
    return NotifyClient()


def _notify_worker_stream() -> str:
    """Lazily read ``NOTIFY_WORKER_STREAM`` (spec G11 — no import at module load).

    Returns:
        The configured NotifyWorker Redis Stream name.

    Raises:
        RuntimeError: ``async-notify`` is not installed.
    """
    try:
        from notify.conf import NOTIFY_WORKER_STREAM
    except ImportError as exc:
        raise RuntimeError(
            "async-notify is required for CommCenter. " "Install with: pip install 'ai-parrot-server[comm-center]'"
        ) from exc
    return NOTIFY_WORKER_STREAM


def _get_db() -> AsyncDB:
    """Construct a fresh ``pg`` :class:`AsyncDB` wrapper for the batch table."""
    return AsyncDB("pg", dsn=default_dsn)


async def publish_one(
    batch_id: uuid.UUID,
    payload: dict,
    row_id: uuid.UUID,
    *,
    client=None,
    dry_run: bool = False,
) -> str | None:
    """Publish a single recipient, driving the row status state machine.

    Writes ``publishing`` **before** calling ``client.stream()`` (the
    pre-``xadd`` marker that narrows duplicate-delivery risk to rows caught
    mid-call — spec §2), then ``queued`` + ``published_at`` on success or
    ``publish_failed`` + ``reason`` on failure. ``attempts`` is incremented
    on every attempt, success or failure.

    Args:
        batch_id: The batch this row belongs to.
        payload: The wire payload to publish (from :func:`build_wire_payload`).
        row_id: The :class:`NotificationBatchRecipient` id to update.
        client: An already-connected ``NotifyClient`` to reuse — :func:`fan_out`
            passes one so a whole batch shares a single Redis connection.
            When omitted, a client is created and closed here, which is
            what makes this function directly reusable by the
            single-recipient endpoint (TASK-2161) without any batch
            machinery.
        dry_run: Defense-in-depth guard (spec §3 Module 9 — the dry-run
            guard "must be enforced at the service layer, not only in the
            handler, so no future caller of CommCenterService can bypass
            it"). The real handler already never reaches this with
            ``dry_run=True`` (both send endpoints short-circuit before
            ever calling ``publish_one``/``fan_out``); this parameter
            exists so a caller building a ``PreparedBatch`` directly and
            passing one of its payloads to ``publish_one`` cannot publish
            it either. Mirrors the equivalent guard in :func:`fan_out`.

    Returns:
        The Redis stream entry id returned by ``client.stream()``. Verified
        live: today's ``NotifyClient.stream()`` does not return one (always
        ``None``) — ``published_at`` is the authoritative "this succeeded"
        marker, not ``message_id``.

    Raises:
        RuntimeError: ``async-notify`` is not installed, or ``dry_run`` is
            ``True``.
        Exception: Whatever ``client.stream()`` raised, re-raised after the
            row has been marked ``publish_failed`` — so :func:`fan_out` can
            catch it and continue with the rest of the batch, and the
            single-recipient endpoint can map it to ``502``.
    """
    if dry_run:
        raise RuntimeError("Refusing to publish a dry-run batch")

    own_client = client is None
    if own_client:
        client = _get_notify_client()
        await client.connect()

    stream_name = _notify_worker_stream()
    db = _get_db()
    try:
        async with await db.connection() as conn:
            NotificationBatchRecipient.Meta.connection = conn
            row = await NotificationBatchRecipient.get(id=row_id)
            row.status = "publishing"
            row.attempts = (row.attempts or 0) + 1
            await row.update()
            logger.debug(
                "Batch %s row %s: status=publishing (attempt %s)",
                batch_id,
                row_id,
                row.attempts,
            )

            try:
                message_id = await client.stream(payload, stream_name, use_wrapper=False)
            except Exception as exc:
                row.status = "publish_failed"
                row.reason = str(exc)
                await row.update()
                logger.warning("Batch %s row %s: publish_failed (%s)", batch_id, row_id, exc)
                raise

            row.status = "queued"
            row.published_at = datetime.now(UTC)
            row.message_id = message_id
            await row.update()
            logger.debug("Batch %s row %s: status=queued", batch_id, row_id)
            return message_id
    finally:
        if own_client:
            await client.close()


async def fan_out(batch_id: uuid.UUID, payloads: list) -> None:
    """Publish every recipient in a batch, never aborting on one failure.

    Reuses a single ``NotifyClient`` connection for the whole batch
    (connect once, close in ``finally`` — spec Key Constraints).

    Also accepts a ``PreparedBatch`` directly in place of ``payloads`` —
    defense in depth for dry-run (spec §3 Module 9): duck-typed via a
    ``dry_run`` attribute, since importing
    :class:`~parrot.services.comm_center.models.PreparedBatch` here would
    be a needless coupling for what is otherwise a plain list of tuples.
    A batch prepared with ``dry_run=True`` is refused unconditionally —
    the real handler already never reaches this (TASK-2159/2161 skip
    fan-out/``publish_one`` entirely for a dry run), but a future caller
    of this service bypassing the handler must not be able to publish one
    either.

    Args:
        batch_id: The batch these payloads belong to.
        payloads: ``(row_id, payload)`` pairs — the already-persisted
            :class:`NotificationBatchRecipient` id and its wire payload
            from :func:`build_wire_payload` — or a ``PreparedBatch``.

    Raises:
        RuntimeError: ``payloads`` is a ``PreparedBatch`` with
            ``dry_run=True``.
    """
    if hasattr(payloads, "dry_run"):
        prepared_batch = payloads
        if prepared_batch.dry_run:
            raise RuntimeError("Refusing to publish a dry-run batch")
        payloads = [(msg.row_number, msg.payload) for msg in prepared_batch.queued]

    client = _get_notify_client()
    await client.connect()
    try:
        for row_id, payload in payloads:
            try:
                await publish_one(batch_id, payload, row_id, client=client)
            except Exception as exc:  # noqa: BLE001 -- one row must never abort the batch
                logger.warning(
                    "Batch %s row %s: publish failed, continuing batch (%s)",
                    batch_id,
                    row_id,
                    exc,
                )
                continue
    finally:
        await client.close()


async def _finalize_batch(batch_id: uuid.UUID, task, attempted_ids: set) -> None:
    """Done-callback body: log any ``fan_out`` exception and un-strand rows.

    A bare ``asyncio.create_task`` swallows exceptions and can leave a
    batch stuck in ``publishing`` if the task itself crashes outside
    :func:`fan_out`'s own per-row try/except. This defensively marks any
    row still ``publishing`` **that this fan-out actually attempted** as
    ``publish_failed`` so it becomes retry-eligible instead of stranded
    forever.

    Scoping to ``attempted_ids`` is what keeps the spec's duplicate
    containment intact: a ``force=False`` :func:`retry_batch` deliberately
    leaves pre-existing ``publishing`` rows alone and reports them as
    ``ambiguous``. Sweeping the whole batch here would flip those to
    ``publish_failed``, making the *next* retry re-publish them silently —
    exactly the duplicate send the pre-``xadd`` marker exists to prevent.

    Args:
        batch_id: The batch that just finished fanning out.
        task: The completed ``fan_out`` :class:`asyncio.Task`.
        attempted_ids: Row ids this fan-out was given. Rows outside this
            set are never touched, however long they have been
            ``publishing``.
    """
    if not task.cancelled():
        exc = task.exception()
        if exc:
            logger.error("fan_out raised for batch %s: %s", batch_id, exc)

    if not attempted_ids:
        return

    db = _get_db()
    async with await db.connection() as conn:
        NotificationBatchRecipient.Meta.connection = conn
        stranded = await NotificationBatchRecipient.filter(batch_id=batch_id, status="publishing")
        for row in stranded or []:
            if row.id not in attempted_ids:
                continue
            row.status = "publish_failed"
            row.reason = "Batch finalized while row was still publishing (possible crash)"
            await row.update()
            logger.warning(
                "Batch %s row %s: un-stranded from publishing -> publish_failed",
                batch_id,
                row.id,
            )


def launch_fan_out(batch_id: uuid.UUID, payloads: list):
    """Launch :func:`fan_out` as a background task with a finalizing done-callback.

    Args:
        batch_id: The batch to fan out.
        payloads: ``(row_id, payload)`` pairs, see :func:`fan_out`.

    Returns:
        The scheduled ``asyncio.Task`` running :func:`fan_out`.
    """
    attempted_ids = {row_id for row_id, _ in payloads}
    task = asyncio.create_task(fan_out(batch_id, payloads))
    task.add_done_callback(lambda t: asyncio.create_task(_finalize_batch(batch_id, t, attempted_ids)))
    return task


async def aggregate_batch_status(
    batch_id: uuid.UUID,
    *,
    details: bool = False,
    status: str | None = None,
    limit: int = DEFAULT_DETAILS_LIMIT,
    offset: int = 0,
) -> dict:
    """Aggregate a batch's progress from the flat tracking table.

    Args:
        batch_id: The batch to summarize.
        details: When ``True``, also return paginated per-recipient rows.
        status: Optional status filter, only applied to ``details`` rows.
        limit: Page size for ``details`` rows, clamped to
            :data:`MAX_DETAILS_LIMIT`.
        offset: Page offset for ``details`` rows.

    Returns:
        ``{"batch_id", "total", "by_status", "rows"}`` — ``rows`` is
        ``None`` unless ``details=True``.
    """
    limit = min(limit, MAX_DETAILS_LIMIT)
    db = _get_db()
    async with await db.connection() as conn:
        table = f"{PARROT_SCHEMA}.{NotificationBatchRecipient.Meta.name}"
        query = f"SELECT status, COUNT(*) AS count FROM {table} WHERE batch_id = $1 GROUP BY status"
        counts = await conn.fetchall(query, (batch_id,))
        by_status = {row["status"]: row["count"] for row in (counts or [])}

        result = {
            "batch_id": batch_id,
            "total": sum(by_status.values()),
            "by_status": by_status,
            "rows": None,
        }

        if details:
            NotificationBatchRecipient.Meta.connection = conn
            filters = {"batch_id": batch_id}
            if status:
                filters["status"] = status
            rows = await NotificationBatchRecipient.filter(**filters)
            result["rows"] = (rows or [])[offset : offset + limit]

        return result


def _rebuild_payload(row: NotificationBatchRecipient) -> dict:
    """Best-effort payload reconstruction for a retry.

    KNOWN LIMITATION (flagged for a follow-up spec/schema amendment, out
    of this task's file scope — the table belongs to TASK-2154's
    ``handlers/models/notification_batches.py``): ``NotificationBatchRecipient``
    stores a single ``recipient_address`` column and a ``template_ref``
    identifier, not the full rendered template body or a multi-field
    contact blob. Consequences:

    - ``teams`` rows cannot be fully reconstructed — both ``team_id`` AND
      ``channel_id`` are required, but only one column is available. The
      rebuilt recipient will legitimately fail contact-field validation
      again on retry. This is a *safe* failure mode (it is reported, never
      silently sent to the wrong channel), not data corruption.
    - ``template_ref`` is treated as the literal template body on retry.
      This is only correct when the original request used an inline
      template string; for a stored/named/file template, ``template_ref``
      is actually just an identifier, not the rendered body. A future
      schema addition (e.g. a ``rendered_template`` column) would make
      retry fully faithful.

    Args:
        row: The tracking row to rebuild a wire payload for.

    Returns:
        The best-effort wire payload, ready to pass to :func:`publish_one`.
    """
    extra: dict = {}
    email = None
    phone = None
    if row.provider in _EMAIL_PROVIDERS:
        email = row.recipient_address
    elif row.provider in _SMS_PROVIDERS:
        phone = row.recipient_address
    elif row.provider in _TELEGRAM_PROVIDERS:
        extra["chat_id"] = row.recipient_address
    elif row.provider in _CHANNEL_PROVIDERS:
        extra["channel_id"] = row.recipient_address
    # teams: intentionally left without team_id/channel_id -- see docstring.

    recipient = RecipientIn(
        name=row.recipient_name or "",
        email=email,
        phone=phone,
        extra=extra,
    )
    rendered_template = row.template_ref or ""
    return build_wire_payload(recipient, row.provider, rendered_template, row.subject)


async def retry_batch(batch_id: uuid.UUID, *, force: bool = False) -> dict:
    """Re-publish retry-eligible rows for a batch (spec §2 state machine).

    Re-publishes ``pending`` and ``publish_failed`` rows; never ``queued``
    or ``skipped``. ``publishing`` rows are only included when
    ``force=True`` — otherwise they are reported as ``ambiguous`` and left
    untouched (they may already have been published; retrying them without
    ``force`` risks a duplicate send).

    Args:
        batch_id: The batch to retry.
        force: When ``True``, also re-publish rows stuck in ``publishing``.

    Returns:
        ``{"retried": <n>, "ambiguous": <n>}``. Row *selection* (which
        rows qualify) has already happened by the time this returns, but
        the actual re-publishing is backgrounded via :func:`launch_fan_out`
        — a batch stranded with thousands of retryable rows after an
        outage must not block the HTTP response (and risk a client/gateway
        timeout) while they are sequentially re-published, mirroring how
        the initial send already backgrounds its own fan-out.
    """
    retry_statuses = list(_RETRYABLE_STATUSES)
    if force:
        retry_statuses.append("publishing")

    db = _get_db()
    async with await db.connection() as conn:
        NotificationBatchRecipient.Meta.connection = conn
        to_retry: list = []
        for st in retry_statuses:
            rows = await NotificationBatchRecipient.filter(batch_id=batch_id, status=st)
            to_retry.extend(rows or [])

        ambiguous = 0
        if not force:
            still_publishing = await NotificationBatchRecipient.filter(batch_id=batch_id, status="publishing")
            ambiguous = len(still_publishing or [])

    payloads = [(row.id, _rebuild_payload(row)) for row in to_retry]
    launch_fan_out(batch_id, payloads)
    return {"retried": len(to_retry), "ambiguous": ambiguous}
