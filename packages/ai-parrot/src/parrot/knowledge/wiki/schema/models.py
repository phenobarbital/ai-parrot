"""Schema-plane records and configuration (FEAT-600 M1)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from parrot.bots.database.models import TableMetadata


class SchemaSourceConfig(BaseModel):
    """One declared SQL source. Never holds a DSN — only the env-var NAME (spec G7)."""

    alias: str = Field(..., description="Origin alias; defaults to the dialect at add-source time")
    dialect: str = Field(..., description="Key of _SQLGLOT_DIALECT_MAP (toolkits/sql.py:45)")
    dsn_env: str = Field(..., description="Environment variable NAME holding the DSN")
    allowed_schemas: list[str] = Field(default_factory=lambda: ["public"])
    tables: list[str] | None = Field(default=None, description='Optional "schema.table" allowlist')
    include_samples: list[str] = Field(default_factory=list, description="Per-table sample_data allowlist")
    ddl_paths: list[str] = Field(default_factory=list, description="Repo-relative .sql paths/globs for ingest-ddl --changed")


class SchemaPlaneConfig(BaseModel):
    """`schema:` block of .parrot/wiki.json (mirrors DecisionConfig on WikiProjectConfig)."""

    enabled: bool = True
    sources: dict[str, SchemaSourceConfig] = Field(default_factory=dict)
    stale_after_days: dict[int, int] = Field(default_factory=lambda: {1: 30, 2: 14, 3: 7})


class ColumnRecord(BaseModel):
    """Row of the `columns` side table."""

    table_id: str
    ordinal: int
    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    comment: str | None = None
    is_primary_key: bool = False
    fk_target: str | None = Field(default=None, description='"table:<origin>/<schema>.<table>.<column>"')


class TableRecord(BaseModel):
    """TableMetadata plus the plane-only identity fields."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    origin: str
    dialect: str
    metadata: TableMetadata
    content_hash: str
    introspected_at: str = Field(..., description="ISO-8601 UTC")
    defined_in: list[str] = Field(default_factory=list, description="file:<rel_path> ids")


class LookupResult(BaseModel):
    """Payload of wiki_schema_lookup / `schema lookup`."""

    page_id: str
    frontmatter: dict[str, Any]
    ddl: str
    columns: list[ColumnRecord]
    relations: list[dict[str, Any]]
    annotations: list[dict[str, Any]]
    age_days: float
    stale: bool


class SyncReport(BaseModel):
    """Result of sync / ingest_ddl."""

    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)
    parse_errors: dict[str, str] = Field(default_factory=dict)
