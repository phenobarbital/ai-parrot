"""A2UI component catalog — contract types and registry internals (Module 2).

The catalog is the security allowlist at the heart of spec goal **G1**: only
components with a registered :class:`ComponentDefinition` may appear in an
envelope, so nothing unknown ever reaches a renderer. It also carries:

* the **mandatory lowering contract** (G4/D8) — every registrable component ships
  a pure, deterministic ``lower(component, data_model) -> BasicTree``, enforced at
  registration time (not by convention); and
* the ``requires_actions`` gate (G2/D10b) — LLM-produced envelopes may not contain
  action-bearing components in v1.

This module holds the low-level types and the registry dict. The public decorator
and validation entry points live in :mod:`parrot.outputs.a2ui.catalog` (``__init__``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from parrot.outputs.a2ui.models import ChildTemplate, Component, ComponentMetadata

__all__ = [
    "ACTION_NOT_ALLOWED_FOR_LLM",
    "CATALOG_UNRESOLVED",
    "DANGLING_CHILD",
    "DEFAULT_CATALOG_ID",
    "DUPLICATE_ID",
    "INVALID_FUNCTION_CALL",
    "MISSING_ROOT",
    "UNALLOWED_CHILD",
    "UNALLOWED_PARENT",
    "UNKNOWN_COMPONENT",
    "BasicNode",
    "BasicTree",
    "CatalogError",
    "CatalogValidationError",
    "ComponentContractError",
    "ComponentDefinition",
    "FunctionDefinition",
    "ProducerOrigin",
    "RegisteredComponent",
    "TabSpec",
    "to_components",
]

#: The Parrot custom catalog id. Extends the A2UI Basic Catalog (spec D2).
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"

# ---------------------------------------------------------------------------
# Validation error codes (spec §2/§7 — v1.0 catalog validation, Module 2)
# ---------------------------------------------------------------------------

#: A component/function's ``catalogId`` could not be resolved (neither the
#: component nor its surface declared one).
CATALOG_UNRESOLVED = "CATALOG_UNRESOLVED"
#: A child component's type is not in its parent's ``allowed_children``.
UNALLOWED_CHILD = "UNALLOWED_CHILD"
#: A parent component's type is not in its child's ``allowed_parents``.
UNALLOWED_PARENT = "UNALLOWED_PARENT"
#: A ``FunctionCall`` targets an unregistered/malformed function.
INVALID_FUNCTION_CALL = "INVALID_FUNCTION_CALL"
#: No component with ``id == "root"`` is present.
MISSING_ROOT = "MISSING_ROOT"
#: Two or more components share the same ``id``.
DUPLICATE_ID = "DUPLICATE_ID"
#: A ``child``/``children`` reference points at a nonexistent component id.
DANGLING_CHILD = "DANGLING_CHILD"
#: A component name is not registered in its resolved catalog.
UNKNOWN_COMPONENT = "UNKNOWN_COMPONENT"
#: An LLM-originated envelope carries a component with a non-null ``action``
#: (G2/D10b gate — LLM envelopes are display-only in v1).
ACTION_NOT_ALLOWED_FOR_LLM = "ACTION_NOT_ALLOWED_FOR_LLM"


class ProducerOrigin(str, Enum):
    """Origin of an envelope, controlling ``requires_actions`` enforcement.

    Tool builders emit envelopes deterministically and MAY include action-bearing
    components (they degrade to deep links at render time). The LLM producer path
    is display-only in v1 and MUST NOT emit ``requires_actions`` components.
    """

    TOOL = "tool"
    LLM = "llm"


class BasicNode(BaseModel):
    """A node in a lowered A2UI v1.0 *Basic Catalog* tree.

    The output of a component's ``lower()`` is a nested tree of Basic Catalog
    primitives (e.g. ``Column``, ``Row``, ``Text``, ``Image``). Unlike the wire
    :class:`~parrot.outputs.a2ui.models.Component` (a FLAT adjacency list keyed
    by id, ``child``/``children`` referencing OTHER ids in the same list), a
    lowered tree nests ``child``/``children`` directly as :class:`BasicNode`
    objects — this is an internal, render-facing representation, not a wire
    message. :func:`to_components` flattens it (spec §2/§5, TASK-2539).

    Props are top-level (``extra="allow"``), mirroring the wire
    :class:`~parrot.outputs.a2ui.models.Component` — NOT nested under a
    ``properties`` key. Presentation semantics that aren't part of the
    official wire (parrot's role hints, its own component's original id)
    belong in ``metadata.extensions.parrot_role``/``parrot_component_id``.

    Attributes:
        id: Optional explicit id. When omitted, :func:`to_components`
            generates a deterministic ``f"{id_prefix}-{n}"`` id.
        component: Basic Catalog (or Parrot) component name.
        child: A single nested child (for single-child primitives like
            ``Card``/``Button``).
        children: Nested children (for multi-child primitives like
            ``Column``/``Row``/``List``), OR a ``ChildTemplate`` referencing
            ``template_source`` by its id.
        template_source: When ``children`` is a ``ChildTemplate``, the
            template pattern node it refers to (``componentId``). Flattened
            as its own top-level component alongside this node, but never
            nested under it directly.
        metadata: Component-level metadata (``extensions.parrot_*``).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str | None = None
    component: str
    child: BasicNode | None = None
    children: list[BasicNode] | ChildTemplate | None = None
    template_source: BasicNode | None = None
    tabs: list[TabSpec] | None = None
    metadata: ComponentMetadata | None = None


