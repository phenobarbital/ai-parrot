---
type: Wiki Summary
title: parrot_tools.odoo.models.inputs
id: mod:parrot_tools.odoo.models.inputs
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic input schemas for OdooToolkit tool methods.
relates_to:
- concept: class:parrot_tools.odoo.models.inputs.AggregateRecordsInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.AttachDocumentInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.BuildDomainInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.BusinessPackReportInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.ConfirmSaleOrderInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.CreateInvoiceInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.CreatePartnerInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.CreateQuotationInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.CreateRecordInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.CreateRecordsInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.DeleteRecordInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.DeleteRecordsInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.DiagnoseAccessInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.DiagnoseOdooCallInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.FieldsGetInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.FindPartnerInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.FitGapReportInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.GenerateJson2PayloadInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.GetOdooProfileInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.GetRecordInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.ImportRecordsInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.InspectModelRelationshipsInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.InvoiceLineInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.PostInvoiceInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.QuotationLineInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.RegisterPaymentInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.ScanAddonsSourceInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.SchemaCatalogInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.SearchEmployeeInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.SearchHolidaysInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.SearchRecordsInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.SetBinaryFieldInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.UpdatePartnerContactInfoInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.UpdateRecordInput
  rel: defines
- concept: class:parrot_tools.odoo.models.inputs.UpdateRecordsInput
  rel: defines
---

# `parrot_tools.odoo.models.inputs`

Pydantic input schemas for OdooToolkit tool methods.

Each tool method on :class:`~parrot_tools.odoo.toolkit.OdooToolkit` is
decorated with ``@tool_schema(<InputModel>)`` so the LLM gets a precise
JSON schema for the arguments it can pass.

## Classes

- **`FieldsGetInput(_OdooBaseInput)`**
- **`SearchRecordsInput(_OdooBaseInput)`**
- **`GetRecordInput(_OdooBaseInput)`**
- **`CreateRecordInput(_OdooBaseInput)`**
- **`CreateRecordsInput(_OdooBaseInput)`**
- **`UpdateRecordInput(_OdooBaseInput)`**
- **`UpdateRecordsInput(_OdooBaseInput)`**
- **`DeleteRecordInput(_OdooBaseInput)`**
- **`DeleteRecordsInput(_OdooBaseInput)`**
- **`ImportRecordsInput(_OdooBaseInput)`** — Idempotent upsert via Odoo's ``load`` (supports external IDs).
- **`FindPartnerInput(_OdooBaseInput)`**
- **`CreatePartnerInput(_OdooBaseInput)`**
- **`UpdatePartnerContactInfoInput(_OdooBaseInput)`**
- **`QuotationLineInput(_OdooBaseInput)`**
- **`CreateQuotationInput(_OdooBaseInput)`**
- **`ConfirmSaleOrderInput(_OdooBaseInput)`**
- **`InvoiceLineInput(_OdooBaseInput)`**
- **`CreateInvoiceInput(_OdooBaseInput)`**
- **`PostInvoiceInput(_OdooBaseInput)`**
- **`RegisterPaymentInput(_OdooBaseInput)`**
- **`SetBinaryFieldInput(_OdooBaseInput)`**
- **`AttachDocumentInput(_OdooBaseInput)`**
- **`AggregateRecordsInput(_OdooBaseInput)`** — Input schema for ``aggregate_records`` — server-side grouping via read_group.
- **`BuildDomainInput(_OdooBaseInput)`** — Input schema for ``build_domain`` — structured domain construction.
- **`GetOdooProfileInput(_OdooBaseInput)`** — Input schema for ``get_odoo_profile`` — comprehensive server snapshot.
- **`SchemaCatalogInput(_OdooBaseInput)`** — Input schema for ``schema_catalog`` — bounded model catalog.
- **`InspectModelRelationshipsInput(_OdooBaseInput)`** — Input schema for ``inspect_model_relationships``.
- **`DiagnoseAccessInput(_OdooBaseInput)`** — Input schema for ``diagnose_access`` — ACL and record-rule diagnosis.
- **`SearchEmployeeInput(_OdooBaseInput)`** — Input schema for ``search_employee``.
- **`SearchHolidaysInput(_OdooBaseInput)`** — Input schema for ``search_holidays`` — leave/holiday queries.
- **`DiagnoseOdooCallInput(_OdooBaseInput)`** — Input schema for ``diagnose_odoo_call`` — call preview/debug.
- **`GenerateJson2PayloadInput(_OdooBaseInput)`** — Input schema for ``generate_json2_payload`` — JSON-2 request preview.
- **`ScanAddonsSourceInput(_OdooBaseInput)`** — Input schema for ``scan_addons_source`` — local addon scanning.
- **`FitGapReportInput(_OdooBaseInput)`** — Input schema for ``fit_gap_report`` — requirement classification.
- **`BusinessPackReportInput(_OdooBaseInput)`** — Input schema for ``business_pack_report``.
