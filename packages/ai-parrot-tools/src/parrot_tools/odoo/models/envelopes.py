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
