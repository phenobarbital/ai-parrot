"""DatasetManager configuration (FEAT-593): persisted datasource descriptors."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SECRET = {"x-secret": True}
FILE_SUFFIXES = (".csv", ".xls", ".xlsx", ".xlsm", ".xlsb", ".parquet")


class _DatasourceBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool = True


class QuerySlugDatasource(_DatasourceBase):
    kind: Literal["query_slug"]
    slug: str
    permanent_filter: dict[str, Any] | None = None


class SqlDatasource(_DatasourceBase):
    kind: Literal["sql"]
    sql: str
    driver: str
    dsn: str | None = Field(default=None, json_schema_extra=_SECRET)
    credentials: dict[str, Any] | None = Field(default=None, json_schema_extra=_SECRET)


class TableDatasource(_DatasourceBase):
    kind: Literal["table"]
    table: str
    driver: str
    dsn: str | None = Field(default=None, json_schema_extra=_SECRET)
    credentials: dict[str, Any] | None = Field(default=None, json_schema_extra=_SECRET)
    strict_schema: bool = True
    permanent_filter: dict[str, Any] | None = None
    allowed_columns: list[str] | None = None


class FileDatasource(_DatasourceBase):
    kind: Literal["file"]
    path: str
    delta_path: str | None = None

    @field_validator("path")
    @classmethod
    def _validate_suffix(cls, value: str) -> str:
        suffix = Path(value).suffix.lower()
        if suffix not in FILE_SUFFIXES:
            raise ValueError(f"Unsupported file suffix {suffix!r}; must be one of {FILE_SUFFIXES}")
        return value

    @model_validator(mode="after")
    def _validate_delta_path(self) -> "FileDatasource":
        if self.delta_path is not None and not self.is_parquet:
            raise ValueError("delta_path is only allowed for .parquet files")
        return self

    @property
    def is_parquet(self) -> bool:
        return Path(self.path).suffix.lower() == ".parquet"

    @property
    def effective_delta_path(self) -> str:
        return self.delta_path or str(Path(self.path).with_suffix(".delta"))


class AirtableDatasource(_DatasourceBase):
    kind: Literal["airtable"]
    base_id: str
    table: str
    view: str | None = None
    api_key: str | None = Field(default=None, json_schema_extra=_SECRET)


class SmartsheetDatasource(_DatasourceBase):
    kind: Literal["smartsheet"]
    sheet_id: str
    access_token: str | None = Field(default=None, json_schema_extra=_SECRET)


class IcebergDatasource(_DatasourceBase):
    kind: Literal["iceberg"]
    table_id: str
    catalog_params: dict[str, Any]
    factory: str = "pandas"
    credentials: dict[str, Any] | None = Field(default=None, json_schema_extra=_SECRET)
    dsn: str | None = Field(default=None, json_schema_extra=_SECRET)


class MongoDatasource(_DatasourceBase):
    kind: Literal["mongo"]
    collection: str
    database: str
    credentials: dict[str, Any] | None = Field(default=None, json_schema_extra=_SECRET)
    dsn: str | None = Field(default=None, json_schema_extra=_SECRET)
    required_filter: bool = True


class DeltaTableDatasource(_DatasourceBase):
    kind: Literal["deltatable"]
    path: str
    table_name: str | None = None
    mode: str = "error"
    credentials: dict[str, Any] | None = Field(default=None, json_schema_extra=_SECRET)


DatasourceSpec = Annotated[
    Union[
        QuerySlugDatasource,
        SqlDatasource,
        TableDatasource,
        FileDatasource,
        AirtableDatasource,
        SmartsheetDatasource,
        IcebergDatasource,
        MongoDatasource,
        DeltaTableDatasource,
    ],
    Field(discriminator="kind"),
]


class DatasetManagerConfig(BaseModel):
    """Constructor flags + the agent-level datasource list (replayed in memory on build)."""

    model_config = ConfigDict(extra="forbid")
    df_prefix: str = "df"
    generate_guide: bool = True
    include_summary_stats: bool = False
    auto_detect_types: bool = True
    usage_rules: str | None = None
    datasources: list[DatasourceSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_names(self) -> "DatasetManagerConfig":
        seen: dict[str, int] = {}
        for source in self.datasources:
            seen[source.name] = seen.get(source.name, 0) + 1
        duplicates = sorted(name for name, count in seen.items() if count > 1)
        if duplicates:
            raise ValueError(f"Duplicate datasource name(s): {', '.join(duplicates)}")
        return self
