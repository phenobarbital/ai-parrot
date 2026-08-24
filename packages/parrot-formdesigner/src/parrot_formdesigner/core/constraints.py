"""Field constraints and conditional visibility rules for form fields.

This module defines the data models for field-level constraints (min/max,
patterns, file size limits) and the dependency rule system that controls
conditional visibility and behavior.
"""

import re
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .types import LocalizedString


DEFAULT_MAX_INLINE_SIZE = 10_485_760
"""System default (10 MB) for the inline data_url size threshold (FEAT-460)."""


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
        max_inline_size_bytes: Maximum file size (bytes) for inline data_url
            inclusion. Files above this get blob_ref only. None → system
            default (DEFAULT_MAX_INLINE_SIZE).
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
    max_inline_size_bytes: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Maximum file size (bytes) for inline data_url inclusion. "
            "Files above this get blob_ref only. "
            "None -> system default (DEFAULT_MAX_INLINE_SIZE)."
        ),
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
    # CONTAINS is IN read the other way round. IN asks "is the answer one of
    # these values"; CONTAINS asks "does this multi-valued source hold that
    # value" — the shape a store's group membership takes, where the context
    # supplies the list and the rule names the one entry it needs.
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"


class FieldCondition(BaseModel):
    """A single condition referencing another field's value.

    Attributes:
        field_id: The authored reference to the field to evaluate — a
            human/YAML/LLM-authored ``field_id`` (FEAT-393). Only
            meaningful when ``source == "field"``. Retained as
            informational input after resolution; it goes stale on
            rename by design and is ignored at evaluation time once
            ``field_uid`` is set.
        field_uid: The resolved, authoritative UID reference (FEAT-393).
            ``None`` until :func:`~parrot_formdesigner.core.resolution.
            resolve_rule_references` rewrites the authored ``field_id``
            at a build boundary. Only meaningful when ``source == "field"``.
        operator: The comparison operator to apply.
        value: The value to compare against (not required for IS_EMPTY/IS_NOT_EMPTY).
    """

    # model_config intentionally omits extra="forbid" for forward-compatible
    # unknown keys — existing forms with unrecognised condition keys must round-trip unchanged.

    field_id: str | None = None
    field_uid: uuid.UUID | None = None
    operator: ConditionOperator
    value: Any = None
    # FEAT-301: condition source discriminator. "field" (default) reads from
    # answers[field_id] — fully backward compatible. "location_variable" /
    # "visit_context" read from the eval context's location_vars / visit_context
    # using `key`. Legacy serialized conditions (no source) deserialize as field.
    source: str = "field"
    key: str | None = None


class LogicGroup(BaseModel):
    """One alternative inside a :class:`DependencyRule`.

    Conditions inside a group are AND'd; the groups themselves are OR'd
    against each other. That nesting is what a flat ``conditions`` list
    cannot express — "the store is in one of these groups AND the visit is
    one of these types" needs two groups, not thirteen conditions under a
    single gate, where ``and`` demands all thirteen and ``or`` settles for
    one.

    The shape matches the frontend's ``LogicGroup`` (navigator-svelte
    ``formbuilder/types/schema.ts``), which has evaluated groups since
    before the server could express them.

    Attributes:
        conditions: Conditions that must ALL hold for this group to match.
    """

    model_config = ConfigDict(extra="forbid")

    conditions: list["FieldCondition"]


class DependencyRule(BaseModel):
    """Rule controlling conditional visibility/behavior of a field or section.

    Attributes:
        groups: Alternatives, each AND'd internally and OR'd against the
            others. When present it REPLACES ``conditions``/``logic`` — the
            flat pair stays for every rule that does not need nesting.
        conditions: List of field conditions that must be evaluated.
        logic: How conditions are combined. One of:
            - ``"and"``: all conditions must be true (default; backward-compatible).
            - ``"or"``: at least one condition must be true.
            - ``"xor"``: exactly one condition must be true.
            - ``"not"``: negates the AND-combination of conditions (i.e. NOT(all true)).
        effect: The effect applied when conditions are met.
        operations: Optional list of :class:`DependencyOperation` instances
            that compute or assign values when the rule is triggered.
    """

    # model_config intentionally omits extra="forbid" for forward-compatible
    # unknown keys — existing forms with unrecognised rule keys must round-trip unchanged.

    groups: list[LogicGroup] | None = None
    conditions: list[FieldCondition]
    logic: Literal["and", "or", "xor", "not"] = "and"
    effect: Literal["show", "hide", "require", "disable"] = "show"
    operations: list["DependencyOperation"] | None = None


