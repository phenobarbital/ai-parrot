"""Pure Pydantic contracts for common-field filtering (FEAT-225 Module 1).

These are I/O-free data models. They carry no driver, DSN, or SQL
information — the FilterCompiler and DatasetManager methods consume them.

Classes:
    ValuesSource: Specifies where to obtain distinct values for a filter.
    FilterDefinition: Declarative filter definition stored on a DatasetManager.
    FilterCondition: A single applied condition within a filter request.
    FilterResult: Per-run outcome recording applied/skipped datasets.

Note: ``from __future__ import annotations`` is intentionally omitted here to
ensure Pydantic v2 can resolve Literal annotations at class definition time
without requiring a manual ``model_rebuild()`` call.
"""
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

FilterKind = Literal["categorical", "numeric", "temporal", "text", "spatial"]

FilterOp = Literal["eq", "ne", "in", "not_in", "range", "radius"]

# Operators that are valid only for specific kinds.
_SPATIAL_ONLY_OPS: frozenset = frozenset({"radius"})
_NUMERIC_TEMPORAL_OPS: frozenset = frozenset({"range"})
_EQUALITY_OPS: frozenset = frozenset({"eq", "ne", "in", "not_in"})
# Kinds that accept equality/range operators (non-spatial).
_NON_SPATIAL_KINDS: frozenset = frozenset({"categorical", "numeric", "temporal", "text"})


class ValuesSource(BaseModel):
    """Specifies where to obtain the distinct values for a frontend combo.

    At most one of ``query_slug``, ``column``, or ``dataset`` is typically
    provided. All are optional; when present they are used by
    ``DatasetManager.get_filter_values`` to locate the value list.

    Attributes:
        query_slug: Named query slug whose result set provides the values.
        column: Column name to run a DISTINCT query against.
        dataset: Restrict value inference to a single named dataset.
    """

    query_slug: Optional[str] = None
    column: Optional[str] = None
    dataset: Optional[str] = None


class FilterDefinition(BaseModel):
    """A declarative common-field filter definition stored on a DatasetManager.

    Instances are validated at ``define_filters()`` time, before any I/O.
    The ``model_validator`` enforces op⇄kind compatibility.

    Attributes:
        name: Stable filter identifier used in requests and the schema.
        columns: Column(s) targeted; spatial filters may carry [lat, lng]
            or a single geometry column.
        kind: Semantic kind of the filter (categorical, numeric, temporal,
            text, or spatial).
        ops: Allowed filter operators for this definition (at least one).
        required: When True, ``apply_filters`` raises ``ValueError`` if a
            target dataset lacks the column(s). When False (default),
            missing-column datasets are silently skipped.
        values_source: Optional explicit source for distinct values.
        label: Human-readable label for frontend display.
        description: Longer description for documentation or LLM context.
    """

    name: str = Field(..., description="Stable filter id used in requests/schema.")
    columns: List[str] = Field(
        ...,
        min_length=1,
        description=(
            "Column(s); spatial uses [lat, lng] or a single geometry column."
        ),
    )
    kind: FilterKind
    ops: List[FilterOp] = Field(
        ...,
        min_length=1,
        description="Allowed filter operators for this definition.",
    )
    required: bool = Field(
        default=False,
        description=(
            "True → error if a target dataset lacks the column(s)."
        ),
    )
    values_source: Optional[ValuesSource] = None
    label: Optional[str] = None
    description: Optional[str] = None

    @model_validator(mode="after")
    def _validate_op_kind_compatibility(self) -> "FilterDefinition":
        """Enforce op⇄kind compatibility rules.

        Rules:
        - ``radius`` is only valid when ``kind == "spatial"``.
        - ``range`` is only valid when ``kind in {"numeric", "temporal"}``.
        - All other operators (``eq``, ``ne``, ``in``, ``not_in``) are
          accepted for non-spatial kinds; spatial definitions may NOT use
          them (spatial requests use ``radius`` exclusively in this v1).

        Returns:
            The validated ``FilterDefinition`` instance.

        Raises:
            ValueError: When any operator is incompatible with the declared
                kind.
        """
        ops_set = set(self.ops)
        kind = self.kind

        # radius is spatial-only
        if "radius" in ops_set and kind != "spatial":
            raise ValueError(
                f"FilterDefinition '{self.name}': operator 'radius' requires "
                f"kind='spatial', got kind='{kind}'."
            )

        # range requires numeric or temporal
        if "range" in ops_set and kind not in {"numeric", "temporal"}:
            raise ValueError(
                f"FilterDefinition '{self.name}': operator 'range' requires "
                f"kind in {{'numeric', 'temporal'}}, got kind='{kind}'."
            )

        # spatial kind must only use radius
        if kind == "spatial":
            non_spatial_ops = ops_set - _SPATIAL_ONLY_OPS
            if non_spatial_ops:
                raise ValueError(
                    f"FilterDefinition '{self.name}': kind='spatial' only "
                    f"supports operator 'radius'; found disallowed operators: "
                    f"{sorted(non_spatial_ops)}."
                )

        return self


class FilterCondition(BaseModel):
    """A single applied condition within a filter request.

    Attributes:
        op: The filter operator to apply.
        value: The operand — scalar, list, ``{"min": ..., "max": ...}`` dict
            for ``range``, or radius specification for ``radius``.
    """

    op: FilterOp
    value: Any = None


class FilterResult(BaseModel):
    """Records the per-run outcome of ``DatasetManager.apply_filters``.

    Attributes:
        applied: Names of datasets that were successfully filtered.
        skipped: Names of datasets that were skipped because they lack the
            target column(s) and the filter's ``required`` flag is False.
    """

    applied: List[str] = Field(default_factory=list)
    skipped: List[str] = Field(
        default_factory=list,
        description="Datasets skipped because they lack the target column (required=False).",
    )
