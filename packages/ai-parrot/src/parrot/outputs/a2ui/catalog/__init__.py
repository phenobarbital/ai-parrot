"""A2UI component catalog — public decorator, lookup, and envelope validation.

Registration pattern mirrors :func:`parrot.outputs.formats.register_renderer`
(module-level registry dict + decorator that inserts and returns the class), with
the added registration-time enforcement of the mandatory ``lower()`` contract.

A registrable component class MUST:

* implement a callable ``lower(self, component, data_model) -> BasicTree``
  (pure and deterministic — golden-file tested in Module 3); and
* optionally expose class attributes ``SCHEMA`` (dict) and ``INSTRUCTIONS`` (str),
  which the decorator folds into the component's :class:`ComponentDefinition`.
"""

from __future__ import annotations

import logging
from typing import Callable

from parrot.outputs.a2ui.catalog.base import (
    DEFAULT_CATALOG_ID,
    BasicNode,
    BasicTree,
    CatalogError,
    CatalogValidationError,
    ComponentContractError,
    ComponentDefinition,
    ProducerOrigin,
    RegisteredComponent,
)
from parrot.outputs.a2ui.models import CreateSurface

__all__ = [
    "BasicNode",
    "BasicTree",
    "CatalogError",
    "CatalogValidationError",
    "ComponentContractError",
    "ComponentDefinition",
    "DEFAULT_CATALOG_ID",
    "ProducerOrigin",
    "RegisteredComponent",
    "catalog_instructions",
    "get_component",
    "list_components",
    "register_component",
    "unregister_component",
    "validate_envelope",
]

logger = logging.getLogger(__name__)

#: Global component allowlist, keyed by component name.
_CATALOG: dict[str, RegisteredComponent] = {}


def register_component(
    name: str,
    *,
    requires_actions: bool = False,
    catalog_id: str = DEFAULT_CATALOG_ID,
) -> Callable[[type], type]:
    """Register a catalog component under ``name``.

    Enforces the mandatory lowering contract at registration time: a class without
    a callable ``lower()`` cannot register (raises :class:`ComponentContractError`).

    Args:
        name: The component type name used in envelopes (e.g. ``"Chart"``).
        requires_actions: Marks the component as action-bearing (D10b). LLM-produced
            envelopes containing it are rejected by :func:`validate_envelope`.
        catalog_id: Owning catalog id; defaults to the Parrot custom catalog.

    Returns:
        The class decorator.

    Raises:
        ComponentContractError: If the decorated class lacks a callable ``lower()``.
    """

    def decorator(cls: type) -> type:
        lower = getattr(cls, "lower", None)
        if not callable(lower):
            raise ComponentContractError(
                f"Component {name!r} ({cls.__name__}) cannot register: it must "
                "implement a callable lower(self, component, data_model) -> BasicTree "
                "(spec G4 — lowering is enforced, not conventional)."
            )
        definition = ComponentDefinition(
            name=name,
            catalog_id=catalog_id,
            schema=dict(getattr(cls, "SCHEMA", {}) or {}),
            instructions=str(getattr(cls, "INSTRUCTIONS", "") or ""),
            requires_actions=requires_actions,
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


def catalog_instructions() -> str:
    """Aggregate every component's embedded ``instructions`` for the LLM producer.

    Returns:
        A newline-joined block of ``<name>: <instructions>`` lines, name-sorted.
    """
    lines = [
        f"{d.name}: {d.instructions}".rstrip(": ").rstrip()
        for d in list_components()
        if d.instructions
    ]
    return "\n".join(lines)


def _iter_nested_component_names(value: object) -> "list[str]":
    """Recursively collect nested catalog-component names from a property value.

    Composite components (Infographic/Report) embed child components as inline
    ``{"component": <name>, "properties": {...}}`` descriptors inside their
    properties (e.g. ``sections[].components[]``). Those names must also pass the
    allowlist, or a hallucinated nested name would only surface as a render-time
    ``KeyError`` — bypassing the producer's bounded-retry/degrade guarantee.
    """
    found: list[str] = []
    if isinstance(value, dict):
        name = value.get("component")
        if isinstance(name, str):
            found.append(name)
            found.extend(_iter_nested_component_names(value.get("properties")))
            for key, item in value.items():
                if key not in ("component", "properties"):
                    found.extend(_iter_nested_component_names(item))
        else:
            for item in value.values():
                found.extend(_iter_nested_component_names(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_iter_nested_component_names(item))
    return found


def validate_envelope(
    envelope: CreateSurface,
    *,
    origin: ProducerOrigin = ProducerOrigin.TOOL,
) -> None:
    """Validate an envelope against the catalog allowlist and the action gate.

    Walks the envelope's top-level component adjacency list AND every nested
    composite child descriptor. Reports ALL problems (not just the first) so
    Module 9's retry loop can re-prompt with full error context.

    Args:
        envelope: The :class:`CreateSurface` envelope to validate.
        origin: Producer origin. ``requires_actions`` rejection applies ONLY to
            :attr:`ProducerOrigin.LLM` envelopes.

    Raises:
        CatalogValidationError: If any component (top-level or nested) is unknown,
            or (for LLM origin) any component is action-bearing.
    """
    names: list[str] = []
    for comp in envelope.components:
        names.append(comp.component)
        names.extend(_iter_nested_component_names(comp.properties))

    unknown: list[str] = []
    action_bearing: list[str] = []
    for name in names:
        entry = _CATALOG.get(name)
        if entry is None:
            unknown.append(name)
            continue
        if origin is ProducerOrigin.LLM and entry.definition.requires_actions:
            action_bearing.append(name)

    problems: list[str] = []
    if unknown:
        problems.append(
            f"Unknown component(s) not in catalog {DEFAULT_CATALOG_ID}: "
            f"{sorted(set(unknown))}"
        )
    if action_bearing:
        problems.append(
            "LLM-produced envelopes may not contain action-bearing component(s) "
            f"in v1: {sorted(set(action_bearing))}"
        )
    if problems:
        raise CatalogValidationError(
            "; ".join(problems),
            unknown_components=sorted(set(unknown)),
            action_components=sorted(set(action_bearing)),
        )
