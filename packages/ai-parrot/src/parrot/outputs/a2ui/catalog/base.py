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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DEFAULT_CATALOG_ID",
    "BasicNode",
    "BasicTree",
    "CatalogError",
    "CatalogValidationError",
    "ComponentContractError",
    "ComponentDefinition",
    "ProducerOrigin",
    "RegisteredComponent",
]

#: The Parrot custom catalog id. Extends the A2UI Basic Catalog (spec D2).
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"


class ProducerOrigin(str, Enum):
    """Origin of an envelope, controlling ``requires_actions`` enforcement.

    Tool builders emit envelopes deterministically and MAY include action-bearing
    components (they degrade to deep links at render time). The LLM producer path
    is display-only in v1 and MUST NOT emit ``requires_actions`` components.
    """

    TOOL = "tool"
    LLM = "llm"


class BasicNode(BaseModel):
    """A node in a lowered A2UI *Basic Catalog* tree.

    The output of a component's ``lower()`` is a nested tree of Basic Catalog
    primitives (e.g. ``Column``, ``Row``, ``Text``, ``Image``). Unlike the wire
    :class:`~parrot.outputs.a2ui.models.Component` (a flat adjacency list keyed by
    id), a lowered tree nests its ``children`` directly — this is an internal,
    render-facing representation, not a wire message.

    Attributes:
        component: Basic Catalog component name.
        properties: Declarative properties for the primitive.
        children: Nested child nodes (fleshed out further in Module 3).
    """

    model_config = ConfigDict(extra="allow")

    component: str
    properties: dict[str, Any] = Field(default_factory=dict)
    children: list["BasicNode"] = Field(default_factory=list)


#: A lowered Basic Catalog tree is rooted at a single :class:`BasicNode`.
BasicTree = BasicNode


class ComponentDefinition(BaseModel):
    """Metadata describing a registered catalog component (spec §2 Data Models).

    Attributes:
        name: Component type name (e.g. ``"Infographic"``).
        catalog_id: Owning catalog id; defaults to the Parrot custom catalog.
        schema_: JSON-Schema for the component payload (wire/dump alias ``schema``).
        instructions: Embedded LLM guidance for producing this component (A2UI spec).
        requires_actions: Whether the component is action-bearing (D10b gate).
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    catalog_id: str = DEFAULT_CATALOG_ID
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    instructions: str = ""
    requires_actions: bool = False


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
    """Raised when an envelope fails catalog allowlist / ``requires_actions`` checks.

    Attributes:
        unknown_components: Component names not present in the catalog.
        action_components: Action-bearing component names rejected for an
            LLM-produced envelope.
    """

    def __init__(
        self,
        message: str,
        *,
        unknown_components: list[str] | None = None,
        action_components: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.unknown_components = unknown_components or []
        self.action_components = action_components or []
