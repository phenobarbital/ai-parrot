"""Form-control registry.

Extending the toolbar:

    from parrot_formdesigner.controls import register_field_control

    register_field_control(
        "rich_text",
        label="Rich Text",
        description="Rich text editor",
        category="advanced",
        icon="rich-text",
        snippet={"type": "string", "format": "rich-text"},
        render_hint="rich",
        supports_constraints=True,
    )

Call this once at consumer startup, before ``setup_form_api(app, registry)``
is called (or any time before the first request — the seed and
extensions live in the same module-level dict).
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict

from ..core.types import FieldType


logger = logging.getLogger(__name__)


class FieldControlMetadata(BaseModel):
    """Metadata describing a single form-control entry for the toolbar.

    Attributes:
        type: Canonical id (`FieldType.value` or extension type id).
        label: Short, human-readable name.
        description: Description shown in the toolbar tooltip / help.
        category: Grouping bucket — one of
            ``"basic" | "selection" | "media" | "layout" | "advanced"``.
        icon: Consumer-defined glyph name.
        snippet: JSON Schema snippet seed to drop into a new form.
        render_hint: UI hint such as ``"input" | "select" | "container"``.
        supports_constraints: Whether the control supports validation
            constraints (min/max length, regex, etc.).
        is_container: Whether the control nests other fields (groups, arrays).
        supported_operators: List of ``ConditionOperator`` values meaningful for
            this control type (used in ``depends_on.conditions`` and
            ``post_depends.conditions``).  Empty list = all operators accepted.
            Optional — omit for extension types.
        supported_effects: List of pre-dependency ``effect`` values applicable
            to this control (``"show" | "hide" | "require" | "disable"``).
            Empty list = all effects applicable.  Optional.
        supported_operations: List of :class:`DependencyOperation` ``op`` values
            that make semantic sense for this control type (e.g. arithmetic ops
            only for numeric types).  Empty list = all ops applicable.  Optional.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    label: str
    description: str
    category: str
    icon: str
    snippet: dict[str, Any]
    render_hint: str
    supports_constraints: bool
    is_container: bool = False
    # Rule capability metadata (FEAT-234) — optional with safe defaults
    supported_operators: list[str] = []
    supported_effects: list[str] = []
    supported_operations: list[str] = []


# Module-level registry — preserves registration order for stable iteration.
_REGISTRY: dict[str, FieldControlMetadata] = {}


def register_field_control(
    field_type: FieldType | str,
    *,
    label: str,
    description: str,
    category: str,
    icon: str,
    snippet: dict[str, Any],
    render_hint: str,
    supports_constraints: bool,
    is_container: bool = False,
    supported_operators: list[str] | None = None,
    supported_effects: list[str] | None = None,
    supported_operations: list[str] | None = None,
) -> None:
    """Register (or overwrite) a control entry in the toolbar registry.

    Idempotent: re-registering the same ``field_type`` overwrites the previous
    entry and logs a warning.

    Args:
        field_type: A ``FieldType`` enum or a string id (for extension types).
        label: Short, human-readable label.
        description: Description for the toolbar tooltip / help.
        category: One of ``"basic" | "selection" | "media" | "layout" | "advanced"``.
        icon: Consumer-defined glyph name.
        snippet: JSON Schema snippet seed.
        render_hint: UI hint (e.g. ``"input"``, ``"select"``, ``"container"``).
        supports_constraints: Whether the control supports validation constraints.
        is_container: Whether the control nests other fields. Defaults to ``False``.
        supported_operators: ``ConditionOperator`` values meaningful for this type.
            ``None`` (default) and ``[]`` both mean "all operators applicable".
        supported_effects: Dependency ``effect`` values applicable to this type.
            ``None`` (default) and ``[]`` both mean "all effects applicable".
        supported_operations: ``DependencyOperation.op`` values that make sense
            for this type.  ``None`` (default) and ``[]`` both mean "all ops".
    """
    type_id = field_type.value if isinstance(field_type, FieldType) else field_type
    if type_id in _REGISTRY:
        logger.warning(
            "register_field_control: overwriting existing entry for type=%s", type_id
        )
    _REGISTRY[type_id] = FieldControlMetadata(
        type=type_id,
        label=label,
        description=description,
        category=category,
        icon=icon,
        snippet=snippet,
        render_hint=render_hint,
        supports_constraints=supports_constraints,
        is_container=is_container,
        supported_operators=supported_operators or [],
        supported_effects=supported_effects or [],
        supported_operations=supported_operations or [],
    )


def get_controls() -> list[FieldControlMetadata]:
    """Return all registered controls in registration order.

    Returns:
        A list of ``FieldControlMetadata`` instances in the order they were
        registered. The list is a fresh copy of the registry's values.
    """
    return list(_REGISTRY.values())


def iter_controls() -> Iterator[FieldControlMetadata]:
    """Yield registered controls in registration order.

    Yields:
        Each ``FieldControlMetadata`` instance in registration order.
    """
    yield from _REGISTRY.values()
