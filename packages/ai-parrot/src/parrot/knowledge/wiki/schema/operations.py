"""Framework-free schema-plane operations (FEAT-540 M3)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.operations import OperationResult


class SchemaLookupInput(BaseModel):
    """Arguments for ``wiki_schema_lookup``."""

    ref: str = Field(
        ...,
        description="table:<origin>/<schema>.<table>, bare <origin>:<schema>.<table>, or <schema>.<table>",
    )


class SchemaSearchInput(BaseModel):
    """Arguments for ``wiki_schema_search``."""

    query: str = Field(..., description="Words to match in table names, column names and comments")
    limit: int = Field(default=20, ge=1, le=100)


class SchemaNeighborsInput(BaseModel):
    """Arguments for ``wiki_schema_neighbors``."""

    ref: str = Field(..., description="Table reference (same forms as lookup)")
    depth: int = Field(default=1, ge=1, le=4)


class SchemaSourcesInput(BaseModel):
    """Arguments for ``wiki_schema_sources``."""


def _lookup_text(result: Any) -> str:
    """Render a compact lookup response containing DDL and its columns."""
    columns = ["| Column | Type | Nullable |", "| --- | --- | --- |"]
    columns.extend(
        f"| {column.name} | {column.data_type} | {'yes' if column.nullable else 'no'} |" for column in result.columns
    )
    return f"## DDL\n\n{result.ddl}\n\n## Columns\n\n" + "\n".join(columns)


async def op_schema_lookup(store: Any, params: SchemaLookupInput, **context: Any) -> OperationResult:
    """Look up one schema table without database introspection."""
    try:
        result = await context["service"].lookup(params.ref, annotation_store=context.get("annotation_store"))
    except (KeyError, ValueError) as exc:
        return OperationResult(text=str(exc), is_error=True)
    if isinstance(result, list):
        return OperationResult(data={"candidates": result, "status": "ambiguous"})
    payload = result.model_dump(mode="json")
    payload["text"] = _lookup_text(result)
    return OperationResult(data=payload)


async def op_schema_search(store: Any, params: SchemaSearchInput, **context: Any) -> OperationResult:
    """Search stored schema records."""
    try:
        return OperationResult(data={"result": await context["service"].search(params.query, limit=params.limit)})
    except (KeyError, ValueError) as exc:
        return OperationResult(text=str(exc), is_error=True)


async def op_schema_neighbors(store: Any, params: SchemaNeighborsInput, **context: Any) -> OperationResult:
    """Return foreign-key paths from a table."""
    try:
        return OperationResult(data={"result": await context["service"].neighbors(params.ref, depth=params.depth)})
    except (KeyError, ValueError) as exc:
        return OperationResult(text=str(exc), is_error=True)


async def op_schema_sources(store: Any, params: SchemaSourcesInput, **context: Any) -> OperationResult:
    """List configured schema sources without resolving their DSNs."""
    try:
        return OperationResult(data={"result": await context["service"].sources()})
    except (KeyError, ValueError) as exc:
        return OperationResult(text=str(exc), is_error=True)
