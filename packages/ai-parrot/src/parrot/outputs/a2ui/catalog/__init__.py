"""A2UI component catalog — public decorator, lookup, and envelope validation.

Registration pattern mirrors :func:`parrot.outputs.formats.register_renderer`
(module-level registry dict + decorator that inserts and returns the class), with
the added registration-time enforcement of the mandatory ``lower()`` contract.

A registrable component class MUST:

* implement a callable ``lower(self, component, data_model) -> BasicTree``
  (pure and deterministic — golden-file tested in Module 3), UNLESS it
  registers with ``is_primitive=True`` (the 18 official Basic Catalog
  primitives, TASK-2536, which ARE the lowering target); and
* optionally expose class attributes ``SCHEMA`` (dict) and ``INSTRUCTIONS`` (str),
  which the decorator folds into the component's :class:`ComponentDefinition`.

v1.0 catalog resolution (spec §2 G2): a component without an explicit
``catalogId`` resolves against its surface's default ``catalogId``
(:func:`resolve_catalog`). The Parrot catalog (:data:`DEFAULT_CATALOG_ID`)
``$ref``-includes the official Basic Catalog by design, so a bare component
name (``"Text"``, ``"Button"``, ...) resolves under either — until TASK-2539
migrates the Parrot catalog's own components into the Python registry, the
Basic Catalog's 18 names are checked directly against the vendored
``catalog.json`` (the source of truth), not the (currently basic-empty)
Python registry.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import jsonschema

from parrot.outputs.a2ui.catalog import basic
from parrot.outputs.a2ui.catalog.base import (
    ACTION_NOT_ALLOWED_FOR_LLM,
    CATALOG_UNRESOLVED,
    DANGLING_CHILD,
    DEFAULT_CATALOG_ID,
    DUPLICATE_ID,
    MISSING_ROOT,
    UNALLOWED_CHILD,
    UNALLOWED_PARENT,
    UNKNOWN_COMPONENT,
    BasicNode,
    BasicTree,
    CatalogError,
    CatalogValidationError,
    ComponentContractError,
    ComponentDefinition,
    FunctionDefinition,
    ProducerOrigin,
    RegisteredComponent,
)
from parrot.outputs.a2ui.models import (
    A2UIAgentMessage,
    A2UIRendererMessage,
    ChildTemplate,
    Component,
    CreateSurface,
    UpdateComponents,
)

__all__ = [
    "DEFAULT_CATALOG_ID",
    "BasicNode",
    "BasicTree",
    "CatalogError",
    "CatalogValidationError",
    "ComponentContractError",
    "ComponentDefinition",
    "FunctionDefinition",
    "ProducerOrigin",
    "RegisteredComponent",
    "catalog_instructions",
    "get_component",
    "get_function",
    "list_components",
    "list_functions",
    "register_component",
    "register_function",
    "resolve_catalog",
    "unregister_component",
    "validate_envelope",
    "validate_message",
]

logger = logging.getLogger(__name__)

#: Global component allowlist, keyed by component name.
_CATALOG: dict[str, RegisteredComponent] = {}

#: Global function allowlist, keyed by function name.
_FUNCTIONS: dict[str, FunctionDefinition] = {}


def register_component(
    name: str,
    *,
    requires_actions: bool = False,
    catalog_id: str = DEFAULT_CATALOG_ID,
    is_primitive: bool = False,
    allowed_parents: list[str] | None = None,
    allowed_children: list[str] | None = None,
) -> Callable[[type], type]:
    """Register a catalog component under ``name``.

    Enforces the mandatory lowering contract at registration time: a class without
    a callable ``lower()`` cannot register (raises :class:`ComponentContractError`)
    UNLESS ``is_primitive=True`` (spec G4).

    Args:
        name: The component type name used in envelopes (e.g. ``"Chart"``).
        requires_actions: Marks the component as action-bearing (D10b). LLM-produced
            envelopes containing it are rejected by :func:`validate_envelope`.
        catalog_id: Owning catalog id; defaults to the Parrot custom catalog.
        is_primitive: ``True`` for an official Basic Catalog primitive — no
            ``lower()`` is required.
        allowed_parents: If set, restricts which component types this one may
            appear under.
        allowed_children: If set, restricts which component types this one
            may contain as ``child``/``children``.

    Returns:
        The class decorator.

    Raises:
        ComponentContractError: If the decorated class lacks a callable ``lower()``
            and is not registered with ``is_primitive=True``.
    """

    def decorator(cls: type) -> type:
        lower = getattr(cls, "lower", None)
        if not is_primitive and not callable(lower):
            raise ComponentContractError(
                f"Component {name!r} ({cls.__name__}) cannot register: it must "
                "implement a callable lower(self, component, data_model) -> BasicTree "
                "(spec G4 — lowering is enforced, not conventional), unless "
                "registered with is_primitive=True."
            )
        definition = ComponentDefinition(
            name=name,
            catalog_id=catalog_id,
            schema=dict(getattr(cls, "SCHEMA", {}) or {}),
            instructions=str(getattr(cls, "INSTRUCTIONS", "") or ""),
            requires_actions=requires_actions,
            is_primitive=is_primitive,
            allowed_parents=allowed_parents,
            allowed_children=allowed_children,
        )
        _CATALOG[name] = RegisteredComponent(definition=definition, component_cls=cls)
        # Attach for convenient access from instances / renderers.
        cls.definition = definition  # type: ignore[attr-defined]
        logger.debug("Registered A2UI catalog component %r (%s)", name, cls.__name__)
        return cls

    return decorator


def unregister_component(name: str) -> None:
    """Remove a component from the catalog (primarily for test isolation)."""
    _CATALOG.pop(name, None)


def get_component(name: str) -> RegisteredComponent:
    """Return the registered component for ``name``.

    Raises:
        KeyError: If ``name`` is not registered.
    """
    return _CATALOG[name]


def list_components() -> list[ComponentDefinition]:
    """Return the definitions of all registered components (name-sorted)."""
    return [entry.definition for _, entry in sorted(_CATALOG.items())]


def register_function(definition: FunctionDefinition) -> None:
    """Register a catalog function definition (primarily the Basic Catalog's 14).

    Args:
        definition: The function's :class:`FunctionDefinition`.
    """
    _FUNCTIONS[definition.name] = definition
    logger.debug("Registered A2UI catalog function %r", definition.name)


def get_function(name: str) -> FunctionDefinition:
    """Return the registered function definition for ``name``.

    Raises:
        KeyError: If ``name`` is not registered.
    """
    return _FUNCTIONS[name]


def list_functions() -> list[FunctionDefinition]:
    """Return all registered function definitions (name-sorted)."""
    return [d for _, d in sorted(_FUNCTIONS.items())]


def catalog_instructions() -> str:
    """Aggregate every component's embedded ``instructions`` for the LLM producer.

    Returns:
        A newline-joined block of ``<name>: <instructions>`` lines, name-sorted.
    """
    # NOTE (bug fix, TASK-2535): a prior `.rstrip(": ")` here would silently
    # eat a legitimate trailing colon/space from an instructions string that
    # happened to end that way — `list_components()` is already filtered to
    # `d.instructions` truthy, so no stripping is needed at all.
    lines = [f"{d.name}: {d.instructions}" for d in list_components() if d.instructions]
    return "\n".join(lines)


def resolve_catalog(
    component_catalog_id: str | None, surface_catalog_id: str | None
) -> str:
    """Resolve the effective catalog id for a component (spec §2 G2).

    Precedence: the component's own ``catalogId`` wins; otherwise the
    surface's default ``catalogId`` applies.

    Args:
        component_catalog_id: The component's own ``catalogId``, if any.
        surface_catalog_id: The surface's default ``catalogId``, if any.

    Returns:
        The resolved catalog id.

    Raises:
        CatalogValidationError: (code ``CATALOG_UNRESOLVED``) if neither is set.
    """
    resolved = component_catalog_id or surface_catalog_id
    if not resolved:
        raise CatalogValidationError(
            "Component has no catalogId and its surface has no default "
            "catalogId — cannot resolve which catalog to validate against.",
            code=CATALOG_UNRESOLVED,
        )
    return resolved


def _basic_component_names() -> frozenset[str]:
    """The 18 official Basic Catalog primitive names (source of truth: vendored JSON)."""
    return frozenset(basic.load_spec("catalog")["components"].keys())


def _component_exists(name: str, resolved_catalog_id: str) -> bool:
    """Whether ``name`` is a known component under ``resolved_catalog_id``.

    Checks the vendored Basic Catalog JSON directly (source of truth, since
    the Python registry has no basic primitives registered until TASK-2536)
    and/or the Python registry (Parrot catalog components, TASK-2539+).
    Per spec G2, the Parrot catalog `$ref`-includes the Basic Catalog, so a
    component resolved against :data:`DEFAULT_CATALOG_ID` may be either.
    """
    if resolved_catalog_id == basic.BASIC_CATALOG_ID:
        return name in _basic_component_names()
    if resolved_catalog_id == DEFAULT_CATALOG_ID:
        if name in _basic_component_names():
            return True
        entry = _CATALOG.get(name)
        return entry is not None and entry.definition.catalog_id == DEFAULT_CATALOG_ID
    entry = _CATALOG.get(name)
    return entry is not None and entry.definition.catalog_id == resolved_catalog_id


def validate_message(message: A2UIAgentMessage | A2UIRendererMessage) -> None:
    """Validate a full v1.0 envelope against the official wire JSON Schemas.

    Args:
        message: An :class:`A2UIAgentMessage` or :class:`A2UIRendererMessage`.

    Raises:
        TypeError: If ``message`` is neither envelope type.
        jsonschema.exceptions.ValidationError: If it does not match the
            corresponding official schema (``agent_to_renderer.json`` /
            ``renderer_to_agent.json``).
    """
    from parrot.outputs.a2ui.serialization import serialize

    if isinstance(message, A2UIAgentMessage):
        schema_name = "agent_to_renderer"
    elif isinstance(message, A2UIRendererMessage):
        schema_name = "renderer_to_agent"
    else:
        raise TypeError(
            f"validate_message expects an A2UIAgentMessage or A2UIRendererMessage, "
            f"got {type(message)!r}."
        )

    payload = serialize(message)
    schema = basic.load_spec(schema_name)
    registry = basic.schema_registry()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls(schema, registry=registry).validate(payload)


def _child_ids(component: Component) -> list[str]:
    """Every child component id ``component`` references (``child``/``children``)."""
    ids: list[str] = []
    if component.child is not None:
        ids.append(component.child)
    if isinstance(component.children, list):
        ids.extend(component.children)
    elif isinstance(component.children, ChildTemplate):
        ids.append(component.children.component_id)
    return ids


def validate_envelope(
    envelope: CreateSurface | UpdateComponents,
    *,
    origin: ProducerOrigin = ProducerOrigin.TOOL,
    surface_catalog_id: str | None = None,
) -> None:
    """Validate a v1.0 envelope's components against the catalog + structure rules.

    Reports ALL problems found (not just the first), so a producer's retry
    loop can re-prompt with full error context (spec §7).

    Checks:

    * Every component's ``catalogId`` resolves (:func:`resolve_catalog`) and
      names a known component (``UNKNOWN_COMPONENT``/``CATALOG_UNRESOLVED``).
    * Exactly one component has ``id == "root"`` (``MISSING_ROOT``).
    * No two components share an ``id`` (``DUPLICATE_ID``).
    * Every ``child``/``children`` reference points at an existing id
      (``DANGLING_CHILD``).
    * ``allowed_parents``/``allowed_children`` (when declared) are respected
      (``UNALLOWED_PARENT``/``UNALLOWED_CHILD``).
    * For ``origin=LLM``, no component carries a non-null ``action`` OR is
      registered with ``requires_actions=True``
      (``ACTION_NOT_ALLOWED_FOR_LLM`` — G2/D10b gate).

    Args:
        envelope: The :class:`CreateSurface`/:class:`UpdateComponents` envelope.
        origin: Producer origin. The action gate applies ONLY to
            :attr:`ProducerOrigin.LLM` envelopes.
        surface_catalog_id: The owning surface's default ``catalogId``. If
            omitted, falls back to ``envelope.catalog_id`` when present
            (``CreateSurface`` carries it; ``UpdateComponents`` does not, so
            callers updating an existing surface should pass it explicitly).

    Raises:
        CatalogValidationError: Aggregating every problem found, via ``.issues``.
    """
    effective_surface_catalog_id = surface_catalog_id or getattr(
        envelope, "catalog_id", None
    )

    components = envelope.components
    ids = [c.id for c in components]
    id_counts: dict[str, int] = {}
    for cid in ids:
        id_counts[cid] = id_counts.get(cid, 0) + 1

    issues: list[dict[str, Any]] = []
    unknown_components: list[str] = []
    action_components: list[str] = []

    if "root" not in ids:
        issues.append(
            {
                "code": MISSING_ROOT,
                "message": "No component with id 'root' found in the envelope.",
                "path": None,
            }
        )
    for cid, count in id_counts.items():
        if count > 1:
            issues.append(
                {
                    "code": DUPLICATE_ID,
                    "message": f"Component id {cid!r} is used {count} times.",
                    "path": cid,
                }
            )

    id_set = set(ids)
    for comp in components:
        for child_id in _child_ids(comp):
            if child_id not in id_set:
                issues.append(
                    {
                        "code": DANGLING_CHILD,
                        "message": f"Component {comp.id!r} references nonexistent child {child_id!r}.",
                        "path": comp.id,
                    }
                )

        try:
            resolved_catalog_id = resolve_catalog(
                comp.catalog_id, effective_surface_catalog_id
            )
        except CatalogValidationError as exc:
            issues.append(
                {"code": exc.code, "message": str(exc), "path": comp.id}
            )
        else:
            if not _component_exists(comp.component, resolved_catalog_id):
                unknown_components.append(comp.component)
                issues.append(
                    {
                        "code": UNKNOWN_COMPONENT,
                        "message": (
                            f"Component {comp.component!r} (id={comp.id!r}) is not "
                            f"registered under catalog {resolved_catalog_id!r}."
                        ),
                        "path": comp.id,
                    }
                )

        entry_for_gate = _CATALOG.get(comp.component)
        is_action_bearing = comp.action is not None or (
            entry_for_gate is not None and entry_for_gate.definition.requires_actions
        )
        if origin is ProducerOrigin.LLM and is_action_bearing:
            action_components.append(comp.component)
            issues.append(
                {
                    "code": ACTION_NOT_ALLOWED_FOR_LLM,
                    "message": (
                        f"LLM-produced envelopes may not contain an 'action' "
                        f"(component {comp.component!r}, id={comp.id!r})."
                    ),
                    "path": comp.id,
                }
            )

    by_id = {c.id: c for c in components}
    for comp in components:
        entry = _CATALOG.get(comp.component)
        allowed_children = entry.definition.allowed_children if entry else None
        for child_id in _child_ids(comp):
            child_comp = by_id.get(child_id)
            if child_comp is None:
                continue  # already reported as DANGLING_CHILD
            if allowed_children is not None and child_comp.component not in allowed_children:
                issues.append(
                    {
                        "code": UNALLOWED_CHILD,
                        "message": (
                            f"Component {comp.component!r} (id={comp.id!r}) does not "
                            f"allow child {child_comp.component!r} (id={child_id!r})."
                        ),
                        "path": comp.id,
                    }
                )
            child_entry = _CATALOG.get(child_comp.component)
            allowed_parents = child_entry.definition.allowed_parents if child_entry else None
            if allowed_parents is not None and comp.component not in allowed_parents:
                issues.append(
                    {
                        "code": UNALLOWED_PARENT,
                        "message": (
                            f"Component {child_comp.component!r} (id={child_id!r}) does "
                            f"not allow parent {comp.component!r} (id={comp.id!r})."
                        ),
                        "path": child_id,
                    }
                )

    if issues:
        summary = "; ".join(f"{i['code']}: {i['message']}" for i in issues)
        raise CatalogValidationError(
            summary,
            issues=issues,
            unknown_components=sorted(set(unknown_components)),
            action_components=sorted(set(action_components)),
        )
