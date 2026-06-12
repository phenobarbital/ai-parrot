"""Field constraints and conditional visibility rules for form fields.

This module defines the data models for field-level constraints (min/max,
patterns, file size limits) and the dependency rule system that controls
conditional visibility and behavior.

FEAT-301: ``FieldCondition`` is now a **discriminated union** by ``source``:
- ``FieldRefCondition``       — conditions over another field's answer (legacy path)
- ``LocationVarCondition``    — conditions over Org Graph location variables
- ``VisitContextCondition``   — conditions over visit-level metadata

Backward compat: pre-existing serialized forms that have plain
``{"field_id": ..., "operator": ..., "value": ...}`` dicts (no ``source`` key)
are automatically upgraded to ``FieldRefCondition`` by the
``DependencyRule._inject_legacy_source`` validator.
"""

import re
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .types import LocalizedString


class FieldConstraints(BaseModel):
    """Constraints applied to a form field for validation.

    Attributes:
        min_length: Minimum string length (>= 0).
        max_length: Maximum string length (>= 0).
        min_value: Minimum numeric value.
        max_value: Maximum numeric value.
        step: Numeric step increment.
        pattern: Regular expression pattern for validation. Validated at
            construction time to prevent ReDoS from malformed patterns.
        pattern_message: Human-readable message shown when pattern fails.
        min_items: Minimum number of items in array/multi-select fields (>= 0).
        max_items: Maximum number of items in array/multi-select fields (>= 0).
        allowed_mime_types: Allowed MIME types for file/image fields.
        max_file_size_bytes: Maximum file size in bytes for file/image fields (>= 0).
    """

    model_config = ConfigDict(extra="forbid")

    min_length: int | None = Field(default=None, ge=0, description="Minimum string length")
    max_length: int | None = Field(default=None, ge=0, description="Maximum string length")
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    pattern: str | None = None
    pattern_message: LocalizedString | None = None
    min_items: int | None = Field(default=None, ge=0, description="Minimum number of items")
    max_items: int | None = Field(default=None, ge=0, description="Maximum number of items")
    allowed_mime_types: list[str] | None = None
    max_file_size_bytes: int | None = Field(
        default=None, ge=0, description="Maximum file size in bytes"
    )
    # Phase 2 — scale fields for NPS / LIKERT / RANKING (FEAT-167)
    scale_min: int | None = Field(default=None, ge=0, description="Scale minimum (>= 0)")
    scale_max: int | None = Field(default=None, description="Scale maximum (must be > scale_min)")
    scale_step: int | None = Field(default=None, ge=1, description="Scale step increment (>= 1)")
    anchor_labels: dict[int, LocalizedString] | None = Field(
        default=None, description="Label for specific scale points"
    )

    @field_validator("scale_max")
    @classmethod
    def _validate_scale_max(cls, v: int | None, info: Any) -> int | None:
        """Enforce scale_max > scale_min when both are set.

        Args:
            v: scale_max value.
            info: Validation info with sibling field data.

        Returns:
            The scale_max value unchanged.

        Raises:
            ValueError: If scale_max <= scale_min.
        """
        scale_min = info.data.get("scale_min")
        if v is not None and scale_min is not None and v <= scale_min:
            raise ValueError(
                f"scale_max ({v}) must be greater than scale_min ({scale_min})"
            )
        return v

    @field_validator("anchor_labels")
    @classmethod
    def _validate_anchor_labels(cls, v: dict | None, info: Any) -> dict | None:
        """Enforce anchor_labels keys are within [scale_min, scale_max].

        Args:
            v: anchor_labels dict.
            info: Validation info with sibling field data.

        Returns:
            The anchor_labels dict unchanged.

        Raises:
            ValueError: If any key is outside the scale bounds.
        """
        if v is None:
            return v
        scale_min = info.data.get("scale_min", 0) or 0
        scale_max = info.data.get("scale_max")
        if scale_max is not None:
            for key in v:
                if not (scale_min <= key <= scale_max):
                    raise ValueError(
                        f"anchor_labels key {key} is outside [{scale_min}, {scale_max}]"
                    )
        return v

    @field_validator("pattern")
    @classmethod
    def _validate_pattern(cls, v: str | None) -> str | None:
        """Validate that the regex pattern compiles without error.

        Args:
            v: Regex pattern string, or None.

        Returns:
            The pattern unchanged if it compiles successfully.

        Raises:
            ValueError: If the pattern is not a valid regular expression.
        """
        if v is not None:
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern: {exc}") from exc
        return v


