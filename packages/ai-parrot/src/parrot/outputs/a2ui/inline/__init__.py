"""Inline A2UI component authoring for a single chat turn (FEAT-755)."""

from parrot.outputs.a2ui.inline.emitter import (
    PRESENTATION_EXTENSION,
    InlineEmitOutcome,
    emit_inline_component,
    extract_component_config,
    presentation_extension,
)
from parrot.outputs.a2ui.inline.feasibility import FeasibilityResult, check_feasibility
from parrot.outputs.a2ui.inline.prompt import (
    INLINE_AUTHORING_NOTES,
    INLINE_COMPONENTS,
    build_component_prompt,
)

__all__ = [
    "PRESENTATION_EXTENSION",
    "InlineEmitOutcome",
    "emit_inline_component",
    "extract_component_config",
    "presentation_extension",
    "FeasibilityResult",
    "check_feasibility",
    "INLINE_AUTHORING_NOTES",
    "INLINE_COMPONENTS",
    "build_component_prompt",
]
