---
type: Wiki Entity
title: OdooToolkit
id: class:parrot_tools.odoo.toolkit.OdooToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit exposing Odoo ERP CRUD + business helpers as agent tools.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# OdooToolkit

Defined in [`parrot_tools.odoo.toolkit`](../summaries/mod:parrot_tools.odoo.toolkit.md).

```python
class OdooToolkit(AbstractToolkit)
```

Toolkit exposing Odoo ERP CRUD + business helpers as agent tools.

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

## Methods

- `async def stop(self) -> None` — Release the transport's session if any.
- `async def cleanup(self) -> None`
- `async def server_info(self) -> ServerInfoResult` — Return Odoo server version, transport, and connection status.
- `async def list_models(self) -> ModelsResult` — List the Odoo models the toolkit knows about with the user's ACLs.
- `async def fields_get(self, model: str, attributes: Optional[list[str]]=None) -> dict[str, Any]` — Return the field definitions for an Odoo model.
- `async def search_records(self, model: str, domain: Optional[list[Any]]=None, fields: Optional[list[str]]=None, limit: int=100, offset: int=0, order: Optional[str]=None) -> SearchResult` — Search records in any Odoo model with domain filters & pagination.
- `async def get_record(self, model: str, record_id: int, fields: Optional[list[str]]=None) -> RecordResult` — Read a single record by id.
- `async def create_record(self, model: str, values: dict[str, Any]) -> CreateResult` — Create one record and return the new id + a summary of the record.
- `async def create_records(self, model: str, vals_list: list[dict[str, Any]]) -> BulkCreateResult` — Create multiple records in a single round-trip (max 1000).
- `async def update_record(self, model: str, record_id: int, values: dict[str, Any]) -> UpdateResult` — Update a single record by id.
- `async def update_records(self, model: str, record_ids: list[int], values: dict[str, Any]) -> BulkUpdateResult` — Apply the same patch to many records in one call (max 1000).
- `async def delete_record(self, model: str, record_id: int) -> DeleteResult` — Delete a single record by id.
- `async def delete_records(self, model: str, record_ids: list[int]) -> BulkDeleteResult` — Delete multiple records in one call (max 1000).
- `async def import_records(self, model: str, fields: list[str], data: list[list[Any]], context: Optional[dict[str, Any]]=None) -> ImportResult` — Idempotent upsert via Odoo's ``load`` (use 'id' field for external IDs).
- `async def find_partner(self, name: Optional[str]=None, email: Optional[str]=None, phone: Optional[str]=None, vat: Optional[str]=None, is_company: Optional[bool]=None, limit: int=10) -> list[ResPartner]` — Search ``res.partner`` with friendly arguments and typed results.
- `async def create_partner(self, name: str, is_company: bool=False, email: Optional[str]=None, phone: Optional[str]=None, mobile: Optional[str]=None, website: Optional[str]=None, street: Optional[str]=None, street2: Optional[str]=None, city: Optional[str]=None, zip: Optional[str]=None, state_id: Optional[int]=None, country_id: Optional[int]=None, parent_id: Optional[int]=None, vat: Optional[str]=None, ref: Optional[str]=None, customer_rank: Optional[int]=None, supplier_rank: Optional[int]=None, extra: Optional[dict[str, Any]]=None) -> ResPartner` — Create a ``res.partner`` and return it as a typed model.
- `async def update_partner_contact_info(self, partner_id: int, email: Optional[str]=None, phone: Optional[str]=None, mobile: Optional[str]=None, website: Optional[str]=None, street: Optional[str]=None, street2: Optional[str]=None, city: Optional[str]=None, zip: Optional[str]=None, state_id: Optional[int]=None, country_id: Optional[int]=None) -> ResPartner` — Update contact / address fields on an existing partner.
- `async def create_quotation(self, partner_id: int, order_lines: list[dict[str, Any]], date_order: Optional[str]=None, validity_date: Optional[str]=None, pricelist_id: Optional[int]=None, payment_term_id: Optional[int]=None, user_id: Optional[int]=None, team_id: Optional[int]=None, company_id: Optional[int]=None, client_order_ref: Optional[str]=None, extra: Optional[dict[str, Any]]=None) -> SaleOrder` — Create a draft ``sale.order`` (quotation) with one or more lines.
- `async def confirm_sale_order(self, sale_order_id: int) -> SaleOrder` — Confirm a draft quotation, transitioning it to the 'sale' state.
- `async def create_invoice(self, partner_id: int, invoice_lines: list[dict[str, Any]], move_type: Literal['out_invoice', 'in_invoice', 'out_refund', 'in_refund']='out_invoice', invoice_date: Optional[str]=None, invoice_date_due: Optional[str]=None, journal_id: Optional[int]=None, currency_id: Optional[int]=None, invoice_origin: Optional[str]=None, ref: Optional[str]=None, extra: Optional[dict[str, Any]]=None) -> AccountMove` — Create a draft invoice / vendor bill on ``account.move``.
- `async def post_invoice(self, invoice_id: int) -> AccountMove` — Post a draft invoice (Odoo 13+: ``action_post``).
- `async def register_payment(self, invoice_id: int, journal_id: int, amount: Optional[float]=None, payment_date: Optional[str]=None, payment_method_line_id: Optional[int]=None, communication: Optional[str]=None) -> dict[str, Any]` — Register a payment on a posted invoice via ``account.payment.register``.
- `async def set_binary_field(self, model: str, record_id: int, field_name: str, source: str) -> BinaryFieldResult` — Upload bytes (URL or base64 string) into a Binary/Image field.
- `async def attach_document(self, res_model: str, res_id: int, name: str, source: str, mimetype: Optional[str]=None, description: Optional[str]=None) -> BinaryFieldResult` — Create an ``ir.attachment`` linked to ``res_model``/``res_id``.
- `async def aggregate_records(self, model: str, group_by: list[str], measures: Optional[list[str]]=None, domain: Optional[list[Any]]=None, lazy: bool=False, limit: Optional[int]=None, offset: int=0, order: Optional[str]=None) -> AggregateResult` — Group and aggregate records server-side using read_group (Odoo 16-18)
- `async def build_domain(self, conditions: list[dict[str, Any]], logical_operator: str='and') -> DomainBuildResult` — Build and validate an Odoo domain array from structured conditions.
- `async def get_odoo_profile(self, include_modules: bool=True, module_limit: int=100) -> OdooProfileResult` — Return a comprehensive Odoo server and environment snapshot.
- `async def schema_catalog(self, query: Optional[str]=None, models: Optional[list[str]]=None, include_fields: bool=False, limit: int=50) -> SchemaCatalogResult` — List Odoo models with optional field metadata.
- `async def inspect_model_relationships(self, model: str) -> ModelRelationshipsResult` — Inspect relational fields and produce create/write hints for a model.
- `async def diagnose_access(self, model: str, operation: str='read', domain: Optional[list[Any]]=None, record_ids: Optional[list[int]]=None) -> AccessDiagnosisResult` — Diagnose ACL and record-rule visibility for a model and operation.
- `async def health_check(self) -> HealthCheckResult` — Return a runtime posture report without making any Odoo network call.
- `async def search_employee(self, name: str, limit: int=20) -> list[HrEmployee]` — Search ``hr.employee`` records by name.
- `async def search_holidays(self, start_date: str, end_date: str, employee_id: Optional[int]=None) -> list[HrLeave]` — Search ``hr.leave`` (leave requests) within a date range.
- `async def diagnose_odoo_call(self, model: str, method: str, args: Optional[list[Any]]=None, kwargs: Optional[dict[str, Any]]=None, transport: str='auto', target_version: Optional[str]=None, observed_error: Optional[str]=None) -> OdooCallDiagnosisResult` — Preview and debug an execute_kw call without executing it.
- `async def generate_json2_payload(self, model: str, method: str, args: Optional[list[Any]]=None, kwargs: Optional[dict[str, Any]]=None, base_url: Optional[str]=None, database: Optional[str]=None) -> Json2PayloadResult` — Translate XML-RPC-style call into a JSON-2 endpoint + named body.
- `async def scan_addons_source(self, addons_paths: Optional[list[str]]=None, max_files: int=200, max_file_bytes: int=300000) -> AddonScanResult` — Scan local Odoo addon directories for manifests and risky patterns.
- `async def fit_gap_report(self, requirements: list[dict[str, Any]], business_context: Optional[dict[str, Any]]=None) -> FitGapResult` — Classify business requirements into fit/gap buckets.
- `async def business_pack_report(self, pack: str) -> BusinessPackResult` — Report expected modules, models, and live availability for a business pack.
- `async def odoo_shell_install_module(self, modules: list[str], database: Optional[str]=None, upgrade: bool=False) -> ShellResult` — Install (or upgrade) one or more Odoo modules via ``odoo-bin``.
- `async def odoo_shell_upgrade_module(self, modules: list[str], database: Optional[str]=None) -> ShellResult` — Upgrade one or more Odoo modules via ``odoo-bin -u``.
- `async def odoo_cli_command(self, subcommand: str, args: Optional[list[str]]=None, database: Optional[str]=None) -> ShellResult` — Run a whitelisted ``odoo-bin`` subcommand.