class ConditionOperator(str, Enum):
    """Operators for field conditions in dependency rules."""

    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"


# ---------------------------------------------------------------------------
# FEAT-301 — FieldCondition discriminated union (RESUELTO §8)
# ---------------------------------------------------------------------------

class FieldRefCondition(BaseModel):
    """Condition over another field's answer (the pre-existing behavior).

    This is the backward-compatible variant: ``field_id`` is preserved
    so existing serialized forms parse without migration.

    Attributes:
        source: Discriminator, always ``"field"``.
        field_id: The ID of the field whose answer to evaluate.
        operator: The comparison operator to apply.
        value: The value to compare against (not required for IS_EMPTY/IS_NOT_EMPTY).
    """

    model_config = ConfigDict(extra="forbid")

    source: Literal["field"] = "field"
    field_id: str
    operator: ConditionOperator
    value: Any = None


class LocationVarCondition(BaseModel):
    """Condition over an Org Graph location variable (store > program merge).

    The variable values are pre-fetched from ``ai-parrot`` Org Graph service
    (FEAT-302) and passed in ``EvaluationContext.location_vars`` at request time.

    Attributes:
        source: Discriminator, always ``"location_variable"``.
        key: Location variable key, e.g. ``"store_type"``.
        operator: The comparison operator to apply.
        value: The value to compare against.
    """

    model_config = ConfigDict(extra="forbid")

    source: Literal["location_variable"]
    key: str
    operator: ConditionOperator
    value: Any = None


class VisitContextCondition(BaseModel):
    """Condition over visit-level metadata (date, type, etc.).

    Attributes:
        source: Discriminator, always ``"visit_context"``.
        key: Visit context key, e.g. ``"visit_type"`` or ``"visit_date"``.
        operator: The comparison operator to apply.
        value: The value to compare against.
    """

    model_config = ConfigDict(extra="forbid")

    source: Literal["visit_context"]
    key: str
    operator: ConditionOperator
    value: Any = None


# The public ``FieldCondition`` type — a discriminated union on ``source``.
# Legacy dicts without ``source`` are handled by DependencyRule's before-validator.
FieldCondition = Annotated[
    Union[FieldRefCondition, LocationVarCondition, VisitContextCondition],
    Field(discriminator="source"),
]


class LocationVariableBinding(BaseModel):
    """Immutable key-value pair from the Org Graph for a location/store node.

    These come from the ``ai-parrot`` Org Graph service (FEAT-302) and are
    passed in ``EvaluationContext.location_vars`` at request time.

    Attributes:
        key: Variable name, e.g. ``"store_type"``.
        scope: Org node identifier, e.g. store ID or program ID.
        value: Resolved value; type depends on the variable definition.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    scope: str
    value: Any


class DependencyRule(BaseModel):
    """Rule controlling conditional visibility/behavior of a field or section.

    Attributes:
        conditions: List of field conditions that must be evaluated.
        logic: Whether conditions are combined with AND or OR logic.
        effect: The effect applied when conditions are met.
    """

    conditions: list[FieldCondition]
    logic: Literal["and", "or"] = "and"
    effect: Literal["show", "hide", "require", "disable"] = "show"

    @model_validator(mode="before")
    @classmethod
    def _inject_legacy_source(cls, data: Any) -> Any:
        """Inject ``source="field"`` into legacy condition dicts without a discriminator.

        Backward-compat shim: pre-existing serialized forms store conditions as
        plain dicts ``{"field_id": ..., "operator": ..., "value": ...}`` without
        a ``source`` key.  The discriminated union requires ``source`` to dispatch,
        so we inject it here before Pydantic processes the conditions.

        Args:
            data: Raw dict or already-validated model instance.

        Returns:
            The (potentially mutated) data dict.
        """
        if isinstance(data, dict):
            for cond in data.get("conditions") or []:
                if isinstance(cond, dict) and "source" not in cond:
                    cond["source"] = "field"
        return data
