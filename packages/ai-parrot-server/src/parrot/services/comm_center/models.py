"""Request-side data models for the CommCenter recipient pipeline.

``RecipientIn`` is the single normalized shape every ingestion transport
(inline JSON, ``multipart/form-data``, base64) produces (spec §2 Data
Models, §3 Module 4). ``SkippedRow`` documents why a row never reached the
NotifyWorker stream (spec §5 — skipped rows must be reported, never
silently dropped).
"""
# ruff: noqa: UP045 -- `datamodel.BaseModel` field validation does not
# understand PEP 604 `X | None` unions (raises `TypeError: Expected type,
# got types.UnionType` at construction time); `typing.Optional[X]` is
# required here, verified live against this repo's installed `datamodel`
# package.
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
