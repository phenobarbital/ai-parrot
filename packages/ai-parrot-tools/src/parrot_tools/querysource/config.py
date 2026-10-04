"""QuerysourceToolkit configuration model (FEAT-593)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuerysourceToolkitConfig(BaseModel):
    """Operator-facing Querysource configuration; ``programs`` is the tenant scope."""

    model_config = ConfigDict(extra="forbid")
    programs: list[str] | None = Field(default=None, description="Allowed program slugs (tenants); empty = all")
    allow_write: bool = False
    allow_raw_sql: bool = False
    allow_external_sources: bool = True
    include_sql: bool = True
    max_rows: int = 200
    forced_conditions: dict[str, Any] | None = None
    dsn: str | None = Field(default=None, json_schema_extra={"x-secret": True})
    multiquery_timeout: float = 600.0