class TabSpec(BaseModel):
    """One ``{title, child}`` pair for a lowered ``Tabs`` :class:`BasicNode`.

    Mirrors the wire ``Tabs.tabs[]`` shape, but ``child`` is a nested
    :class:`BasicNode` (flattened by :func:`to_components`, not yet an id).
    """

    model_config = ConfigDict(populate_by_name=True)

    title: Any
    child: BasicNode


BasicNode.model_rebuild()

#: A lowered Basic Catalog tree is rooted at a single :class:`BasicNode`.
BasicTree = BasicNode


def to_components(tree: BasicNode, *, id_prefix: str = "blk") -> list[Component]:
    """Flatten a lowered :class:`BasicNode` tree into a v1.0 flat adjacency list.

    Every node gets a deterministic id: its own ``id`` if set, else
    ``f"{id_prefix}-{n}"`` (depth-first, post-order counter). A node's
    ``template_source`` (if any) is flattened alongside it as its own
    top-level component, matching whatever id a sibling ``ChildTemplate``
    references via ``componentId``.

    Args:
        tree: The root of a lowered Basic Catalog tree.
        id_prefix: Prefix for auto-generated ids.

    Returns:
        A flat list of v1.0 :class:`Component` instances — the wire adjacency
        list (order is a valid topological walk, root last).
    """
    components: list[Component] = []
    counter = {"n": 0}

    def _next_id() -> str:
        counter["n"] += 1
        return f"{id_prefix}-{counter['n']}"

    def _walk(node: BasicNode) -> str:
        node_id = node.id or _next_id()

        child_id: str | None = None
        if node.child is not None:
            child_id = _walk(node.child)

        children_value: list[str] | ChildTemplate | None = None
        if isinstance(node.children, list):
            children_value = [_walk(child) for child in node.children]
        elif node.children is not None:
            children_value = node.children  # a ChildTemplate — passed through

        if node.template_source is not None:
            _walk(node.template_source)

        extra = dict(node.model_extra or {})
        if node.tabs is not None:
            extra["tabs"] = [{"title": tab.title, "child": _walk(tab.child)} for tab in node.tabs]

        components.append(
            Component(
                id=node_id,
                component=node.component,
                child=child_id,
                children=children_value,
                metadata=node.metadata,
                **extra,
            )
        )
        return node_id

    _walk(tree)
    return components


