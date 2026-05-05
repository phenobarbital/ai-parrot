"""Pydantic result envelopes for OdooToolkit operations.

Envelopes wrap raw Odoo responses with consistent metadata so agents always
receive a structured, JSON-serialisable payload regardless of the underlying
Odoo model.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class FieldSelectionMetadata(BaseModel):
    """Metadata describing how the returned field set was chosen."""

    fields_returned: int = Field(..., description="Number of fields included in the record")
    field_selection_method: str = Field(
        ..., description="How fields were chosen: 'requested', 'all', or 'auto'"
    )
    total_fields_available: Optional[int] = Field(
        default=None, description="Total fields exposed by the Odoo model, when known"
    )
    note: Optional[str] = Field(default=None, description="Free-form note about the selection")


class ModelOperations(BaseModel):
    """ACL summary for a given Odoo model, from the connected user's perspective."""

    read: bool = False
    write: bool = False
    create: bool = False
    unlink: bool = False


class ModelInfo(BaseModel):
    """One entry in a list_models response."""

    model: str = Field(..., description="Technical name (e.g. 'res.partner')")
    name: str = Field(..., description="Human-readable name")
    operations: Optional[ModelOperations] = None


class ModelsResult(BaseModel):
    """Result envelope for ``list_models``."""

    models: list[ModelInfo] = Field(default_factory=list)
    total: Optional[int] = None
    error: Optional[str] = None


class SearchResult(BaseModel):
    """Result envelope for ``search_records``."""

    records: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    limit: Optional[int] = None
    offset: int = 0
    model: str
    fields: Optional[list[str]] = None


class RecordResult(BaseModel):
    """Result envelope for ``get_record``."""

    record: dict[str, Any]
    model: str
    metadata: Optional[FieldSelectionMetadata] = None

    model_config = ConfigDict(protected_namespaces=())


class CreateResult(BaseModel):
    """Result envelope for ``create_record``."""

    success: bool = True
    record: dict[str, Any] = Field(default_factory=dict)
    record_id: int
    model: str
    message: str = ""


class BulkCreateResult(BaseModel):
    """Result envelope for ``create_records``."""

    success: bool = True
    created_ids: list[int] = Field(default_factory=list)
    count: int = 0
    model: str
    message: str = ""


class UpdateResult(BaseModel):
    """Result envelope for ``update_record``."""

    success: bool = True
    record: dict[str, Any] = Field(default_factory=dict)
    record_id: int
    model: str
    message: str = ""


class BulkUpdateResult(BaseModel):
    """Result envelope for ``update_records``."""

    success: bool = True
    updated_ids: list[int] = Field(default_factory=list)
    count: int = 0
    model: str
    message: str = ""


class DeleteResult(BaseModel):
    """Result envelope for ``delete_record``."""

    success: bool = True
    deleted_id: int
    model: str
    message: str = ""


class BulkDeleteResult(BaseModel):
    """Result envelope for ``delete_records``."""

    success: bool = True
    deleted_ids: list[int] = Field(default_factory=list)
    count: int = 0
    model: str
    message: str = ""


class ImportResult(BaseModel):
    """Result envelope for ``import_records`` (Odoo's ``load`` semantics)."""

    success: bool = True
    imported: int = 0
    ids: list[int] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    model: str
    message: str = ""


class BinaryFieldResult(BaseModel):
    """Result envelope for binary field uploads."""

    success: bool = True
    model: str
    record_id: int
    field: str
    size_bytes: int = 0
    message: str = ""


class ServerInfoResult(BaseModel):
    """Result envelope for ``server_info``."""

    server_version: str = ""
    server_serie: str = ""
    protocol_version: Optional[int] = None
    server_version_info: list[Any] = Field(default_factory=list)
    odoo_url: str = ""
    database: str = ""
    connected: bool = False
    transport: str = "unknown"
    uid: Optional[int] = None


# ── Phase 1: Introspection & Smart Tool Result Envelopes ────────────────────


class AggregateResult(BaseModel):
    """Result envelope for ``aggregate_records``."""

    groups: list[dict[str, Any]] = Field(default_factory=list)
    model: str
    group_by: list[str]
    measures: list[str] = Field(default_factory=list)
    count: int = 0

    model_config = ConfigDict(protected_namespaces=())


class DomainBuildResult(BaseModel):
    """Result envelope for ``build_domain``."""

    domain: list[Any] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    valid: bool = True


class OdooProfileResult(BaseModel):
    """Result envelope for ``get_odoo_profile``."""

    server_version: str = ""
    server_serie: str = ""
    odoo_url: str = ""
    database: str = ""
    uid: Optional[int] = None
    user_context: dict[str, Any] = Field(default_factory=dict)
    transport: str = "unknown"
    installed_modules: list[dict[str, Any]] = Field(default_factory=list)


class SchemaCatalogResult(BaseModel):
    """Result envelope for ``schema_catalog``."""

    models: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    include_fields: bool = False


class ModelRelationshipsResult(BaseModel):
    """Result envelope for ``inspect_model_relationships``."""

    model: str
    many2one: list[dict[str, Any]] = Field(default_factory=list)
    one2many: list[dict[str, Any]] = Field(default_factory=list)
    many2many: list[dict[str, Any]] = Field(default_factory=list)
    required_fields: list[dict[str, Any]] = Field(default_factory=list)
    create_hints: list[str] = Field(default_factory=list)

    model_config = ConfigDict(protected_namespaces=())


class AccessDiagnosisResult(BaseModel):
    """Result envelope for ``diagnose_access``."""

    model: str
    operation: str
    acl_allowed: bool = False
    record_rules: list[dict[str, Any]] = Field(default_factory=list)
    user_groups: list[str] = Field(default_factory=list)
    diagnosis: str = ""

    model_config = ConfigDict(protected_namespaces=())


class HealthCheckResult(BaseModel):
    """Result envelope for ``health_check`` — runtime posture report."""

    toolkit_version: str = "1.0.0"
    transport: str = "unknown"
    connected: bool = False
    write_permissions: list[str] = Field(default_factory=list)
    tool_count: int = 0


# ── Phase 2: Diagnostics, Audit & Planning Result Envelopes ────────────────


class OdooCallDiagnosisResult(BaseModel):
    """Result envelope for ``diagnose_odoo_call``."""

    model: str
    method: str
    method_safety: str = "unknown"  # "read_only" | "destructive" | "side_effect" | "unknown"
    transport_compatibility: str = "ok"  # "ok" | "warning" | "error"
    warnings: list[str] = Field(default_factory=list)
    corrected_payload: Optional[dict[str, Any]] = None
    next_actions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(protected_namespaces=())


class Json2PayloadResult(BaseModel):
    """Result envelope for ``generate_json2_payload``."""

    endpoint: str = ""  # e.g. "/json/2/res.partner/search_read"
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class AddonScanResult(BaseModel):
    """Result envelope for ``scan_addons_source``."""

    addons_found: int = 0
    addons: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FitGapResult(BaseModel):
    """Result envelope for ``fit_gap_report``."""

    requirements: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    recommended_calls: list[str] = Field(default_factory=list)


class BusinessPackResult(BaseModel):
    """Result envelope for ``business_pack_report``."""

    pack: str
    expected_modules: list[dict[str, Any]] = Field(default_factory=list)
    expected_models: list[str] = Field(default_factory=list)
    installed: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
