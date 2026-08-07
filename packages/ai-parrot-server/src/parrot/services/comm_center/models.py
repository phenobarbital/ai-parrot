"""Request-side data models for the CommCenter recipient pipeline.

``RecipientIn`` is the single normalized shape every ingestion transport
(inline JSON, ``multipart/form-data``, base64) produces (spec §2 Data
Models, §3 Module 4). ``SkippedRow`` documents why a row never reached the
NotifyWorker stream (spec §5 — skipped rows must be reported, never
silently dropped). ``SenderRequest``/``SenderResponse`` are the
``POST /sender`` bulk-send request/response bodies (TASK-2159).
"""
# ruff: noqa: UP045 -- `datamodel.BaseModel` field validation does not
# understand PEP 604 `X | None` unions (raises `TypeError: Expected type,
# got types.UnionType` at construction time); `typing.Optional[X]` is
# required here, verified live against this repo's installed `datamodel`
# package.
import uuid
from typing import Optional

from datamodel import BaseModel, Field


class RecipientIn(BaseModel):
    """One normalized recipient row from JSON, Excel, or CSV.

    Extra columns beyond the canonical five (``name``, ``username``,
    ``email``, ``phone``, ``address``) are preserved verbatim in ``extra``
    and forwarded as pass-2 render kwargs (spec §3 Module 3/4).
    """

    name: str = Field(required=True)
    username: Optional[str] = Field(required=False, default=None)
    email: Optional[str] = Field(required=False, default=None)
    phone: Optional[str] = Field(required=False, default=None)
    address: Optional[str] = Field(required=False, default=None)
    provider: Optional[str] = Field(required=False, default=None)
    extra: dict = Field(required=False, default_factory=dict)


class SkippedRow(BaseModel):
    """A recipient row excluded from the send, with the reason why.

    Reported back to the caller (spec §5) — the batch proceeds with the
    remaining rows rather than aborting.
    """

    row: int = Field(required=True)
    reason: str = Field(required=True)


class PreparedMessage(BaseModel):
    """One recipient that passed validation, with its finished wire payload.

    ``payload`` is exactly what :func:`parrot.services.comm_center.dispatch`
    (TASK-2158) will ``xadd`` unchanged — this is the last step ``prepare()``
    performs before any publishing would happen.
    """

    recipient: RecipientIn = Field(required=True)
    payload: dict = Field(required=False, default_factory=dict)
    row_number: Optional[int] = Field(required=False, default=None)


class PreparedBatch(BaseModel):
    """Result of ``CommCenterService.prepare()`` — no I/O has happened yet.

    Everything up to (not including) publishing: the resolved computed
    functions, the partially-rendered template, and the split between
    recipients ready to publish (``queued``) and those excluded
    (``skipped``). This is the only shape ``dry_run`` (TASK-2162) ever
    returns to the caller.
    """

    resolved_functions: dict = Field(required=False, default_factory=dict)
    template: Optional[str] = Field(required=False, default=None)
    subject: Optional[str] = Field(required=False, default=None)
    queued: list = Field(required=False, default_factory=list)
    skipped: list = Field(required=False, default_factory=list)
    dry_run: bool = Field(required=False, default=False)
    preview: Optional[str] = Field(required=False, default=None)


class SenderRequest(BaseModel):
    """``POST /sender`` request body — the bulk-send endpoint (spec §2).

    Exactly one of ``template_id``, ``template_name``, ``template``, or
    ``template_file`` must be provided; exactly one of ``recipients``
    (inline JSON) or ``file_b64`` must be provided when the transport is
    JSON (multipart uploads carry recipients as a file part instead, never
    through this model).
    """

    provider: str = Field(required=True)
    template_id: Optional[uuid.UUID] = Field(required=False, default=None)
    template_name: Optional[str] = Field(required=False, default=None)
    template: Optional[str] = Field(required=False, default=None)
    template_file: Optional[str] = Field(required=False, default=None)
    subject: Optional[str] = Field(required=False, default=None)
    recipients: Optional[list] = Field(required=False, default=None)
    file_b64: Optional[str] = Field(required=False, default=None)
    filename: Optional[str] = Field(required=False, default=None)
    dry_run: bool = Field(required=False, default=False)


class SenderResponse(BaseModel):
    """``POST /sender`` response body (spec §2, §5 acceptance criteria)."""

    batch_id: Optional[uuid.UUID] = Field(required=False, default=None)
    status: str = Field(required=True)
    total: int = Field(required=True)
    queued: int = Field(required=True)
    skipped: int = Field(required=True)
    resolved_functions: dict = Field(required=False, default_factory=dict)
    skipped_details: list = Field(required=False, default_factory=list)
    preview: Optional[str] = Field(required=False, default=None)


class SingleMessageRequest(BaseModel):
    """``POST /message`` request body — one recipient, one provider (spec G13).

    ``provider`` is **required and explicit** — unlike ``SenderRequest``,
    there is exactly one recipient, so there is no per-record override to
    resolve. Exactly one of ``template_id``/``template_name``/``template``/
    ``template_file`` must be provided, same resolution as the bulk
    endpoint.
    """

    provider: str = Field(required=True)
    recipient: RecipientIn = Field(required=True)
    template_id: Optional[uuid.UUID] = Field(required=False, default=None)
    template_name: Optional[str] = Field(required=False, default=None)
    template: Optional[str] = Field(required=False, default=None)
    template_file: Optional[str] = Field(required=False, default=None)
    subject: Optional[str] = Field(required=False, default=None)
    dry_run: bool = Field(required=False, default=False)


class SingleMessageResponse(BaseModel):
    """``POST /message`` response body (spec §2, G13).

    ``status`` is one of ``queued``/``publish_failed``/``skipped``/
    ``dry_run``; ``reason`` is populated for ``skipped``/``publish_failed``.
    """

    batch_id: Optional[uuid.UUID] = Field(required=False, default=None)
    message_id: Optional[str] = Field(required=False, default=None)
    status: str = Field(required=True)
    reason: Optional[str] = Field(required=False, default=None)
    resolved_functions: dict = Field(required=False, default_factory=dict)
    preview: Optional[str] = Field(required=False, default=None)