class ComponentDefinition(BaseModel):
    """Metadata describing a registered catalog component (spec §2 Data Models).

    Attributes:
        name: Component type name (e.g. ``"Infographic"``).
        catalog_id: Owning catalog id; defaults to the Parrot custom catalog.
        schema_: JSON-Schema for the component payload (wire/dump alias ``schema``).
        instructions: Embedded LLM guidance for producing this component (A2UI spec).
        requires_actions: Whether the component is action-bearing (D10b gate).
        is_primitive: ``True`` for the 18 official Basic Catalog primitives —
            these register WITHOUT a ``lower()`` (they ARE the lowering
            target, not something that lowers further). Every non-primitive
            component MUST still supply ``lower()`` (G4).
        allowed_parents: If set, the type names this component may appear
            under (``child``/``children`` of). ``None`` means unrestricted.
        allowed_children: If set, the type names allowed as this component's
            ``child``/``children``. ``None`` means unrestricted.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    catalog_id: str = DEFAULT_CATALOG_ID
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    instructions: str = ""
    requires_actions: bool = False
    is_primitive: bool = False
    allowed_parents: list[str] | None = None
    allowed_children: list[str] | None = None


class FunctionDefinition(BaseModel):
    """Metadata describing a registered catalog function (spec §2 Data Models).

    Attributes:
        name: Function name (e.g. ``"formatString"``, ``"and"``).
        catalog_id: Owning catalog id.
        args_schema: JSON-Schema for the function's ``args`` object.
        return_type: The function's declared return type (informational).
        allowed_callers: Who may invoke this function in a ``FunctionCall``.
        requires_user_activation: Whether invoking this function requires a
            direct user gesture (e.g. ``openUrl``).
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    catalog_id: str
    args_schema: dict[str, Any] = Field(default_factory=dict)
    return_type: str = "any"
    allowed_callers: Literal["rendererOnly", "agentOnly", "rendererOrAgent"] = "rendererOnly"
    requires_user_activation: bool = False


@dataclass
class RegisteredComponent:
    """A catalog entry: the component's definition plus its implementing class."""

    definition: ComponentDefinition
    component_cls: type = field(repr=False)


# ---------------------------------------------------------------------------
# Errors (structured — carry offending component names for Module 9 re-prompts)
# ---------------------------------------------------------------------------


class CatalogError(Exception):
    """Base class for catalog errors."""


class ComponentContractError(CatalogError):
    """Raised when a component class violates the registration contract.

    The canonical trigger is a missing/uncallable ``lower()`` — a component
    cannot register without a lowering (spec G4, enforced not conventional).
    """


class CatalogValidationError(CatalogError):
    """Raised when an envelope/catalog-id fails v1.0 catalog validation.

    Two usage shapes:

    * A single structured error (e.g. :func:`resolve_catalog`): pass ``code``.
      ``.code``/``.issues`` are populated from it.
    * An aggregate error reporting EVERY problem found (e.g.
      :func:`validate_envelope`, spec §7 "reporta TODOS los errores"): pass
      ``issues`` directly — a list of ``{"code": ..., "message": ...,
      "path": ...}`` dicts. ``.code`` then reflects the FIRST issue.

    Attributes:
        code: The (first) structured error code — one of the ``base.py``
            module constants (``CATALOG_UNRESOLVED``, ``UNALLOWED_PARENT``, ...).
        issues: The full list of structured issues found.
        unknown_components: Component names not present in the catalog
            (kept for backward-compat call sites; also present in ``issues``).
        action_components: Action-bearing component names rejected for an
            LLM-produced envelope (kept for backward-compat call sites; also
            present in ``issues``).
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        issues: list[dict[str, Any]] | None = None,
        unknown_components: list[str] | None = None,
        action_components: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.issues: list[dict[str, Any]] = issues or (
            [{"code": code, "message": message, "path": None}] if code else []
        )
        self.code: str | None = self.issues[0]["code"] if self.issues else code
        self.unknown_components = unknown_components or []
        self.action_components = action_components or []
