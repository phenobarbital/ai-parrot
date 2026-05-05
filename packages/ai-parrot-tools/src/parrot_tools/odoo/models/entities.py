"""Pydantic entity models for the most-used Odoo objects.

All models set ``extra='allow'`` so unknown Odoo fields round-trip cleanly:
this lets the toolkit support custom modules and minor schema drift without
requiring a model bump.

Many2one fields in Odoo serialise as ``[id, display_name]`` or ``False`` when
empty; we model them as ``Optional[Many2one]`` (a tuple/list of length 2).
One2many and Many2many serialise as lists of integer ids.
"""
from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# Odoo's many2one wire format: [id, display_name] | False
Many2one = Union[tuple[int, str], list[Any], bool, None]


class _OdooEntity(BaseModel):
    """Base for all Odoo entity models — preserves unknown fields verbatim."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: Optional[int] = Field(default=None, description="Odoo record id")
    display_name: Optional[str] = Field(default=None, description="Computed display name")


# ── res.partner ─────────────────────────────────────────────────────────────


class ResPartner(_OdooEntity):
    """Subset of ``res.partner`` fields most agents need."""

    name: Optional[str] = None
    is_company: Optional[bool] = None
    company_type: Optional[str] = None  # 'person' | 'company'
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    website: Optional[str] = None
    street: Optional[str] = None
    street2: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    state_id: Optional[Many2one] = None
    country_id: Optional[Many2one] = None
    parent_id: Optional[Many2one] = None
    vat: Optional[str] = None
    ref: Optional[str] = None
    customer_rank: Optional[int] = None
    supplier_rank: Optional[int] = None
    category_id: Optional[list[int]] = None
    user_id: Optional[Many2one] = None
    lang: Optional[str] = None
    active: Optional[bool] = None


class ResUsers(_OdooEntity):
    """Subset of ``res.users`` fields."""

    login: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    partner_id: Optional[Many2one] = None
    active: Optional[bool] = None
    company_id: Optional[Many2one] = None
    company_ids: Optional[list[int]] = None
    groups_id: Optional[list[int]] = None


# ── product.* ───────────────────────────────────────────────────────────────


class ProductTemplate(_OdooEntity):
    """Subset of ``product.template`` fields."""

    name: Optional[str] = None
    default_code: Optional[str] = None
    barcode: Optional[str] = None
    type: Optional[str] = None  # 'consu' | 'service' | 'product'
    list_price: Optional[float] = None
    standard_price: Optional[float] = None
    categ_id: Optional[Many2one] = None
    uom_id: Optional[Many2one] = None
    uom_po_id: Optional[Many2one] = None
    sale_ok: Optional[bool] = None
    purchase_ok: Optional[bool] = None
    active: Optional[bool] = None
    description_sale: Optional[str] = None


class ProductProduct(_OdooEntity):
    """Subset of ``product.product`` fields (variants)."""

    name: Optional[str] = None
    default_code: Optional[str] = None
    barcode: Optional[str] = None
    list_price: Optional[float] = None
    standard_price: Optional[float] = None
    qty_available: Optional[float] = None
    virtual_available: Optional[float] = None
    product_tmpl_id: Optional[Many2one] = None
    categ_id: Optional[Many2one] = None
    uom_id: Optional[Many2one] = None
    active: Optional[bool] = None


# ── sale.order ──────────────────────────────────────────────────────────────


class SaleOrderLine(_OdooEntity):
    """Subset of ``sale.order.line`` fields."""

    name: Optional[str] = None
    product_id: Optional[Many2one] = None
    product_uom_qty: Optional[float] = None
    price_unit: Optional[float] = None
    price_subtotal: Optional[float] = None
    price_tax: Optional[float] = None
    price_total: Optional[float] = None
    discount: Optional[float] = None
    tax_id: Optional[list[int]] = None
    order_id: Optional[Many2one] = None


class SaleOrder(_OdooEntity):
    """Subset of ``sale.order`` fields."""

    name: Optional[str] = None
    state: Optional[str] = None  # 'draft' | 'sent' | 'sale' | 'done' | 'cancel'
    partner_id: Optional[Many2one] = None
    partner_invoice_id: Optional[Many2one] = None
    partner_shipping_id: Optional[Many2one] = None
    date_order: Optional[str] = None
    validity_date: Optional[str] = None
    user_id: Optional[Many2one] = None
    team_id: Optional[Many2one] = None
    company_id: Optional[Many2one] = None
    currency_id: Optional[Many2one] = None
    pricelist_id: Optional[Many2one] = None
    payment_term_id: Optional[Many2one] = None
    amount_untaxed: Optional[float] = None
    amount_tax: Optional[float] = None
    amount_total: Optional[float] = None
    order_line: Optional[list[int]] = None
    invoice_status: Optional[str] = None
    client_order_ref: Optional[str] = None


# ── account.move (invoice / bill) ───────────────────────────────────────────


class AccountMoveLine(_OdooEntity):
    """Subset of ``account.move.line`` fields."""

    name: Optional[str] = None
    move_id: Optional[Many2one] = None
    product_id: Optional[Many2one] = None
    quantity: Optional[float] = None
    price_unit: Optional[float] = None
    price_subtotal: Optional[float] = None
    price_total: Optional[float] = None
    discount: Optional[float] = None
    tax_ids: Optional[list[int]] = None
    account_id: Optional[Many2one] = None
    debit: Optional[float] = None
    credit: Optional[float] = None
    balance: Optional[float] = None


class AccountMove(_OdooEntity):
    """Subset of ``account.move`` fields (invoices, bills, journal entries)."""

    name: Optional[str] = None
    move_type: Optional[str] = Field(
        default=None,
        description="'out_invoice' | 'in_invoice' | 'out_refund' | 'in_refund' | 'entry' | …",
    )
    state: Optional[str] = None  # 'draft' | 'posted' | 'cancel'
    payment_state: Optional[str] = None
    partner_id: Optional[Many2one] = None
    invoice_date: Optional[str] = None
    invoice_date_due: Optional[str] = None
    journal_id: Optional[Many2one] = None
    currency_id: Optional[Many2one] = None
    company_id: Optional[Many2one] = None
    invoice_user_id: Optional[Many2one] = None
    invoice_origin: Optional[str] = None
    ref: Optional[str] = None
    amount_untaxed: Optional[float] = None
    amount_tax: Optional[float] = None
    amount_total: Optional[float] = None
    amount_residual: Optional[float] = None
    invoice_line_ids: Optional[list[int]] = None


# ── crm.lead ────────────────────────────────────────────────────────────────


class CrmLead(_OdooEntity):
    """Subset of ``crm.lead`` fields."""

    name: Optional[str] = None
    type: Optional[str] = None  # 'lead' | 'opportunity'
    stage_id: Optional[Many2one] = None
    partner_id: Optional[Many2one] = None
    contact_name: Optional[str] = None
    email_from: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    expected_revenue: Optional[float] = None
    probability: Optional[float] = None
    user_id: Optional[Many2one] = None
    team_id: Optional[Many2one] = None
    company_id: Optional[Many2one] = None
    description: Optional[str] = None
    tag_ids: Optional[list[int]] = None
    date_deadline: Optional[str] = None


# ── stock.picking ───────────────────────────────────────────────────────────


class StockPicking(_OdooEntity):
    """Subset of ``stock.picking`` fields (delivery / receipt orders)."""

    name: Optional[str] = None
    state: Optional[str] = None  # 'draft' | 'waiting' | 'confirmed' | 'assigned' | 'done' | 'cancel'
    partner_id: Optional[Many2one] = None
    picking_type_id: Optional[Many2one] = None
    location_id: Optional[Many2one] = None
    location_dest_id: Optional[Many2one] = None
    scheduled_date: Optional[str] = None
    date_done: Optional[str] = None
    origin: Optional[str] = None
    move_ids: Optional[list[int]] = None


# ── hr.employee ─────────────────────────────────────────────────────────────


class HrEmployee(_OdooEntity):
    """Subset of ``hr.employee`` fields most agents need."""

    name: Optional[str] = None
    job_id: Optional[Many2one] = None
    job_title: Optional[str] = None
    department_id: Optional[Many2one] = None
    parent_id: Optional[Many2one] = None
    work_email: Optional[str] = None
    work_phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    company_id: Optional[Many2one] = None
    active: Optional[bool] = None


# ── hr.leave ─────────────────────────────────────────────────────────────────


class HrLeave(_OdooEntity):
    """Subset of ``hr.leave`` (leave allocation/request) fields."""

    employee_id: Optional[Many2one] = None
    holiday_status_id: Optional[Many2one] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    number_of_days: Optional[float] = None
    state: Optional[str] = None  # 'draft' | 'confirm' | 'validate' | 'refuse'
    name: Optional[str] = None


__all__ = [
    "Many2one",
    "ResPartner",
    "ResUsers",
    "ProductTemplate",
    "ProductProduct",
    "SaleOrder",
    "SaleOrderLine",
    "AccountMove",
    "AccountMoveLine",
    "CrmLead",
    "StockPicking",
    "HrEmployee",
    "HrLeave",
]