class DependencyOperation(BaseModel):
    """An operation that computes or assigns a value from referenced field values.

    Used within :class:`DependencyRule` (as one of ``operations``) and
    :class:`PostDependency` (as ``operation``) to express derived/calculated
    field values.

    Attributes:
        op: The operation kind. One of:
            - ``"copy"`` — copy a source field value to ``target``.
            - ``"add"`` / ``"subtract"`` / ``"multiply"`` / ``"divide"`` — arithmetic.
            - ``"percent"`` — compute a percentage.
            - ``"concat"`` — concatenate string operand values.
            - ``"format"`` — apply a format string (use ``options["template"]``).
            - ``"date_diff"`` — compute the difference between two dates
              (unit via ``options["unit"]``, e.g. ``"days"``).
            - ``"lookup"`` — look up a value via an external tool reference
              (tool ref in ``options["tool_ref"]``).
            - ``"aggregate"`` — aggregate values across repeated-section items
              (function in ``options["fn"]``, e.g. ``"sum"`` / ``"avg"`` / ``"count"``).
        operands: List of field reference strings whose current values are
            the inputs. Must be non-empty. Authored as ``field_id``
            strings; :func:`~parrot_formdesigner.core.resolution.
            resolve_rule_references` (FEAT-393) rewrites them in place to
            canonical UUID strings (``str(field_uid)``) at a build
            boundary — idempotent, since an already-UID-shaped operand
            validates and passes through unchanged.
        target: The field reference that receives the computed value.
            Same authored-``field_id`` → resolved-UUID-string lifecycle as
            ``operands`` (FEAT-393).
        options: Optional operation-specific configuration (e.g. ``{"unit": "days"}``
            for ``date_diff``, ``{"template": "{} {}"}`` for ``format``).
    """

    model_config = ConfigDict(extra="forbid")

    op: Literal[
        "copy",
        "add",
        "subtract",
        "multiply",
        "divide",
        "percent",
        "concat",
        "format",
        "date_diff",
        "lookup",
        "aggregate",
    ]
    operands: list[str]
    target: str
    options: dict[str, Any] | None = None

    @field_validator("operands")
    @classmethod
    def _non_empty_operands(cls, v: list[str]) -> list[str]:
        """Validate that operands list is non-empty.

        Args:
            v: The operands list.

        Returns:
            The operands list unchanged.

        Raises:
            ValueError: If operands is empty.
        """
        if not v:
            raise ValueError("operands must contain at least one field_id")
        return v

    @field_validator("target")
    @classmethod
    def _non_empty_target(cls, v: str) -> str:
        """Validate that target is non-empty.

        Args:
            v: The target field_id.

        Returns:
            The target unchanged.

        Raises:
            ValueError: If target is empty.
        """
        if not v or not v.strip():
            raise ValueError("target must be a non-empty field_id")
        return v


class PostDependency(BaseModel):
    """A forward dependency: how a field's answered value affects a later field.

    ``PostDependency`` declares that the *owning* field's value has a forward
    effect on a control declared **after** it.  Ordering is validated by
    :class:`~parrot_formdesigner.services.FormValidator`.

    Attributes:
        target: The field reference of the field to affect (must be
            declared *after* the owning field in the form layout).
            Authored as a ``field_id`` string; resolved in place to a
            canonical UUID string by
            :func:`~parrot_formdesigner.core.resolution.resolve_rule_references`
            (FEAT-393) — idempotent, same lifecycle as
            :attr:`DependencyOperation.target`.
        effect: The effect to apply.  ``"set"`` and ``"calc"`` require an
            ``operation``; the others are pure visibility/state changes.
            One of:

            - ``"set"`` — assign a computed value to ``target`` (requires ``operation``).
            - ``"calc"`` — calculate and assign a derived value (requires ``operation``).
            - ``"reload_options"`` — hint to clients to refresh the options list of
              ``target`` (async hint; evaluation timing is renderer-specific).
            - ``"show"`` / ``"hide"`` — control visibility of ``target``.
            - ``"require"`` — make ``target`` required.
            - ``"cascade_clear"`` — clear the value of ``target``.
        conditions: Optional gating conditions evaluated against the *owning*
            field's value (and context). If ``None``, the effect always applies.
        logic: How ``conditions`` are combined (same semantics as
            :attr:`DependencyRule.logic`). Default ``"and"``.
        operation: Required when ``effect`` is ``"set"`` or ``"calc"``.
    """

    model_config = ConfigDict(extra="forbid")

    target: str
    effect: Literal[
        "set",
        "calc",
        "reload_options",
        "show",
        "hide",
        "require",
        "cascade_clear",
    ]
    conditions: list[FieldCondition] | None = None
    logic: Literal["and", "or", "xor", "not"] = "and"
    operation: DependencyOperation | None = None

    @model_validator(mode="after")
    def _require_operation_for_set_calc(self) -> "PostDependency":
        """Enforce that set/calc effects carry an operation.

        Returns:
            Self, unchanged.

        Raises:
            ValueError: If ``effect`` is ``"set"`` or ``"calc"`` and
                ``operation`` is ``None``.
        """
        if self.effect in ("set", "calc") and self.operation is None:
            raise ValueError(
                f"effect={self.effect!r} requires an 'operation' (DependencyOperation)"
            )
        return self


# Resolve forward reference in DependencyRule.operations
DependencyRule.model_rebuild()
