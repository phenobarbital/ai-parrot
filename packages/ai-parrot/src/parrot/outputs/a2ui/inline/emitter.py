"""Inline A2UI component emitter (FEAT-755).

Turns the component config the LLM authored in the main turn into a validated A2UI
envelope on ``response.a2ui_envelope``, stamped with the surface-level
``parrot_presentation`` marker so a renderer knows it was produced as an inline chat
answer rather than inferring it from the root component.

NEVER raises (spec G3): every failure is a ``degraded`` outcome and the caller's
existing ``DEFAULT`` degradation takes over.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Final, Literal, NamedTuple, Optional
from uuid import uuid4

from parrot.outputs.a2ui.builders import build_surface
from parrot.outputs.a2ui.catalog import ProducerOrigin
from parrot.outputs.a2ui.emission import finalize_a2ui_response
from parrot.outputs.a2ui.inline.feasibility import check_feasibility
from parrot.outputs.a2ui.inline.prompt import INLINE_COMPONENTS
from parrot.outputs.a2ui.models import Extensions, SurfaceMetadata
from parrot.outputs.a2ui.serialization import serialize

logger = logging.getLogger(__name__)

__all__ = [
    "PRESENTATION_EXTENSION",
    "InlineEmitOutcome",
    "presentation_extension",
    "extract_component_config",
    "emit_inline_component",
]

PRESENTATION_EXTENSION: Final[str] = "parrot_presentation"


class InlineEmitOutcome(NamedTuple):
    """What the emitter did, for logging and for ``response.metadata['a2ui_inline']``."""

    status: Literal["emitted", "degraded"]
    component: str
    reason: Optional[str] = None
    surface_id: Optional[str] = None


def presentation_extension(component: str) -> dict[str, Any]:
    """Return the surface-level marker payload for ``component``.

    Args:
        component: Catalog component name.

    Returns:
        The renderer-facing inline presentation marker.
    """
    return {"kind": "widget", "inline": True, "origin": "chat_turn", "component": component}


def _json_object_from_text(content: str) -> Optional[dict[str, Any]]:
    """Parse the first fenced or bare JSON object in ``content``.

    Args:
        content: Provider-authored text which may contain a JSON object.

    Returns:
        The parsed object, or ``None`` when no candidate is a valid JSON object.
    """
    candidates: list[str] = []
    candidates.extend(re.findall(r"```json\s*\n(.*?)```", content, re.DOTALL | re.IGNORECASE))
    candidates.extend(re.findall(r"```\s*\n(.*?)```", content, re.DOTALL))

    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_component_config(response: Any) -> Optional[dict[str, Any]]:
    """Pull the component config off ``response``.

    ``response.structured_output`` is primary. Pydantic-like models are dumped with
    aliases and without ``None`` values; dictionaries are used directly. Text in
    ``response.output`` and then ``response.content`` is retained as a fallback for
    providers which do not honor structured output on tool-using turns.

    Args:
        response: An AIMessage-like response object.

    Returns:
        The extracted component configuration, or ``None`` when none parses.
    """
    try:
        structured = getattr(response, "structured_output", None)
        if isinstance(structured, dict):
            return structured
        model_dump = getattr(structured, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(by_alias=True, exclude_none=True)
            if isinstance(dumped, dict):
                return dumped
    except Exception as exc:  # noqa: BLE001 - continue to the text fallback
        logger.warning("Structured inline component config extraction failed: %s", exc)

    try:
        for attribute in ("output", "content"):
            content = getattr(response, attribute, None)
            if isinstance(content, str):
                parsed = _json_object_from_text(content)
                if parsed is not None:
                    return parsed
    except Exception as exc:  # noqa: BLE001 - extraction is part of the never-raise boundary
        logger.warning("Text inline component config extraction failed: %s", exc)
    return None


def _write_outcome(response: Any, outcome: InlineEmitOutcome) -> bool:
    """Write the emitter side channel without allowing malformed responses to escape.

    Args:
        response: An AIMessage-like response object.
        outcome: Outcome to record.

    Returns:
        Whether the metadata side channel was written.
    """
    try:
        metadata = getattr(response, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            response.metadata = metadata
        metadata["a2ui_inline"] = outcome._asdict()
        return True
    except Exception as exc:  # noqa: BLE001 - malformed response objects must not escape
        logger.warning("Could not record inline A2UI outcome: %s", exc)
        return False


def _degraded(response: Any, component: str, reason: str) -> InlineEmitOutcome:
    """Return and record a degraded outcome while clearing a partial envelope.

    Args:
        response: An AIMessage-like response object.
        component: Requested component name.
        reason: Fixed degradation reason code.

    Returns:
        The recorded degraded outcome.
    """
    try:
        response.a2ui_envelope = None
    except Exception as exc:  # noqa: BLE001 - malformed response objects must not escape
        logger.warning("Could not clear inline A2UI envelope: %s", exc)
    outcome = InlineEmitOutcome(status="degraded", component=component, reason=reason)
    _write_outcome(response, outcome)
    return outcome


def emit_inline_component(
    response: Any,
    component: str,
    *,
    frame: Any | None = None,
    surface_id: Optional[str] = None,
) -> InlineEmitOutcome:
    """Author, validate and attach an inline A2UI envelope. Never raises.

    The pipeline checks the inline allowlist, extracts and checks the authored config,
    validates a surface through :func:`build_surface`, serializes it, and finalizes the
    response. ``response.metadata['a2ui_inline']`` is written on normal emitted and
    degraded outcomes.

    Args:
        response: An AIMessage-like response object mutated only on success.
        component: Requested catalog component name.
        frame: Optional source frame used by feasibility rules.
        surface_id: Optional caller-supplied surface identifier.

    Returns:
        The emitted or degraded outcome.
    """
    missing = object()
    original_envelope: Any = missing
    original_output_mode: Any = missing

    try:
        original_envelope = getattr(response, "a2ui_envelope", missing)
        original_output_mode = getattr(response, "output_mode", missing)
        if component not in INLINE_COMPONENTS:
            return _degraded(response, component, "component_not_inline")

        config = extract_component_config(response)
        if config is None:
            return _degraded(response, component, "config_unparseable")

        feasibility = check_feasibility(component, config, frame)
        if not feasibility.feasible:
            return _degraded(response, component, feasibility.reason or "unexpected_error")

        sid = surface_id or f"{component.lower()}-{uuid4().hex[:8]}"
        try:
            surface = build_surface(
                component,
                config,
                surface_id=sid,
                origin=ProducerOrigin.LLM,
                surface_metadata=SurfaceMetadata(
                    extensions=Extensions(
                        root={PRESENTATION_EXTENSION: presentation_extension(component)}
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001 - validation failures degrade by contract
            logger.warning("Inline A2UI catalog validation failed for %s: %s", component, exc)
            return _degraded(response, component, "catalog_validation_failed")

        response.a2ui_envelope = serialize(surface)
        finalize_a2ui_response(response)
        outcome = InlineEmitOutcome(status="emitted", component=component, surface_id=sid)
        if not _write_outcome(response, outcome):
            raise RuntimeError("could not record emitted inline A2UI outcome")
        return outcome
    except Exception as exc:  # noqa: BLE001 - G3: no emitter exception may escape
        logger.warning("Inline A2UI emission failed unexpectedly for %s: %s", component, exc)
        try:
            if original_envelope is missing:
                delattr(response, "a2ui_envelope")
            else:
                response.a2ui_envelope = original_envelope
            if original_output_mode is missing:
                delattr(response, "output_mode")
            else:
                response.output_mode = original_output_mode
        except Exception as rollback_exc:  # noqa: BLE001 - malformed responses must not escape
            logger.warning("Could not roll back inline A2UI response: %s", rollback_exc)
        return _degraded(response, component, "unexpected_error")
