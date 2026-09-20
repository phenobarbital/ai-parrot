"""Comparison stage of the planogram cycle: slots definition, registration, scoring, projection."""

from .definition import (
    Descriptors,
    FacingDefinition,
    RuleBinding,
    ShelfDefinition,
    SlotsDefinition,
    SlotsDefinitionError,
    ZoneDefinition,
    definition_coverage,
    load_slots_definition,
    validate_bindings,
)

__all__ = [
    "Descriptors",
    "FacingDefinition",
    "RuleBinding",
    "ShelfDefinition",
    "SlotsDefinition",
    "SlotsDefinitionError",
    "ZoneDefinition",
    "definition_coverage",
    "load_slots_definition",
    "validate_bindings",
]
