"""OdooToolkit — exposes Odoo ERP operations as agent tools.

Composes an :class:`~parrot_tools.odoo.transport.AbstractOdooTransport`
(JSON-2 for Odoo 19+, XML-RPC for 14-18, or auto-detected) and turns
each public async method into a tool via :class:`AbstractToolkit`.

Inspired by:
- ``pantalytics/odoo-mcp-pro`` — for the result-envelope pattern, the bulk
  CRUD layout and the binary upload helper.
- ``phenobarbital/flowtask`` ``OdooInjector`` — for the ``import_records``
  upsert use case (Odoo's ``load`` with external IDs).

Configuration falls back to the ``ODOO_*`` keys in :mod:`parrot.conf` when
constructor arguments are omitted.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from typing import Any, Literal, Optional

import aiohttp
from pydantic import BaseModel

from parrot.conf import (
    ODOO_DATABASE,
    ODOO_PASSWORD,
    ODOO_TIMEOUT,
    ODOO_URL,
    ODOO_USERNAME,
    ODOO_VERIFY_SSL,
)
from parrot.interfaces.odoointerface import (
    OdooAuthenticationError,
    OdooConfig,
    OdooConnectionError,
    OdooError,
    OdooRPCError,
)
from parrot.tools.decorators import tool_schema
from parrot.tools.decorators import requires_permission
from parrot.tools.toolkit import AbstractToolkit

from .models.entities import (
    AccountMove,
    CrmLead,
    ProductProduct,
    ProductTemplate,
    ResPartner,
    SaleOrder,
    StockPicking,
)
from .models.envelopes import (
    BinaryFieldResult,
    BulkCreateResult,
    BulkDeleteResult,
    BulkUpdateResult,
    CreateResult,
    DeleteResult,
    FieldSelectionMetadata,
    ImportResult,
    ModelInfo,
    ModelOperations,
    ModelsResult,
    RecordResult,
    SearchResult,
    ServerInfoResult,
    UpdateResult,
)
from .models.inputs import (
    AttachDocumentInput,
    ConfirmSaleOrderInput,
    CreateInvoiceInput,
    CreatePartnerInput,
    CreateQuotationInput,
    CreateRecordInput,
    CreateRecordsInput,
    DeleteRecordInput,
    DeleteRecordsInput,
    FieldsGetInput,
    FindPartnerInput,
    GetRecordInput,
    ImportRecordsInput,
    PostInvoiceInput,
    RegisterPaymentInput,
    SearchRecordsInput,
    SetBinaryFieldInput,
    UpdatePartnerContactInfoInput,
    UpdateRecordInput,
    UpdateRecordsInput,
)
from .transport import (
    AbstractOdooTransport,
    Protocol,
    auto_detect_transport,
    build_transport,
)

# Models that are exposed by default through ``list_models``. These match the
# typed entities the toolkit understands; agents can still query any other
# Odoo model through the generic CRUD tools.
_DEFAULT_KNOWN_MODELS: tuple[tuple[str, str], ...] = (
    ("res.partner", "Contact / Partner"),
    ("res.users", "User"),
    ("product.template", "Product Template"),
    ("product.product", "Product Variant"),
    ("sale.order", "Sales Order"),
    ("sale.order.line", "Sales Order Line"),
    ("account.move", "Journal Entry / Invoice"),
    ("account.move.line", "Journal Item"),
    ("crm.lead", "CRM Lead / Opportunity"),
    ("stock.picking", "Stock Transfer"),
)


def _model_to_dict(model: BaseModel | dict[str, Any] | None) -> dict[str, Any]:
    """Render a Pydantic model (or pass-through dict) to JSON-friendly dict."""
    if model is None:
        return {}
    if isinstance(model, BaseModel):
        return model.model_dump(exclude_none=True)
    return dict(model)


class OdooToolkit(AbstractToolkit):
    """Toolkit exposing Odoo ERP CRUD + business helpers as agent tools.

    Construction validates configuration via :class:`OdooConfig` but defers
    all I/O to the first tool call, which authenticates lazily through
    :meth:`_pre_execute`.

    Example:
        toolkit = OdooToolkit(
            url="https://my.odoo.com",
            database="prod",
            username="alice@acme.com",
            password="...",
            protocol="auto",
        )
        tools = toolkit.get_tools()
        result = await toolkit.search_records(model="res.partner", limit=5)
    """

    tool_prefix = "odoo"

    def __init__(
        self,
        url: str | None = None,
        database: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int | None = None,
        verify_ssl: bool | None = None,
        protocol: Protocol = "auto",
        transport: AbstractOdooTransport | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the toolkit.

        Args:
            url: Odoo base URL. Falls back to ``ODOO_URL``.
            database: Odoo database. Falls back to ``ODOO_DATABASE``.
            username: Odoo login. Falls back to ``ODOO_USERNAME``.
            password: Odoo password / API key. Falls back to ``ODOO_PASSWORD``.
            timeout: Request timeout (seconds). Falls back to ``ODOO_TIMEOUT``.
            verify_ssl: Whether to verify SSL certificates.
            protocol: 'auto' (default), 'json2', 'jsonrpc', or 'xmlrpc'.
            transport: Pre-built transport (mainly for tests). When provided,
                ``protocol`` is ignored.
            **kwargs: Forwarded to :class:`AbstractToolkit`.
        """
        super().__init__(**kwargs)
        self.config = OdooConfig(
            url=url or ODOO_URL or "",
            database=database or ODOO_DATABASE or "",
            username=username or ODOO_USERNAME or "",
            password=password or ODOO_PASSWORD or "",
            timeout=timeout if timeout is not None else ODOO_TIMEOUT,
            verify_ssl=verify_ssl if verify_ssl is not None else ODOO_VERIFY_SSL,
        )
        self.protocol: Protocol = protocol
        self._transport: AbstractOdooTransport | None = transport
        self._auth_lock = asyncio.Lock()
        self.logger = logging.getLogger("OdooToolkit")

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def _ensure_transport(self) -> AbstractOdooTransport:
        """Build the transport on first use and authenticate exactly once.

        Concurrent tool calls are serialised by :attr:`_auth_lock` so we never
        kick off two parallel logins.
        """
        if self._transport is not None and self._transport.uid is not None:
            return self._transport
        async with self._auth_lock:
            if self._transport is None:
                if self.protocol == "auto":
                    self._transport = await auto_detect_transport(self.config)
                else:
                    built = build_transport(self.protocol, self.config)
                    if built is None:
                        raise ValueError(
                            f"build_transport returned None for protocol={self.protocol!r}"
                        )
                    self._transport = built
            if self._transport.uid is None:
                await self._transport.authenticate()
            return self._transport

    async def _pre_execute(self, tool_name: str, **kwargs: Any) -> None:
        """Authenticate lazily before the first tool call."""
        if self.config.url and self.config.database and self.config.username:
            await self._ensure_transport()

    async def stop(self) -> None:
        """Release the transport's session if any."""
        if self._transport is not None:
            await self._transport.close()

    async def cleanup(self) -> None:
        await self.stop()

    # ── Internal helpers (private — never exposed as tools) ─────────────────

    async def _execute(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Run an ``execute_kw`` call through the active transport."""
        transport = await self._ensure_transport()
        return await transport.execute_kw(model, method, args, kwargs)

    @staticmethod
    def _record_url(base_url: str, model: str, record_id: int) -> str:
        """Build an Odoo web URL pointing at a given record."""
        return f"{base_url.rstrip('/')}/web#id={record_id}&model={model}&view_type=form"

    async def _read_one(
        self,
        model: str,
        record_id: int,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch a single record and return its dict (empty dict if missing)."""
        kw: dict[str, Any] = {}
        if fields:
            kw["fields"] = fields
        rows = await self._execute(model, "read", [[record_id]], kw)
        return rows[0] if rows else {}

    @staticmethod
    async def _resolve_binary_source(source: str) -> bytes:
        """Resolve a SetBinary/AttachDocument ``source`` to raw bytes.

        Accepts:
          * ``http(s)://...`` — fetched via aiohttp.
          * Otherwise — assumed base64 (whitespace stripped); on decode failure
            the raw UTF-8 bytes are returned (lets callers pass plain text).
        """
        if source.startswith(("http://", "https://")):
            async with aiohttp.ClientSession() as session:
                async with session.get(source) as resp:
                    resp.raise_for_status()
                    return await resp.read()
        try:
            return base64.b64decode(source, validate=True)
        except (binascii.Error, ValueError):
            return source.encode("utf-8")

    # ────────────────────────────────────────────────────────────────────────
    # ──  PUBLIC TOOLS — every public async method is registered as a tool  ──
    # ────────────────────────────────────────────────────────────────────────

    # ── Discovery ───────────────────────────────────────────────────────────

    async def server_info(self) -> ServerInfoResult:
        """Return Odoo server version, transport, and connection status."""
        try:
            transport = await self._ensure_transport()
            info = await transport.version()
        except OdooError as exc:
            self.logger.warning("server_info failed: %s", exc)
            return ServerInfoResult(
                odoo_url=self.config.url,
                database=self.config.database,
                connected=False,
                transport=self.protocol,
            )
        return ServerInfoResult(
            server_version=str(info.get("server_version", "")),
            server_serie=str(info.get("server_serie", "")),
            protocol_version=info.get("protocol_version"),
            server_version_info=list(info.get("server_version_info") or []),
            odoo_url=self.config.url,
            database=self.config.database,
            connected=transport.uid is not None,
            transport=transport.name,
            uid=transport.uid,
        )

    async def list_models(self) -> ModelsResult:
        """List the Odoo models the toolkit knows about with the user's ACLs."""
        models: list[ModelInfo] = []
        for tech_name, label in _DEFAULT_KNOWN_MODELS:
            ops = ModelOperations()
            for op in ("read", "write", "create", "unlink"):
                try:
                    allowed = await self._execute(
                        tech_name,
                        "check_access_rights",
                        [op],
                        {"raise_exception": False},
                    )
                except OdooError:
                    allowed = False
                setattr(ops, op, bool(allowed))
            models.append(ModelInfo(model=tech_name, name=label, operations=ops))
        return ModelsResult(models=models, total=len(models))

    @tool_schema(FieldsGetInput)
    async def fields_get(
        self,
        model: str,
        attributes: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Return the field definitions for an Odoo model."""
        kwargs: dict[str, Any] = {}
        if attributes:
            kwargs["attributes"] = attributes
        return await self._execute(model, "fields_get", [], kwargs)

    # ── Generic CRUD ────────────────────────────────────────────────────────

    @tool_schema(SearchRecordsInput)
    async def search_records(
        self,
        model: str,
        domain: Optional[list[Any]] = None,
        fields: Optional[list[str]] = None,
        limit: int = 100,
        offset: int = 0,
        order: Optional[str] = None,
    ) -> SearchResult:
        """Search records in any Odoo model with domain filters & pagination."""
        kwargs: dict[str, Any] = {"limit": limit, "offset": offset}
        if fields:
            kwargs["fields"] = fields
        if order:
            kwargs["order"] = order
        records = await self._execute(model, "search_read", [domain or []], kwargs)
        total = await self._execute(model, "search_count", [domain or []])
        return SearchResult(
            records=records or [],
            total=int(total or 0),
            limit=limit,
            offset=offset,
            model=model,
            fields=fields,
        )

    @tool_schema(GetRecordInput)
    async def get_record(
        self,
        model: str,
        record_id: int,
        fields: Optional[list[str]] = None,
    ) -> RecordResult:
        """Read a single record by id."""
        record = await self._read_one(model, record_id, fields)
        metadata = FieldSelectionMetadata(
            fields_returned=len(record),
            field_selection_method="requested" if fields else "all",
            note="Requested fields were used." if fields else "No explicit fields requested.",
        )
        return RecordResult(record=record, model=model, metadata=metadata)

    @requires_permission("odoo.write")
    @tool_schema(CreateRecordInput)
    async def create_record(
        self,
        model: str,
        values: dict[str, Any],
    ) -> CreateResult:
        """Create one record and return the new id + a summary of the record."""
        new_id = await self._execute(model, "create", [values])
        record = await self._read_one(model, int(new_id))
        return CreateResult(
            record=record,
            record_id=int(new_id),
            model=model,
            message=f"Created {model} #{new_id}",
        )

    @requires_permission("odoo.write")
    @tool_schema(CreateRecordsInput)
    async def create_records(
        self,
        model: str,
        vals_list: list[dict[str, Any]],
    ) -> BulkCreateResult:
        """Create multiple records in a single round-trip (max 1000)."""
        result = await self._execute(model, "create", [vals_list])
        ids = list(result) if isinstance(result, list) else [int(result)]
        return BulkCreateResult(
            created_ids=[int(i) for i in ids],
            count=len(ids),
            model=model,
            message=f"Created {len(ids)} {model} record(s)",
        )

    @requires_permission("odoo.write")
    @tool_schema(UpdateRecordInput)
    async def update_record(
        self,
        model: str,
        record_id: int,
        values: dict[str, Any],
    ) -> UpdateResult:
        """Update a single record by id."""
        ok = await self._execute(model, "write", [[record_id], values])
        record = await self._read_one(model, record_id) if ok else {}
        return UpdateResult(
            success=bool(ok),
            record=record,
            record_id=record_id,
            model=model,
            message=f"Updated {model} #{record_id}",
        )

    @requires_permission("odoo.write")
    @tool_schema(UpdateRecordsInput)
    async def update_records(
        self,
        model: str,
        record_ids: list[int],
        values: dict[str, Any],
    ) -> BulkUpdateResult:
        """Apply the same patch to many records in one call (max 1000)."""
        ok = await self._execute(model, "write", [list(record_ids), values])
        return BulkUpdateResult(
            success=bool(ok),
            updated_ids=list(record_ids),
            count=len(record_ids),
            model=model,
            message=f"Updated {len(record_ids)} {model} record(s)",
        )

    @requires_permission("odoo.delete")
    @tool_schema(DeleteRecordInput)
    async def delete_record(
        self,
        model: str,
        record_id: int,
    ) -> DeleteResult:
        """Delete a single record by id."""
        ok = await self._execute(model, "unlink", [[record_id]])
        return DeleteResult(
            success=bool(ok),
            deleted_id=record_id,
            model=model,
            message=f"Deleted {model} #{record_id}",
        )

    @requires_permission("odoo.delete")
    @tool_schema(DeleteRecordsInput)
    async def delete_records(
        self,
        model: str,
        record_ids: list[int],
    ) -> BulkDeleteResult:
        """Delete multiple records in one call (max 1000)."""
        ok = await self._execute(model, "unlink", [list(record_ids)])
        return BulkDeleteResult(
            success=bool(ok),
            deleted_ids=list(record_ids),
            count=len(record_ids),
            model=model,
            message=f"Deleted {len(record_ids)} {model} record(s)",
        )

    @requires_permission("odoo.write")
    @tool_schema(ImportRecordsInput)
    async def import_records(
        self,
        model: str,
        fields: list[str],
        data: list[list[Any]],
        context: Optional[dict[str, Any]] = None,
    ) -> ImportResult:
        """Idempotent upsert via Odoo's ``load`` (use 'id' field for external IDs).

        This mirrors Odoo's CSV import semantics: rows whose external-id is
        already present are updated, new rows are created. Same operation
        Flowtask's OdooInjector relies on for ETL jobs.
        """
        kwargs = {"context": context} if context else {}
        result = await self._execute(model, "load", [fields, data], kwargs)
        ids = [int(i) for i in (result or {}).get("ids") or []]
        errors = list((result or {}).get("messages") or [])
        return ImportResult(
            success=bool(ids) and not errors,
            imported=len(ids),
            ids=ids,
            errors=errors,
            model=model,
            message=(
                f"Imported {len(ids)} {model} record(s); "
                f"{len(errors)} message(s)"
            ),
        )

    # ── Partner helpers ─────────────────────────────────────────────────────

    _PARTNER_DEFAULT_FIELDS = [
        "id", "display_name", "name", "is_company", "company_type",
        "email", "phone", "mobile", "website", "vat", "ref",
        "street", "street2", "city", "zip", "state_id", "country_id",
        "parent_id", "user_id", "lang", "active",
        "customer_rank", "supplier_rank", "category_id",
    ]

    @tool_schema(FindPartnerInput)
    async def find_partner(
        self,
        name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        vat: Optional[str] = None,
        is_company: Optional[bool] = None,
        limit: int = 10,
    ) -> list[ResPartner]:
        """Search ``res.partner`` with friendly arguments and typed results."""
        domain: list[Any] = []
        if name:
            domain.append(("name", "ilike", name))
        if email:
            domain.append(("email", "ilike", email))
        if phone:
            domain.append("|")
            domain.append(("phone", "ilike", phone))
            domain.append(("mobile", "ilike", phone))
        if vat:
            domain.append(("vat", "=", vat))
        if is_company is not None:
            domain.append(("is_company", "=", is_company))
        records = await self._execute(
            "res.partner",
            "search_read",
            [domain],
            {"fields": self._PARTNER_DEFAULT_FIELDS, "limit": limit},
        )
        return [ResPartner.model_validate(r) for r in records or []]

    @requires_permission("odoo.write")
    @tool_schema(CreatePartnerInput)
    async def create_partner(
        self,
        name: str,
        is_company: bool = False,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        mobile: Optional[str] = None,
        website: Optional[str] = None,
        street: Optional[str] = None,
        street2: Optional[str] = None,
        city: Optional[str] = None,
        zip: Optional[str] = None,
        state_id: Optional[int] = None,
        country_id: Optional[int] = None,
        parent_id: Optional[int] = None,
        vat: Optional[str] = None,
        ref: Optional[str] = None,
        customer_rank: Optional[int] = None,
        supplier_rank: Optional[int] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> ResPartner:
        """Create a ``res.partner`` and return it as a typed model."""
        values: dict[str, Any] = {"name": name, "is_company": is_company}
        for key, val in (
            ("email", email), ("phone", phone), ("mobile", mobile),
            ("website", website), ("street", street), ("street2", street2),
            ("city", city), ("zip", zip), ("state_id", state_id),
            ("country_id", country_id), ("parent_id", parent_id),
            ("vat", vat), ("ref", ref),
            ("customer_rank", customer_rank), ("supplier_rank", supplier_rank),
        ):
            if val is not None:
                values[key] = val
        if extra:
            values.update(extra)
        new_id = await self._execute("res.partner", "create", [values])
        record = await self._read_one(
            "res.partner", int(new_id), self._PARTNER_DEFAULT_FIELDS
        )
        return ResPartner.model_validate(record)

    @requires_permission("odoo.write")
    @tool_schema(UpdatePartnerContactInfoInput)
    async def update_partner_contact_info(
        self,
        partner_id: int,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        mobile: Optional[str] = None,
        website: Optional[str] = None,
        street: Optional[str] = None,
        street2: Optional[str] = None,
        city: Optional[str] = None,
        zip: Optional[str] = None,
        state_id: Optional[int] = None,
        country_id: Optional[int] = None,
    ) -> ResPartner:
        """Update contact / address fields on an existing partner."""
        values = {
            k: v for k, v in {
                "email": email, "phone": phone, "mobile": mobile,
                "website": website, "street": street, "street2": street2,
                "city": city, "zip": zip, "state_id": state_id,
                "country_id": country_id,
            }.items() if v is not None
        }
        if not values:
            raise ValueError("update_partner_contact_info requires at least one field to update")
        await self._execute("res.partner", "write", [[partner_id], values])
        record = await self._read_one(
            "res.partner", partner_id, self._PARTNER_DEFAULT_FIELDS
        )
        return ResPartner.model_validate(record)

    # ── Sales helpers ───────────────────────────────────────────────────────

    _SALE_ORDER_DEFAULT_FIELDS = [
        "id", "display_name", "name", "state", "partner_id",
        "date_order", "validity_date", "user_id", "team_id",
        "company_id", "currency_id", "pricelist_id", "payment_term_id",
        "amount_untaxed", "amount_tax", "amount_total",
        "order_line", "invoice_status", "client_order_ref",
    ]

    @requires_permission("odoo.write")
    @tool_schema(CreateQuotationInput)
    async def create_quotation(
        self,
        partner_id: int,
        order_lines: list[dict[str, Any]],
        date_order: Optional[str] = None,
        validity_date: Optional[str] = None,
        pricelist_id: Optional[int] = None,
        payment_term_id: Optional[int] = None,
        user_id: Optional[int] = None,
        team_id: Optional[int] = None,
        company_id: Optional[int] = None,
        client_order_ref: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> SaleOrder:
        """Create a draft ``sale.order`` (quotation) with one or more lines."""
        line_commands = [(0, 0, _model_to_dict(line)) for line in order_lines]
        values: dict[str, Any] = {
            "partner_id": partner_id,
            "order_line": line_commands,
        }
        for key, val in (
            ("date_order", date_order), ("validity_date", validity_date),
            ("pricelist_id", pricelist_id), ("payment_term_id", payment_term_id),
            ("user_id", user_id), ("team_id", team_id),
            ("company_id", company_id), ("client_order_ref", client_order_ref),
        ):
            if val is not None:
                values[key] = val
        if extra:
            values.update(extra)
        new_id = await self._execute("sale.order", "create", [values])
        record = await self._read_one(
            "sale.order", int(new_id), self._SALE_ORDER_DEFAULT_FIELDS
        )
        return SaleOrder.model_validate(record)

    @requires_permission("odoo.write")
    @tool_schema(ConfirmSaleOrderInput)
    async def confirm_sale_order(self, sale_order_id: int) -> SaleOrder:
        """Confirm a draft quotation, transitioning it to the 'sale' state."""
        await self._execute("sale.order", "action_confirm", [[sale_order_id]])
        record = await self._read_one(
            "sale.order", sale_order_id, self._SALE_ORDER_DEFAULT_FIELDS
        )
        return SaleOrder.model_validate(record)

    # ── Invoicing helpers ───────────────────────────────────────────────────

    _ACCOUNT_MOVE_DEFAULT_FIELDS = [
        "id", "display_name", "name", "move_type", "state", "payment_state",
        "partner_id", "invoice_date", "invoice_date_due", "journal_id",
        "currency_id", "company_id", "invoice_user_id", "invoice_origin", "ref",
        "amount_untaxed", "amount_tax", "amount_total", "amount_residual",
        "invoice_line_ids",
    ]

    @requires_permission("odoo.write")
    @tool_schema(CreateInvoiceInput)
    async def create_invoice(
        self,
        partner_id: int,
        invoice_lines: list[dict[str, Any]],
        move_type: Literal[
            "out_invoice", "in_invoice", "out_refund", "in_refund"
        ] = "out_invoice",
        invoice_date: Optional[str] = None,
        invoice_date_due: Optional[str] = None,
        journal_id: Optional[int] = None,
        currency_id: Optional[int] = None,
        invoice_origin: Optional[str] = None,
        ref: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> AccountMove:
        """Create a draft invoice / vendor bill on ``account.move``."""
        line_commands = [(0, 0, _model_to_dict(line)) for line in invoice_lines]
        values: dict[str, Any] = {
            "move_type": move_type,
            "partner_id": partner_id,
            "invoice_line_ids": line_commands,
        }
        for key, val in (
            ("invoice_date", invoice_date),
            ("invoice_date_due", invoice_date_due),
            ("journal_id", journal_id),
            ("currency_id", currency_id),
            ("invoice_origin", invoice_origin),
            ("ref", ref),
        ):
            if val is not None:
                values[key] = val
        if extra:
            values.update(extra)
        new_id = await self._execute("account.move", "create", [values])
        record = await self._read_one(
            "account.move", int(new_id), self._ACCOUNT_MOVE_DEFAULT_FIELDS
        )
        return AccountMove.model_validate(record)

    @requires_permission("odoo.write")
    @tool_schema(PostInvoiceInput)
    async def post_invoice(self, invoice_id: int) -> AccountMove:
        """Post a draft invoice (Odoo 13+: ``action_post``)."""
        await self._execute("account.move", "action_post", [[invoice_id]])
        record = await self._read_one(
            "account.move", invoice_id, self._ACCOUNT_MOVE_DEFAULT_FIELDS
        )
        return AccountMove.model_validate(record)

    @requires_permission("odoo.write")
    @tool_schema(RegisterPaymentInput)
    async def register_payment(
        self,
        invoice_id: int,
        journal_id: int,
        amount: Optional[float] = None,
        payment_date: Optional[str] = None,
        payment_method_line_id: Optional[int] = None,
        communication: Optional[str] = None,
    ) -> dict[str, Any]:
        """Register a payment on a posted invoice via ``account.payment.register``.

        Returns the dict of created ``account.payment`` records (keyed by id).
        """
        payment_vals: dict[str, Any] = {"journal_id": journal_id}
        if amount is not None:
            payment_vals["amount"] = amount
        if payment_date:
            payment_vals["payment_date"] = payment_date
        if payment_method_line_id:
            payment_vals["payment_method_line_id"] = payment_method_line_id
        if communication:
            payment_vals["communication"] = communication
        ctx = {"active_model": "account.move", "active_ids": [invoice_id]}
        wizard_id = await self._execute(
            "account.payment.register",
            "create",
            [payment_vals],
            {"context": ctx},
        )
        result = await self._execute(
            "account.payment.register",
            "action_create_payments",
            [[int(wizard_id)]],
            {"context": ctx},
        )
        return result if isinstance(result, dict) else {"result": result}

    # ── Binary helpers ──────────────────────────────────────────────────────

    @requires_permission("odoo.write")
    @tool_schema(SetBinaryFieldInput)
    async def set_binary_field(
        self,
        model: str,
        record_id: int,
        field_name: str,
        source: str,
    ) -> BinaryFieldResult:
        """Upload bytes (URL or base64 string) into a Binary/Image field."""
        data = await self._resolve_binary_source(source)
        encoded = base64.b64encode(data).decode("ascii")
        await self._execute(model, "write", [[record_id], {field_name: encoded}])
        return BinaryFieldResult(
            model=model,
            record_id=record_id,
            field=field_name,
            size_bytes=len(data),
            message=f"Uploaded {len(data)} bytes to {model}.{field_name} on #{record_id}",
        )

    @requires_permission("odoo.write")
    @tool_schema(AttachDocumentInput)
    async def attach_document(
        self,
        res_model: str,
        res_id: int,
        name: str,
        source: str,
        mimetype: Optional[str] = None,
        description: Optional[str] = None,
    ) -> BinaryFieldResult:
        """Create an ``ir.attachment`` linked to ``res_model``/``res_id``."""
        data = await self._resolve_binary_source(source)
        encoded = base64.b64encode(data).decode("ascii")
        values: dict[str, Any] = {
            "name": name,
            "res_model": res_model,
            "res_id": res_id,
            "datas": encoded,
            "type": "binary",
        }
        if mimetype:
            values["mimetype"] = mimetype
        if description:
            values["description"] = description
        attachment_id = await self._execute("ir.attachment", "create", [values])
        return BinaryFieldResult(
            model="ir.attachment",
            record_id=int(attachment_id),
            field="datas",
            size_bytes=len(data),
            message=(
                f"Attached {name!r} ({len(data)} bytes) to {res_model} #{res_id} "
                f"as ir.attachment #{attachment_id}"
            ),
        )


# Re-export common errors for convenience so callers don't need a second import.
__all__ = [
    "OdooToolkit",
    "OdooError",
    "OdooAuthenticationError",
    "OdooConnectionError",
    "OdooRPCError",
]
