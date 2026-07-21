---
type: Wiki Summary
title: parrot_tools.odoo.models.envelopes
id: mod:parrot_tools.odoo.models.envelopes
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic result envelopes for OdooToolkit operations.
relates_to:
- concept: class:parrot_tools.odoo.models.envelopes.AccessDiagnosisResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.AddonScanResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.AggregateResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.BinaryFieldResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.BulkCreateResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.BulkDeleteResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.BulkUpdateResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.BusinessPackResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.CreateResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.DeleteResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.DomainBuildResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.FieldSelectionMetadata
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.FitGapResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.HealthCheckResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.ImportResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.Json2PayloadResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.ModelInfo
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.ModelOperations
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.ModelRelationshipsResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.ModelsResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.OdooCallDiagnosisResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.OdooProfileResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.RecordResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.SchemaCatalogResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.SearchResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.ServerInfoResult
  rel: defines
- concept: class:parrot_tools.odoo.models.envelopes.UpdateResult
  rel: defines
---

# `parrot_tools.odoo.models.envelopes`

Pydantic result envelopes for OdooToolkit operations.

Envelopes wrap raw Odoo responses with consistent metadata so agents always
receive a structured, JSON-serialisable payload regardless of the underlying
Odoo model.

## Classes

- **`FieldSelectionMetadata(BaseModel)`** — Metadata describing how the returned field set was chosen.
- **`ModelOperations(BaseModel)`** — ACL summary for a given Odoo model, from the connected user's perspective.
- **`ModelInfo(BaseModel)`** — One entry in a list_models response.
- **`ModelsResult(BaseModel)`** — Result envelope for ``list_models``.
- **`SearchResult(BaseModel)`** — Result envelope for ``search_records``.
- **`RecordResult(BaseModel)`** — Result envelope for ``get_record``.
- **`CreateResult(BaseModel)`** — Result envelope for ``create_record``.
- **`BulkCreateResult(BaseModel)`** — Result envelope for ``create_records``.
- **`UpdateResult(BaseModel)`** — Result envelope for ``update_record``.
- **`BulkUpdateResult(BaseModel)`** — Result envelope for ``update_records``.
- **`DeleteResult(BaseModel)`** — Result envelope for ``delete_record``.
- **`BulkDeleteResult(BaseModel)`** — Result envelope for ``delete_records``.
- **`ImportResult(BaseModel)`** — Result envelope for ``import_records`` (Odoo's ``load`` semantics).
- **`BinaryFieldResult(BaseModel)`** — Result envelope for binary field uploads.
- **`ServerInfoResult(BaseModel)`** — Result envelope for ``server_info``.
- **`AggregateResult(BaseModel)`** — Result envelope for ``aggregate_records``.
- **`DomainBuildResult(BaseModel)`** — Result envelope for ``build_domain``.
- **`OdooProfileResult(BaseModel)`** — Result envelope for ``get_odoo_profile``.
- **`SchemaCatalogResult(BaseModel)`** — Result envelope for ``schema_catalog``.
- **`ModelRelationshipsResult(BaseModel)`** — Result envelope for ``inspect_model_relationships``.
- **`AccessDiagnosisResult(BaseModel)`** — Result envelope for ``diagnose_access``.
- **`HealthCheckResult(BaseModel)`** — Result envelope for ``health_check`` — runtime posture report.
- **`OdooCallDiagnosisResult(BaseModel)`** — Result envelope for ``diagnose_odoo_call``.
- **`Json2PayloadResult(BaseModel)`** — Result envelope for ``generate_json2_payload``.
- **`AddonScanResult(BaseModel)`** — Result envelope for ``scan_addons_source``.
- **`FitGapResult(BaseModel)`** — Result envelope for ``fit_gap_report``.
- **`BusinessPackResult(BaseModel)`** — Result envelope for ``business_pack_report``.
