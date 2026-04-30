"""Pydantic input schemas for OdooToolkit tool methods.

Each tool method on :class:`~parrot_tools.odoo.toolkit.OdooToolkit` is
decorated with ``@tool_schema(<InputModel>)`` so the LLM gets a precise
JSON schema for the arguments it can pass.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Odoo domain triplets are runtime-typed; we keep them as a plain list[Any]
# rather than a strict tuple schema so the LLM can pass them naturally.
OdooDomain = list[Any]


class _OdooBaseInput(BaseModel):
    """Base input model — forbids extra args so typos surface early."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())


# ── Discovery ───────────────────────────────────────────────────────────────


class FieldsGetInput(_OdooBaseInput):
    model: str = Field(..., description="Odoo model technical name, e.g. 'res.partner'")
    attributes: Optional[list[str]] = Field(
        default=None,
        description="Field-attribute names to include (e.g. ['string','type','required'])",
    )


# ── Generic CRUD ────────────────────────────────────────────────────────────


class SearchRecordsInput(_OdooBaseInput):
    model: str = Field(..., description="Odoo model technical name")
    domain: Optional[OdooDomain] = Field(
        default=None,
        description="Odoo domain filter, e.g. [('is_company','=',True)]. Empty = all records.",
    )
    fields: Optional[list[str]] = Field(
        default=None, description="Field names to return. Default = all fields."
    )
    limit: int = Field(default=100, ge=1, le=10000, description="Max records to return")
    offset: int = Field(default=0, ge=0, description="Records to skip (pagination)")
    order: Optional[str] = Field(default=None, description="Sort order, e.g. 'name asc'")


class GetRecordInput(_OdooBaseInput):
    model: str
    record_id: int = Field(..., ge=1)
    fields: Optional[list[str]] = None


class CreateRecordInput(_OdooBaseInput):
    model: str
    values: dict[str, Any] = Field(..., description="Field values for the new record")


class CreateRecordsInput(_OdooBaseInput):
    model: str
    vals_list: list[dict[str, Any]] = Field(
        ..., min_length=1, max_length=1000, description="List of value dicts (≤ 1000)"
    )


class UpdateRecordInput(_OdooBaseInput):
    model: str
    record_id: int = Field(..., ge=1)
    values: dict[str, Any]


class UpdateRecordsInput(_OdooBaseInput):
    model: str
    record_ids: list[int] = Field(..., min_length=1, max_length=1000)
    values: dict[str, Any]


class DeleteRecordInput(_OdooBaseInput):
    model: str
    record_id: int = Field(..., ge=1)


class DeleteRecordsInput(_OdooBaseInput):
    model: str
    record_ids: list[int] = Field(..., min_length=1, max_length=1000)


class ImportRecordsInput(_OdooBaseInput):
    """Idempotent upsert via Odoo's ``load`` (supports external IDs)."""

    model: str
    fields: list[str] = Field(
        ...,
        min_length=1,
        description="Field names. Use 'id' for external XMLIDs to enable upsert.",
    )
    data: list[list[Any]] = Field(
        ..., min_length=1, description="Rows of values aligned with `fields`"
    )
    context: Optional[dict[str, Any]] = None


# ── Partner helpers ─────────────────────────────────────────────────────────


class FindPartnerInput(_OdooBaseInput):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    vat: Optional[str] = None
    is_company: Optional[bool] = None
    limit: int = Field(default=10, ge=1, le=200)


class CreatePartnerInput(_OdooBaseInput):
    name: str
    is_company: bool = False
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    website: Optional[str] = None
    street: Optional[str] = None
    street2: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    state_id: Optional[int] = None
    country_id: Optional[int] = None
    parent_id: Optional[int] = None
    vat: Optional[str] = None
    ref: Optional[str] = None
    customer_rank: Optional[int] = None
    supplier_rank: Optional[int] = None
    extra: Optional[dict[str, Any]] = Field(
        default=None, description="Additional res.partner fields not covered above"
    )


class UpdatePartnerContactInfoInput(_OdooBaseInput):
    partner_id: int = Field(..., ge=1)
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    website: Optional[str] = None
    street: Optional[str] = None
    street2: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    state_id: Optional[int] = None
    country_id: Optional[int] = None


# ── Sales helpers ───────────────────────────────────────────────────────────


class QuotationLineInput(_OdooBaseInput):
    product_id: int = Field(..., ge=1)
    product_uom_qty: float = Field(default=1.0, gt=0)
    price_unit: Optional[float] = None
    name: Optional[str] = None
    discount: Optional[float] = None
    tax_ids: Optional[list[int]] = None


class CreateQuotationInput(_OdooBaseInput):
    partner_id: int = Field(..., ge=1)
    order_lines: list[QuotationLineInput] = Field(..., min_length=1)
    date_order: Optional[str] = None
    validity_date: Optional[str] = None
    pricelist_id: Optional[int] = None
    payment_term_id: Optional[int] = None
    user_id: Optional[int] = None
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    client_order_ref: Optional[str] = None
    extra: Optional[dict[str, Any]] = None


class ConfirmSaleOrderInput(_OdooBaseInput):
    sale_order_id: int = Field(..., ge=1)


# ── Invoicing helpers ───────────────────────────────────────────────────────


class InvoiceLineInput(_OdooBaseInput):
    product_id: Optional[int] = Field(default=None, ge=1)
    quantity: float = Field(default=1.0, gt=0)
    price_unit: float = Field(..., ge=0)
    name: Optional[str] = None
    discount: Optional[float] = None
    tax_ids: Optional[list[int]] = None
    account_id: Optional[int] = None


class CreateInvoiceInput(_OdooBaseInput):
    partner_id: int = Field(..., ge=1)
    invoice_lines: list[InvoiceLineInput] = Field(..., min_length=1)
    move_type: Literal[
        "out_invoice", "in_invoice", "out_refund", "in_refund"
    ] = Field(default="out_invoice")
    invoice_date: Optional[str] = None
    invoice_date_due: Optional[str] = None
    journal_id: Optional[int] = None
    currency_id: Optional[int] = None
    invoice_origin: Optional[str] = None
    ref: Optional[str] = None
    extra: Optional[dict[str, Any]] = None


class PostInvoiceInput(_OdooBaseInput):
    invoice_id: int = Field(..., ge=1)


class RegisterPaymentInput(_OdooBaseInput):
    invoice_id: int = Field(..., ge=1)
    journal_id: int = Field(..., ge=1, description="Payment journal (e.g. bank)")
    amount: Optional[float] = Field(
        default=None,
        description="Payment amount; defaults to amount_residual on the invoice",
    )
    payment_date: Optional[str] = None
    payment_method_line_id: Optional[int] = None
    communication: Optional[str] = None


# ── Binary helpers ──────────────────────────────────────────────────────────


class SetBinaryFieldInput(_OdooBaseInput):
    model: str = Field(..., description="Odoo model containing the binary field")
    record_id: int = Field(..., ge=1)
    field_name: str = Field(..., description="Binary/Image field name, e.g. 'image_1920'")
    source: str = Field(
        ...,
        description="Either an http(s) URL to fetch, or a base64-encoded string",
    )


class AttachDocumentInput(_OdooBaseInput):
    res_model: str = Field(..., description="Target model the attachment belongs to")
    res_id: int = Field(..., ge=1)
    name: str = Field(..., description="File name as it should appear in Odoo")
    source: str = Field(
        ...,
        description="Either an http(s) URL to fetch, or a base64-encoded string",
    )
    mimetype: Optional[str] = None
    description: Optional[str] = None
