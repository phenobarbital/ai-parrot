"""Field constraints and conditional visibility rules for form fields.

This module defines the data models for field-level constraints (min/max,
patterns, file size limits) and the dependency rule system that controls
conditional visibility and behavior.
"""

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class FieldCondition(BaseModel):
    """A single condition referencing another field's value.

    Attributes:
        field_id: The ID of the field to evaluate.
        operator: The comparison operator to apply.
        value: The value to compare against (not required for IS_EMPTY/IS_NOT_EMPTY).
    """

    field_id: str
    operator: ConditionOperator
    value: Any = None


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
