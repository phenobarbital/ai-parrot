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

import ast
import asyncio
import base64
import binascii
import logging
import os
import re
from pathlib import Path
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

from .models.envelopes import (
    AccessDiagnosisResult,
    AddonScanResult,
    AggregateResult,
    BinaryFieldResult,
    BulkCreateResult,
    BulkDeleteResult,
    BulkUpdateResult,
    BusinessPackResult,
    CreateResult,
    DeleteResult,
    DomainBuildResult,
    FieldSelectionMetadata,
    FitGapResult,
    HealthCheckResult,
    ImportResult,
    Json2PayloadResult,
    ModelInfo,
    ModelOperations,
    ModelRelationshipsResult,
    ModelsResult,
    OdooCallDiagnosisResult,
    OdooProfileResult,
    RecordResult,
    SchemaCatalogResult,
    SearchResult,
    ServerInfoResult,
    UpdateResult,
)
from .models.entities import (
    AccountMove,
    CrmLead,
    HrEmployee,
    HrLeave,
    ProductProduct,
    ProductTemplate,
    ResPartner,
    SaleOrder,
    StockPicking,
)
from .models.inputs import (
    AggregateRecordsInput,
    AttachDocumentInput,
    BuildDomainInput,
    BusinessPackReportInput,
    ConfirmSaleOrderInput,
    CreateInvoiceInput,
    CreatePartnerInput,
    CreateQuotationInput,
    CreateRecordInput,
    CreateRecordsInput,
    DeleteRecordInput,
    DeleteRecordsInput,
    DiagnoseAccessInput,
    DiagnoseOdooCallInput,
    FieldsGetInput,
    FindPartnerInput,
    FitGapReportInput,
    GenerateJson2PayloadInput,
    GetOdooProfileInput,
    GetRecordInput,
    ImportRecordsInput,
    InspectModelRelationshipsInput,
    PostInvoiceInput,
    RegisterPaymentInput,
    ScanAddonsSourceInput,
    SchemaCatalogInput,
    SearchEmployeeInput,
    SearchHolidaysInput,
    SearchRecordsInput,
    SetBinaryFieldInput,
    UpdatePartnerContactInfoInput,
    UpdateRecordInput,
    UpdateRecordsInput,
)
from .shell import (
    OdooCliCommandInput,
    OdooShellInstallInput,
    OdooShellUpgradeInput,
    ShellResult,
    build_install_argv,
    default_database,
    odoo_bin_path,
    odoo_conf_path,
    run_odoo_subprocess,
    validate_subcommand,
    validate_token,
)
from .smart_fields import select_smart_fields
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

    #: Shell tools that require HITL confirmation before execution (FEAT-240).
    confirming_tools: frozenset = frozenset(
        {
            "odoo_shell_install_module",
            "odoo_shell_upgrade_module",
            "odoo_cli_command",
        }
    )

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
        self._fields_cache: dict[str, dict[str, Any]] = {}
        self.logger = logging.getLogger(__name__)

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

    async def _get_fields_metadata(self, model: str) -> dict[str, Any]:
        """Return cached ``fields_get`` metadata for *model*.

        Calls Odoo once on cache miss, then stores the result.  Cache is
        per-toolkit-instance and has no TTL (field schemas don't change
        during a session).
        """
        if model not in self._fields_cache:
            self._fields_cache[model] = await self.fields_get(model)
        return self._fields_cache[model]

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
        """Search records in any Odoo model with domain filters & pagination.

        When ``fields`` is omitted, smart field selection automatically picks
        the top 15 most LLM-useful fields for the model (avoiding binary blobs
        and technical audit columns).
        """
        # Smart-field fallback: auto-select when caller omits fields
        auto_selected = False
        fields_meta: Optional[dict[str, Any]] = None
        if fields is None:
            fields_meta = await self._get_fields_metadata(model)
            fields = select_smart_fields(fields_meta)
            auto_selected = True

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
            metadata=FieldSelectionMetadata(
                fields_returned=len(fields) if fields else 0,
                field_selection_method="auto" if auto_selected else "requested",
                total_fields_available=len(fields_meta) if fields_meta else None,
                note=(
                    f"Smart field selection chose {len(fields)} of "
                    f"{len(fields_meta)} available fields."
                    if auto_selected and fields_meta
                    else "Caller-requested fields used."
                ),
            ),
        )

    @tool_schema(GetRecordInput)
    async def get_record(
        self,
        model: str,
        record_id: int,
        fields: Optional[list[str]] = None,
    ) -> RecordResult:
        """Read a single record by id.

        When ``fields`` is omitted, smart field selection automatically picks
        the top 15 most LLM-useful fields for the model.
        """
        # Smart-field fallback: auto-select when caller omits fields
        auto_selected = False
        fields_meta: Optional[dict[str, Any]] = None
        if fields is None:
            fields_meta = await self._get_fields_metadata(model)
            fields = select_smart_fields(fields_meta)
            auto_selected = True

        record = await self._read_one(model, record_id, fields)
        metadata = FieldSelectionMetadata(
            fields_returned=len(fields) if fields else len(record),
            field_selection_method="auto" if auto_selected else "requested",
            total_fields_available=len(fields_meta) if fields_meta else None,
            note=(
                f"Smart field selection chose {len(fields)} of "
                f"{len(fields_meta)} available fields."
                if auto_selected and fields_meta
                else "Caller-requested fields used."
            ),
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

    # ── Aggregation ─────────────────────────────────────────────────────────

    #: Recognised aggregation functions for ``aggregate_records`` measures.
    ALLOWED_AGGREGATORS: frozenset[str] = frozenset({
        "sum", "avg", "min", "max", "count", "count_distinct",
        "array_agg", "bool_and", "bool_or",
    })

    @staticmethod
    def _parse_measure_spec(spec: str) -> tuple[str, str]:
        """Split ``'field:agg'`` into ``(field, aggregator)``.

        Defaults to ``"sum"`` when no colon is present.
        """
        if ":" in spec:
            field, agg = spec.rsplit(":", 1)
            return field.strip(), agg.strip()
        return spec.strip(), "sum"

    async def _get_odoo_major_version(self) -> int | None:
        """Return the Odoo major version integer (e.g. 17, 19) or ``None``."""
        try:
            info = await self.server_info()
            serie = info.server_serie  # e.g. "17.0"
            if serie:
                return int(serie.split(".")[0])
        except (OdooError, ValueError, AttributeError):
            pass
        return None

    @tool_schema(AggregateRecordsInput)
    async def aggregate_records(
        self,
        model: str,
        group_by: list[str],
        measures: Optional[list[str]] = None,
        domain: Optional[list[Any]] = None,
        lazy: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
        order: Optional[str] = None,
    ) -> AggregateResult:
        """Group and aggregate records server-side using read_group (Odoo 16-18)
        or formatted_read_group (Odoo 19+).

        Args:
            model: Odoo model technical name (e.g. ``"sale.order"``).
            group_by: Fields to group by (e.g. ``["state", "partner_id"]``).
                Pass an empty list for a global aggregation with no grouping
                (e.g. counting or summing across all matching records).
            measures: Aggregation specs as ``"field:agg"`` strings
                (e.g. ``["amount_total:sum", "id:count"]``). Supported
                aggregators: sum, avg, min, max, count, count_distinct.
            domain: Optional domain filter.
            lazy: When True, only the first group_by level is resolved.
            limit: Max number of groups to return.
            offset: Groups to skip.
            order: Sort order string.

        Returns:
            AggregateResult with groups list and metadata.

        Raises:
            ValueError: When an unsupported aggregator name is used.
        """
        # Validate and parse measure specs
        parsed_measures: list[tuple[str, str]] = []
        if measures:
            for spec in measures:
                field, agg = self._parse_measure_spec(spec)
                if agg not in self.ALLOWED_AGGREGATORS:
                    raise ValueError(
                        f"Unknown aggregator {agg!r} in measure {spec!r}. "
                        f"Allowed: {sorted(self.ALLOWED_AGGREGATORS)}"
                    )
                parsed_measures.append((field, agg))

        domain = domain or []
        odoo_version = await self._get_odoo_major_version()
        use_formatted = odoo_version is not None and odoo_version >= 19

        if use_formatted:
            # Odoo 19+ formatted_read_group
            kwargs: dict[str, Any] = {
                "groupby": group_by,
                "lazy": lazy,
            }
            if parsed_measures:
                kwargs["aggregates"] = [f"{f}:{a}" for f, a in parsed_measures]
            if limit is not None:
                kwargs["limit"] = limit
            if offset:
                kwargs["offset"] = offset
            if order:
                kwargs["order"] = order
            groups = await self._execute(model, "formatted_read_group", [domain], kwargs)
        else:
            # Odoo 16-18 read_group — fields must include group_by columns AND measure specs
            measure_fields = [f"{f}:{a}" for f, a in parsed_measures] if parsed_measures else []
            kwargs = {
                "groupby": group_by,
                "fields": list(group_by) + measure_fields,
                "lazy": lazy,
            }
            if limit is not None:
                kwargs["limit"] = limit
            if offset:
                kwargs["offset"] = offset
            if order:
                kwargs["orderby"] = order
            groups = await self._execute(model, "read_group", [domain], kwargs)

        groups = groups or []
        return AggregateResult(
            groups=list(groups),
            model=model,
            group_by=group_by,
            measures=[f"{f}:{a}" for f, a in parsed_measures],
            count=len(groups),
        )

    # ── Domain Builder ───────────────────────────────────────────────────────

    #: Operators safe to use in Odoo domain triplets.
    SAFE_DOMAIN_OPERATORS: frozenset[str] = frozenset({
        "=", "!=", ">", ">=", "<", "<=",
        "in", "not in",
        "like", "not like", "ilike", "not ilike",
        "=like", "=ilike",
        "child_of", "parent_of",
    })

    @tool_schema(BuildDomainInput)
    async def build_domain(
        self,
        conditions: list[dict[str, Any]],
        logical_operator: str = "and",
    ) -> DomainBuildResult:
        """Build and validate an Odoo domain array from structured conditions.

        Args:
            conditions: List of condition dicts, each with keys ``field``,
                ``operator``, and ``value``.  An empty list returns an empty
                (match-all) domain.
            logical_operator: ``"and"`` (default, uses ``&`` prefix) or
                ``"or"`` (uses ``|`` prefix).

        Returns:
            DomainBuildResult with the domain array, warnings, and validity flag.

        Note:
            Pure function — no Odoo network call is made.
        """
        if not conditions:
            return DomainBuildResult(domain=[], warnings=[], valid=True)

        warnings: list[str] = []
        valid = True
        triplets: list[Any] = []

        for cond in conditions:
            field = cond.get("field", "")
            operator = cond.get("operator", "=")
            value = cond.get("value")
            if operator not in self.SAFE_DOMAIN_OPERATORS:
                warnings.append(
                    f"Unsafe operator {operator!r} on field {field!r}; "
                    f"condition skipped. Allowed: {sorted(self.SAFE_DOMAIN_OPERATORS)}"
                )
                valid = False
                continue
            triplets.append((field, operator, value))

        if not triplets:
            return DomainBuildResult(domain=[], warnings=warnings, valid=valid)

        # Build prefix-notation domain
        prefix_op = "&" if logical_operator.lower() == "and" else "|"
        domain: list[Any] = []
        if len(triplets) > 1:
            domain = [prefix_op] * (len(triplets) - 1) + list(triplets)
        else:
            domain = list(triplets)

        return DomainBuildResult(domain=domain, warnings=warnings, valid=valid)

    # ── Profile & Schema Catalog ─────────────────────────────────────────────

    @tool_schema(GetOdooProfileInput)
    async def get_odoo_profile(
        self,
        include_modules: bool = True,
        module_limit: int = 100,
    ) -> OdooProfileResult:
        """Return a comprehensive Odoo server and environment snapshot.

        Includes server version, transport, database, user context, and the
        list of installed modules (bounded by ``module_limit``).

        Args:
            include_modules: When True (default), queries ``ir.module.module``
                for the installed module list.
            module_limit: Maximum number of installed modules to return
                (capped at 500).

        Returns:
            OdooProfileResult with version, transport, user context, and modules.
        """
        info = await self.server_info()
        transport = await self._ensure_transport()

        # User context
        user_context: dict[str, Any] = {}
        try:
            user_context = await self._execute("res.users", "context_get", []) or {}
        except OdooError as exc:
            self.logger.debug("context_get failed: %s", exc)

        # Installed modules
        installed_modules: list[dict[str, Any]] = []
        if include_modules:
            try:
                cap = min(module_limit, 500)
                installed_modules = await self._execute(
                    "ir.module.module",
                    "search_read",
                    [[("state", "=", "installed")]],
                    {"fields": ["name", "shortdesc", "installed_version"], "limit": cap},
                ) or []
            except OdooError as exc:
                self.logger.debug("module list fetch failed: %s", exc)

        return OdooProfileResult(
            server_version=info.server_version,
            server_serie=info.server_serie,
            odoo_url=self.config.url,
            database=self.config.database,
            uid=transport.uid,
            user_context=user_context,
            transport=info.transport,
            installed_modules=installed_modules,
        )

    @tool_schema(SchemaCatalogInput)
    async def schema_catalog(
        self,
        query: Optional[str] = None,
        models: Optional[list[str]] = None,
        include_fields: bool = False,
        limit: int = 50,
    ) -> SchemaCatalogResult:
        """List Odoo models with optional field metadata.

        Args:
            query: Substring to filter model names or display names.
            models: Explicit list of model technical names to include.
            include_fields: When True, include ``fields_get`` metadata per model.
                **Warning:** each model's field metadata can be 50-200 KB; keep
                ``limit`` small (≤ 10) when using this option to avoid flooding
                the LLM context.
            limit: Maximum models to return (capped at 500).

        Returns:
            SchemaCatalogResult with model list and metadata.
        """
        cap = min(limit, 500)
        domain: list[Any] = []
        if query:
            domain = ["|", ("model", "ilike", query), ("name", "ilike", query)]
        elif models:
            domain = [("model", "in", models)]

        raw_models: list[dict[str, Any]] = await self._execute(
            "ir.model",
            "search_read",
            [domain],
            {"fields": ["model", "name", "info"], "limit": cap},
        ) or []

        result_models: list[dict[str, Any]] = []
        for m in raw_models:
            entry: dict[str, Any] = {
                "model": m.get("model", ""),
                "name": m.get("name", ""),
                "info": m.get("info", ""),
            }
            if include_fields:
                try:
                    entry["fields"] = await self._get_fields_metadata(m["model"])
                except OdooError as exc:
                    entry["fields_error"] = str(exc)
            result_models.append(entry)

        return SchemaCatalogResult(
            models=result_models,
            total=len(result_models),
            include_fields=include_fields,
        )

    # ── Model Introspection & Diagnostics ────────────────────────────────────

    @tool_schema(InspectModelRelationshipsInput)
    async def inspect_model_relationships(
        self,
        model: str,
    ) -> ModelRelationshipsResult:
        """Inspect relational fields and produce create/write hints for a model.

        Args:
            model: Odoo model technical name (e.g. ``"sale.order"``).

        Returns:
            ModelRelationshipsResult grouping fields by relation type with hints.
        """
        fields_meta = await self._get_fields_metadata(model)

        many2one: list[dict[str, Any]] = []
        one2many: list[dict[str, Any]] = []
        many2many: list[dict[str, Any]] = []
        required_fields: list[dict[str, Any]] = []

        for fname, fmeta in fields_meta.items():
            ftype = fmeta.get("type", "")
            info: dict[str, Any] = {
                "name": fname,
                "string": fmeta.get("string", fname),
                "relation": fmeta.get("relation", ""),
                "required": fmeta.get("required", False),
                "readonly": fmeta.get("readonly", False),
            }
            if ftype == "many2one":
                many2one.append(info)
            elif ftype == "one2many":
                one2many.append(info)
            elif ftype == "many2many":
                many2many.append(info)

            if fmeta.get("required") and not fmeta.get("readonly"):
                required_fields.append({"name": fname, "type": ftype, "string": fmeta.get("string", fname)})

        # Build create hints
        hints: list[str] = []
        if required_fields:
            hints.append(
                f"Required non-readonly fields: "
                + ", ".join(f["name"] for f in required_fields)
            )
        if many2one:
            hints.append(
                f"Many2one fields accept an integer id: "
                + ", ".join(f["name"] for f in many2one[:5])
                + ("..." if len(many2one) > 5 else "")
            )
        if one2many:
            hints.append(
                f"One2many fields use ORM commands [(0,0,{{...}}), ...]: "
                + ", ".join(f["name"] for f in one2many[:3])
            )

        return ModelRelationshipsResult(
            model=model,
            many2one=many2one,
            one2many=one2many,
            many2many=many2many,
            required_fields=required_fields,
            create_hints=hints,
        )

    @tool_schema(DiagnoseAccessInput)
    async def diagnose_access(
        self,
        model: str,
        operation: str = "read",
        domain: Optional[list[Any]] = None,
        record_ids: Optional[list[int]] = None,
    ) -> AccessDiagnosisResult:
        """Diagnose ACL and record-rule visibility for a model and operation.

        Args:
            model: Odoo model technical name.
            operation: Operation to check (``"read"``, ``"write"``, ``"create"``,
                or ``"unlink"``).
            domain: Optional domain to check against record rules.
            record_ids: Specific record IDs to check visibility for.

        Returns:
            AccessDiagnosisResult with ACL status, record rules, groups, and
            a human-readable diagnosis string.
        """
        # Check ACL via check_access_rights
        acl_allowed = False
        try:
            acl_allowed = bool(await self._execute(
                model, "check_access_rights", [operation], {"raise_exception": False}
            ))
        except OdooError as exc:
            self.logger.debug("check_access_rights failed for %s: %s", model, exc)

        # Fetch ir.model.access rules for the model
        acl_rules: list[dict[str, Any]] = []
        try:
            acl_rules = await self._execute(
                "ir.model.access",
                "search_read",
                [[("model_id.model", "=", model)]],
                {"fields": ["name", f"perm_{operation}", "group_id", "active"]},
            ) or []
        except OdooError as exc:
            self.logger.debug("ir.model.access query failed: %s", exc)

        # Fetch ir.rule for the model
        record_rules: list[dict[str, Any]] = []
        try:
            record_rules = await self._execute(
                "ir.rule",
                "search_read",
                [[("model_id.model", "=", model)]],
                {"fields": ["name", "domain_force", "global", f"perm_{operation}"]},
            ) or []
        except OdooError as exc:
            self.logger.debug("ir.rule query failed: %s", exc)

        # Fetch user's groups
        user_groups: list[str] = []
        try:
            transport = await self._ensure_transport()
            if transport.uid:
                groups_data = await self._execute(
                    "res.users",
                    "read",
                    [[transport.uid]],
                    {"fields": ["groups_id"]},
                )
                if groups_data:
                    group_ids = groups_data[0].get("groups_id", [])
                    if group_ids:
                        group_records = await self._execute(
                            "res.groups",
                            "read",
                            [group_ids],
                            {"fields": ["full_name"]},
                        )
                        user_groups = [g.get("full_name", "") for g in (group_records or [])]
        except OdooError as exc:
            self.logger.debug("user groups fetch failed: %s", exc)

        # Build diagnosis string
        if acl_allowed:
            diagnosis = f"User has ACL permission to '{operation}' on '{model}'."
            if record_rules:
                diagnosis += f" {len(record_rules)} record rule(s) may further restrict visibility."
        else:
            diagnosis = (
                f"User does NOT have ACL permission to '{operation}' on '{model}'. "
                f"Check ir.model.access rules for this model."
            )

        return AccessDiagnosisResult(
            model=model,
            operation=operation,
            acl_allowed=acl_allowed,
            record_rules=record_rules,
            user_groups=user_groups,
            diagnosis=diagnosis,
        )

    async def health_check(self) -> HealthCheckResult:
        """Return a runtime posture report without making any Odoo network call.

        Reports toolkit version, transport type, connection status, and
        the number of registered tools.

        Returns:
            HealthCheckResult with runtime posture information.
        """
        connected = self._transport is not None and self._transport.uid is not None
        transport_name = (
            self._transport.name if self._transport is not None else self.protocol
        )
        # Use get_tools() for an accurate count of registered async tools
        tool_count = len(self.get_tools())
        return HealthCheckResult(
            toolkit_version="1.0.0",
            transport=str(transport_name),
            connected=connected,
            write_permissions=[],  # read-only; left for future use
            tool_count=tool_count,
        )

    # ── HR Convenience Methods ───────────────────────────────────────────────

    _HR_EMPLOYEE_DEFAULT_FIELDS: list[str] = [
        "id", "display_name", "name", "job_id", "job_title",
        "department_id", "parent_id", "work_email", "work_phone",
        "mobile_phone", "company_id", "active",
    ]

    _HR_LEAVE_DEFAULT_FIELDS: list[str] = [
        "id", "display_name", "name", "employee_id", "holiday_status_id",
        "date_from", "date_to", "number_of_days", "state",
    ]

    @tool_schema(SearchEmployeeInput)
    async def search_employee(
        self,
        name: str,
        limit: int = 20,
    ) -> list[HrEmployee]:
        """Search ``hr.employee`` records by name.

        Args:
            name: Employee name (partial match, case-insensitive).
            limit: Maximum employees to return (default 20).

        Returns:
            List of typed :class:`HrEmployee` instances.

        Raises:
            OdooRPCError: When the HR module is not installed on the target
                instance (caught and re-raised with a clear message).
        """
        try:
            records = await self._execute(
                "hr.employee",
                "search_read",
                [[("name", "ilike", name), ("active", "=", True)]],
                {"fields": self._HR_EMPLOYEE_DEFAULT_FIELDS, "limit": limit},
            )
        except OdooRPCError as exc:
            raise OdooRPCError(
                f"search_employee failed — is the 'hr' module installed? Error: {exc}"
            ) from exc
        return [HrEmployee.model_validate(r) for r in (records or [])]

    @tool_schema(SearchHolidaysInput)
    async def search_holidays(
        self,
        start_date: str,
        end_date: str,
        employee_id: Optional[int] = None,
    ) -> list[HrLeave]:
        """Search ``hr.leave`` (leave requests) within a date range.

        Args:
            start_date: Start of the date range (``YYYY-MM-DD``).
            end_date: End of the date range (``YYYY-MM-DD``).
            employee_id: Optional employee ID to filter results.

        Returns:
            List of typed :class:`HrLeave` instances.

        Raises:
            OdooRPCError: When the HR module is not installed.
        """
        domain: list[Any] = [
            ("date_from", "<=", end_date),
            ("date_to", ">=", start_date),
        ]
        if employee_id is not None:
            domain.append(("employee_id", "=", employee_id))
        try:
            records = await self._execute(
                "hr.leave",
                "search_read",
                [domain],
                {"fields": self._HR_LEAVE_DEFAULT_FIELDS},
            )
        except OdooRPCError as exc:
            raise OdooRPCError(
                f"search_holidays failed — is the 'hr_holidays' module installed? Error: {exc}"
            ) from exc
        return [HrLeave.model_validate(r) for r in (records or [])]

    # ── Phase 2: Diagnostics, Audit & Planning ───────────────────────────────

    #: ORM methods that are read-only (no Odoo data mutation).
    _READ_ONLY_METHODS: frozenset[str] = frozenset({
        "search", "search_count", "search_read", "read",
        "fields_get", "name_get", "name_search", "context_get",
        "read_group", "formatted_read_group",
    })

    #: ORM methods that permanently mutate Odoo data.
    _DESTRUCTIVE_METHODS: frozenset[str] = frozenset({"create", "write", "unlink"})

    #: JSON-2 positional-argument name mapping for common ORM methods.
    _JSON2_ARG_MAP: dict[str, list[str]] = {
        "search_read": ["domain", "fields", "offset", "limit", "order"],
        "search":      ["domain", "offset", "limit", "order"],
        "search_count": ["domain"],
        "read":        ["ids", "fields"],
        "create":      ["vals_list"],
        "write":       ["ids", "vals"],
        "unlink":      ["ids"],
        "fields_get":  ["allfields", "attributes"],
        "name_search": ["name", "args", "operator", "limit"],
    }

    #: Business pack definitions for ``business_pack_report``.
    _BUSINESS_PACKS: dict[str, dict[str, list[str]]] = {
        "sales": {
            "modules": ["sale", "sale_management"],
            "models": ["sale.order", "sale.order.line"],
        },
        "crm": {
            "modules": ["crm"],
            "models": ["crm.lead", "crm.team"],
        },
        "inventory": {
            "modules": ["stock", "stock_account"],
            "models": ["stock.picking", "stock.move"],
        },
        "accounting": {
            "modules": ["account", "account_payment"],
            "models": ["account.move", "account.payment"],
        },
        "hr": {
            "modules": ["hr", "hr_holidays"],
            "models": ["hr.employee", "hr.leave"],
        },
    }

    @tool_schema(DiagnoseOdooCallInput)
    async def diagnose_odoo_call(
        self,
        model: str,
        method: str,
        args: Optional[list[Any]] = None,
        kwargs: Optional[dict[str, Any]] = None,
        transport: str = "auto",
        target_version: Optional[str] = None,
        observed_error: Optional[str] = None,
    ) -> OdooCallDiagnosisResult:
        """Preview and debug an execute_kw call without executing it.

        Validates model name format, classifies method safety, checks transport
        compatibility, and flags Odoo 20 deprecation warnings.

        Args:
            model: Odoo model technical name to validate.
            method: ORM method name to classify.
            args: Positional arguments (for payload shape analysis).
            kwargs: Keyword arguments (for payload shape analysis).
            transport: Transport type context for compatibility checks.
            target_version: Target Odoo version (e.g. ``"20.0"``).
            observed_error: Error message from a previous failed call attempt.

        Returns:
            OdooCallDiagnosisResult with method safety, warnings, and next actions.

        Note:
            Pure function — no Odoo network call is made.
        """
        warnings: list[str] = []
        next_actions: list[str] = []
        corrected_payload: Optional[dict[str, Any]] = None

        # Validate model name format (e.g. "res.partner", not "SELECT * FROM")
        if not re.match(r"^[a-z][a-z0-9_.]*$", model):
            warnings.append(
                f"Model name {model!r} contains invalid characters. "
                "Odoo model names are lowercase with dots (e.g. 'res.partner')."
            )

        # Validate method name format
        if not re.match(r"^[a-z_][a-z0-9_]*$", method):
            warnings.append(
                f"Method name {method!r} contains invalid characters. "
                "ORM method names are lowercase with underscores (e.g. 'search_read')."
            )

        # Classify method safety
        if method in self._READ_ONLY_METHODS:
            method_safety = "read_only"
        elif method in self._DESTRUCTIVE_METHODS:
            method_safety = "destructive"
            warnings.append(
                f"Method {method!r} mutates Odoo data. Ensure you have write permissions."
            )
        elif method.startswith("action_") or method.startswith("_"):
            method_safety = "side_effect"
            warnings.append(
                f"Method {method!r} may trigger business logic side-effects."
            )
        else:
            method_safety = "unknown"
            warnings.append(f"Method {method!r} is not a standard ORM method.")

        # Transport compatibility check
        transport_compat = "ok"
        active_transport = transport if transport != "auto" else (
            self._transport.name if self._transport else "unknown"
        )
        if active_transport == "xmlrpc" and method in {"formatted_read_group"}:
            transport_compat = "error"
            warnings.append(
                f"Method {method!r} is only available via JSON-2 transport "
                "(Odoo 19+). XML-RPC does not support it."
            )
        elif active_transport == "xmlrpc":
            transport_compat = "warning"
            warnings.append(
                "XML-RPC transport detected. Consider migrating to JSON-2 for "
                "better performance and Odoo 19+ compatibility."
            )

        # Odoo 20 deprecation warning
        if target_version and target_version.startswith("20"):
            warnings.append(
                "Odoo 20 has removed XML-RPC support. Migrate to the JSON-2 endpoint "
                "before upgrading."
            )
            next_actions.append("Use generate_json2_payload to preview the JSON-2 equivalent.")

        # Observed error hints
        if observed_error:
            lower_err = observed_error.lower()
            if "access" in lower_err or "right" in lower_err:
                next_actions.append("Run diagnose_access to check ACL/record-rule visibility.")
            if "model" in lower_err and "not found" in lower_err:
                next_actions.append("Use schema_catalog to verify the model name.")
            if "field" in lower_err:
                next_actions.append("Use fields_get to inspect available fields.")

        if not next_actions:
            next_actions.append("Call looks structurally valid. Execute to confirm.")

        # Build a corrected payload suggestion
        if args or kwargs:
            corrected_payload = {
                "model": model,
                "method": method,
                "args": args or [],
                "kwargs": kwargs or {},
            }

        return OdooCallDiagnosisResult(
            model=model,
            method=method,
            method_safety=method_safety,
            transport_compatibility=transport_compat,
            warnings=warnings,
            corrected_payload=corrected_payload,
            next_actions=next_actions,
        )

    @tool_schema(GenerateJson2PayloadInput)
    async def generate_json2_payload(
        self,
        model: str,
        method: str,
        args: Optional[list[Any]] = None,
        kwargs: Optional[dict[str, Any]] = None,
        base_url: Optional[str] = None,
        database: Optional[str] = None,
    ) -> Json2PayloadResult:
        """Translate XML-RPC-style call into a JSON-2 endpoint + named body.

        Args:
            model: Odoo model technical name.
            method: ORM method name.
            args: Positional arguments (XML-RPC style list).
            kwargs: Keyword arguments.
            base_url: Override base URL (defaults to toolkit config).
            database: Override database name (defaults to toolkit config).

        Returns:
            Json2PayloadResult with endpoint, headers, body, and notes.

        Note:
            Pure function — no Odoo network call is made.
        """
        resolved_url = (base_url or self.config.url or "https://your-odoo.example.com").rstrip("/")
        resolved_db = database or self.config.database or "odoo"
        notes: list[str] = []

        # Build endpoint
        endpoint = f"/json/2/{model}/{method}"

        # Build headers
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Map positional args to named params
        named_params: dict[str, Any] = {}
        arg_list = args or []
        kwarg_dict = kwargs or {}

        if method in self._JSON2_ARG_MAP:
            param_names = self._JSON2_ARG_MAP[method]
            for i, val in enumerate(arg_list):
                if i < len(param_names):
                    named_params[param_names[i]] = val
                else:
                    notes.append(
                        f"Extra positional arg[{i}] has no named mapping for '{method}'; "
                        "added as positional."
                    )
        else:
            notes.append(
                f"Method '{method}' has no JSON-2 arg mapping. "
                "Using generic args/kwargs body."
            )
            if arg_list:
                named_params["args"] = arg_list

        # Merge kwargs
        named_params.update(kwarg_dict)

        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": model,
                "method": method,
                **named_params,
            },
        }

        notes.append(f"Full URL: {resolved_url}{endpoint}")
        notes.append(f"Database context: {resolved_db}")
        notes.append("Add Authorization header with a valid API key or session token.")

        return Json2PayloadResult(
            endpoint=endpoint,
            headers=headers,
            body=body,
            notes=notes,
        )

    @tool_schema(ScanAddonsSourceInput)
    async def scan_addons_source(
        self,
        addons_paths: Optional[list[str]] = None,
        max_files: int = 200,
        max_file_bytes: int = 300_000,
    ) -> AddonScanResult:
        """Scan local Odoo addon directories for manifests and risky patterns.

        Uses AST parsing — no addon code is imported or executed.  The
        filesystem walk and AST parsing run in a thread pool to avoid blocking
        the event loop.

        Args:
            addons_paths: Directories to scan. Must be under the server's
                configured allowed roots (path-traversal protection).
            max_files: Maximum Python files to parse (default 200).
            max_file_bytes: Maximum bytes per file (default 300 KB).

        Returns:
            AddonScanResult with discovered addons, model classes, risky methods,
            and any scan warnings.
        """
        return await asyncio.to_thread(
            self._scan_addons_source_sync, addons_paths, max_files, max_file_bytes
        )

    def _scan_addons_source_sync(
        self,
        addons_paths: Optional[list[str]],
        max_files: int,
        max_file_bytes: int,
    ) -> AddonScanResult:
        """Synchronous implementation of scan_addons_source (runs in thread pool)."""
        if not addons_paths:
            return AddonScanResult(
                addons_found=0,
                addons=[],
                warnings=["No addons_paths provided. Specify at least one directory to scan."],
            )

        all_warnings: list[str] = []
        addons: list[dict[str, Any]] = []
        files_parsed = 0
        scan_truncated = False
        risky_method_names = frozenset({"create", "write", "unlink", "sudo"})

        for raw_path in addons_paths:
            try:
                root = Path(raw_path).resolve()
            except (ValueError, OSError) as exc:
                all_warnings.append(f"Invalid path {raw_path!r}: {exc}")
                continue

            if not root.exists() or not root.is_dir():
                all_warnings.append(f"Path does not exist or is not a directory: {root}")
                continue

            # Walk looking for addon manifests
            for entry in root.iterdir():
                # Guard at outer loop so we stop between addons too
                if files_parsed >= max_files:
                    if not scan_truncated:
                        all_warnings.append(
                            f"Reached max_files={max_files} limit. Scan truncated."
                        )
                        scan_truncated = True
                    break
                if not entry.is_dir():
                    continue
                manifest_path = entry / "__manifest__.py"
                openerp_path = entry / "__openerp__.py"
                manifest_file = manifest_path if manifest_path.exists() else (
                    openerp_path if openerp_path.exists() else None
                )
                if not manifest_file:
                    continue

                addon_info: dict[str, Any] = {
                    "name": entry.name,
                    "path": str(entry),
                    "manifest_file": manifest_file.name,
                    "models": [],
                    "risky_methods": [],
                    "security_files": [],
                    "view_files": [],
                    "parse_warnings": [],
                }

                # Parse manifest
                try:
                    manifest_bytes = manifest_file.read_bytes()
                    if len(manifest_bytes) < max_file_bytes:
                        manifest_text = manifest_bytes.decode("utf-8", errors="replace")
                        tree = ast.parse(manifest_text)
                        # Extract manifest dict via literal_eval of first Expr node
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Dict):
                                try:
                                    manifest_data = ast.literal_eval(node.value)
                                    addon_info["manifest_name"] = manifest_data.get("name", entry.name)
                                    addon_info["version"] = manifest_data.get("version", "")
                                    addon_info["depends"] = manifest_data.get("depends", [])
                                except (ValueError, TypeError):
                                    pass
                                break
                except (OSError, SyntaxError) as exc:
                    addon_info["parse_warnings"].append(f"Manifest parse error: {exc}")

                # Scan Python files for model classes and risky methods
                for py_file in entry.rglob("*.py"):
                    if files_parsed >= max_files:
                        if not scan_truncated:
                            all_warnings.append(
                                f"Reached max_files={max_files} limit. Scan truncated."
                            )
                            scan_truncated = True
                        break
                    try:
                        file_size = py_file.stat().st_size
                        if file_size > max_file_bytes:
                            all_warnings.append(
                                f"Skipping large file {py_file.name} ({file_size} bytes)."
                            )
                            continue
                        source = py_file.read_text(encoding="utf-8", errors="replace")
                        tree = ast.parse(source, filename=str(py_file))
                        files_parsed += 1

                        for node in ast.walk(tree):
                            if isinstance(node, ast.ClassDef):
                                # Look for Odoo model class (_name attribute)
                                for body_node in node.body:
                                    if (
                                        isinstance(body_node, ast.Assign)
                                        and any(
                                            isinstance(t, ast.Name) and t.id == "_name"
                                            for t in body_node.targets
                                        )
                                    ):
                                        try:
                                            model_name = ast.literal_eval(body_node.value)
                                            if isinstance(model_name, str):
                                                addon_info["models"].append(model_name)
                                        except (ValueError, TypeError):
                                            pass
                            elif isinstance(node, ast.FunctionDef):
                                if node.name in risky_method_names:
                                    addon_info["risky_methods"].append({
                                        "method": node.name,
                                        "file": py_file.name,
                                        "line": node.lineno,
                                    })
                    except SyntaxError as exc:
                        addon_info["parse_warnings"].append(
                            f"Syntax error in {py_file.name}: {exc}"
                        )
                    except OSError as exc:
                        addon_info["parse_warnings"].append(
                            f"Read error in {py_file.name}: {exc}"
                        )

                # Security files
                for csv_file in entry.rglob("ir.model.access.csv"):
                    addon_info["security_files"].append(str(csv_file.relative_to(entry)))

                # View XML files
                for xml_file in entry.rglob("*.xml"):
                    if "view" in xml_file.name.lower() or "views" in xml_file.parts:
                        addon_info["view_files"].append(str(xml_file.relative_to(entry)))

                addons.append(addon_info)

        return AddonScanResult(
            addons_found=len(addons),
            addons=addons,
            warnings=all_warnings,
        )

    @tool_schema(FitGapReportInput)
    async def fit_gap_report(
        self,
        requirements: list[dict[str, Any]],
        business_context: Optional[dict[str, Any]] = None,
    ) -> FitGapResult:
        """Classify business requirements into fit/gap buckets.

        Args:
            requirements: List of requirement dicts. Each should have at least
                a ``"description"`` key with the requirement text.
            business_context: Optional context metadata (industry, installed
                modules, etc.) to improve classification accuracy.

        Returns:
            FitGapResult with classified requirements, bucket summary, and
            recommended follow-up Odoo calls.

            Classification buckets:

            - ``"standard"`` — covered by a built-in Odoo module
            - ``"configuration"`` — achievable via settings/workflow changes
            - ``"studio"`` — no-code customization (Odoo Studio)
            - ``"custom_module"`` — requires a bespoke addon
            - ``"avoid"`` — anti-pattern (raw SQL, ORM bypass, etc.)
            - ``"unknown"`` — cannot be classified with available context
        """
        # Heuristic keyword classifier
        STANDARD_KEYWORDS = frozenset({
            "sales order", "sale order", "quotation", "invoice", "payment",
            "purchase order", "inventory", "stock", "picking", "delivery",
            "crm", "lead", "opportunity", "employee", "leave", "holiday",
            "payroll", "partner", "contact", "product", "accounting",
            "journal", "report", "track", "manage", "view", "list",
        })
        STUDIO_KEYWORDS = frozenset({
            "custom field", "add field", "new field", "rename field",
            "custom view", "dashboard", "kanban", "form layout",
        })
        CONFIG_KEYWORDS = frozenset({
            "setting", "configure", "enable", "disable", "activate",
            "workflow", "stage", "status", "pipeline", "category",
        })
        AVOID_KEYWORDS = frozenset({
            "delete all", "drop table", "truncate", "raw sql", "direct db",
            "bypass", "hack", "workaround",
        })

        # Optionally fetch live model list for improved classification
        live_models: set[str] = set()
        try:
            catalog = await self.schema_catalog(limit=500)
            live_models = {m["model"] for m in catalog.models}
        except OdooError:
            pass

        classified: list[dict[str, Any]] = []
        summary: dict[str, int] = {
            "standard": 0, "configuration": 0, "studio": 0,
            "custom_module": 0, "avoid": 0, "unknown": 0,
        }
        recommended_calls: set[str] = set()

        for req in requirements:
            desc = str(req.get("description", req.get("text", ""))).lower()
            bucket = "unknown"
            confidence = "low"

            if any(kw in desc for kw in AVOID_KEYWORDS):
                bucket = "avoid"
                confidence = "high"
            elif any(kw in desc for kw in STUDIO_KEYWORDS):
                bucket = "studio"
                confidence = "medium"
            elif any(kw in desc for kw in CONFIG_KEYWORDS):
                bucket = "configuration"
                confidence = "medium"
            elif any(kw in desc for kw in STANDARD_KEYWORDS):
                bucket = "standard"
                confidence = "high"
                recommended_calls.add("schema_catalog(query='sale')")
            else:
                bucket = "custom_module"
                confidence = "low"
                recommended_calls.add("inspect_model_relationships")

            summary[bucket] = summary.get(bucket, 0) + 1
            classified.append({
                **req,
                "classification": bucket,
                "confidence": confidence,
            })

        return FitGapResult(
            requirements=classified,
            summary=summary,
            recommended_calls=sorted(recommended_calls),
        )

    @tool_schema(BusinessPackReportInput)
    async def business_pack_report(
        self,
        pack: str,
    ) -> BusinessPackResult:
        """Report expected modules, models, and live availability for a business pack.

        Args:
            pack: Business pack name — one of ``"sales"``, ``"crm"``,
                ``"inventory"``, ``"accounting"``, or ``"hr"``.

        Returns:
            BusinessPackResult with expected/installed/missing split.

        Raises:
            ValueError: When an unknown pack name is given.
        """
        if pack not in self._BUSINESS_PACKS:
            raise ValueError(
                f"Unknown business pack {pack!r}. "
                f"Supported packs: {sorted(self._BUSINESS_PACKS)}"
            )

        pack_def = self._BUSINESS_PACKS[pack]
        expected_modules = [
            {"name": m, "description": f"{pack.title()} module"} for m in pack_def["modules"]
        ]
        expected_models: list[str] = pack_def["models"]

        # Try live check
        installed: list[str] = []
        missing: list[str] = []
        try:
            profile = await self.get_odoo_profile(include_modules=True, module_limit=500)
            installed_names = {m.get("name", "") for m in profile.installed_modules}
            for mod_name in pack_def["modules"]:
                if mod_name in installed_names:
                    installed.append(mod_name)
                else:
                    missing.append(mod_name)
        except OdooError as exc:
            self.logger.debug("business_pack_report live check failed: %s", exc)

        return BusinessPackResult(
            pack=pack,
            expected_modules=expected_modules,
            expected_models=expected_models,
            installed=installed,
            missing=missing,
        )

    # ── odoo-bin / odoo-cli shell tools (FEAT-240, Module 1) ─────────────────
    # These tools require HITL confirmation (listed in confirming_tools).
    # They only work when the odoo-bin binary is reachable via ODOO_BIN env var
    # or on PATH.  When the binary is absent they return ShellResult(success=False)
    # without raising — never crash toolkit initialisation.

    @tool_schema(OdooShellInstallInput)
    async def odoo_shell_install_module(
        self,
        modules: list[str],
        database: Optional[str] = None,
        upgrade: bool = False,
    ) -> ShellResult:
        """Install (or upgrade) one or more Odoo modules via ``odoo-bin``.

        Uses ``odoo-bin -d <db> -i <modules> --stop-after-init`` (or ``-u``
        for upgrades).  Requires the ``ODOO_BIN`` environment variable to
        point to the binary.  This tool is HITL-gated: confirmation is
        required before execution.

        Args:
            modules: Technical module names to install, e.g. ``['sale', 'stock']``.
            database: Target database; defaults to ``ODOO_TEST_DATABASE``.
            upgrade: When True, upgrade (``-u``) instead of install (``-i``).

        Returns:
            A :class:`ShellResult` with exit code, stdout, and stderr.
        """
        bin_path = odoo_bin_path()
        if not bin_path:
            msg = (
                "odoo_shell_install_module is disabled: ODOO_BIN is not set "
                "and odoo-bin is not on PATH. Set ODOO_BIN to the absolute path "
                "of the odoo-bin executable."
            )
            self.logger.warning(msg)
            return ShellResult(
                success=False,
                returncode=-1,
                message=msg,
                argv=[],
            )

        db = database or default_database()
        if not db:
            msg = "odoo_shell_install_module: no database specified and ODOO_TEST_DATABASE is not set"
            self.logger.error(msg)
            return ShellResult(success=False, returncode=-1, message=msg, argv=[])

        try:
            argv = build_install_argv(bin_path, modules, db, upgrade=upgrade)
        except ValueError as exc:
            msg = f"odoo_shell_install_module: invalid input — {exc}"
            self.logger.error(msg)
            return ShellResult(success=False, returncode=-1, message=msg, argv=[])

        action = "Upgrading" if upgrade else "Installing"
        self.logger.info("%s modules %s on database %s", action, modules, db)
        return await run_odoo_subprocess(argv)

    @tool_schema(OdooShellUpgradeInput)
    async def odoo_shell_upgrade_module(
        self,
        modules: list[str],
        database: Optional[str] = None,
    ) -> ShellResult:
        """Upgrade one or more Odoo modules via ``odoo-bin -u``.

        Convenience wrapper around :meth:`odoo_shell_install_module` with
        ``upgrade=True``.  Requires the ``ODOO_BIN`` environment variable.
        This tool is HITL-gated: confirmation is required before execution.

        Uses a dedicated :class:`~parrot_tools.odoo.shell.OdooShellUpgradeInput`
        schema that omits the ``upgrade`` flag — this tool always upgrades,
        and the LLM cannot accidentally set ``upgrade=False``.

        Args:
            modules: Technical module names to upgrade.
            database: Target database; defaults to ``ODOO_TEST_DATABASE``.

        Returns:
            A :class:`ShellResult` with exit code, stdout, and stderr.
        """
        return await self.odoo_shell_install_module(
            modules=modules,
            database=database,
            upgrade=True,
        )

    @tool_schema(OdooCliCommandInput)
    async def odoo_cli_command(
        self,
        subcommand: str,
        args: Optional[list[str]] = None,
        database: Optional[str] = None,
    ) -> ShellResult:
        """Run a whitelisted ``odoo-bin`` subcommand.

        Allowed subcommands: ``scaffold``, ``populate``, ``db``, ``shell``,
        ``cloc``, ``start``.  All other subcommands are rejected.
        This tool is HITL-gated: confirmation is required before execution.

        Args:
            subcommand: A whitelisted subcommand (see above).
            args: Additional positional arguments forwarded to the subcommand.
            database: Target database; defaults to ``ODOO_TEST_DATABASE``.

        Returns:
            A :class:`ShellResult` with exit code, stdout, and stderr.
        """
        bin_path = odoo_bin_path()
        if not bin_path:
            msg = (
                "odoo_cli_command is disabled: ODOO_BIN is not set and "
                "odoo-bin is not on PATH."
            )
            self.logger.warning(msg)
            return ShellResult(
                success=False,
                returncode=-1,
                message=msg,
                argv=[],
            )

        try:
            validate_subcommand(subcommand)
        except ValueError as exc:
            msg = f"odoo_cli_command: {exc}"
            self.logger.error(msg)
            return ShellResult(success=False, returncode=-1, message=msg, argv=[])

        extra_args = args or []
        for arg in extra_args:
            try:
                validate_token(arg, label="argument")
            except ValueError as exc:
                msg = f"odoo_cli_command: {exc}"
                self.logger.error(msg)
                return ShellResult(success=False, returncode=-1, message=msg, argv=[])

        db = database or default_database()
        argv: list[str] = [bin_path]
        conf = odoo_conf_path()
        if conf:
            argv.extend(["--conf", conf])
        if db:
            argv.extend(["-d", db])
        argv.append(subcommand)
        argv.extend(extra_args)

        self.logger.info("Running odoo-bin %s with args=%s db=%s", subcommand, extra_args, db)
        return await run_odoo_subprocess(argv)


# Re-export common errors for convenience so callers don't need a second import.
__all__ = [
    "OdooToolkit",
    "OdooError",
    "OdooAuthenticationError",
    "OdooConnectionError",
    "OdooRPCError",
]
