"""LLM envelope producer with a catalog-validate-retry loop (Module 9, D1b).

The LLM produces A2UI envelopes only for freeform DISPLAY UI. This module wraps the
existing ``client.ask(..., structured_output=StructuredOutputConfig(output_type=CreateSurface))``
machinery — which silently degrades to raw text on a Pydantic ``ValidationError`` — with
a bounded catalog-validate-retry loop: validate against the catalog allowlist (LLM
origin, so ``requires_actions`` components are rejected — D10b), re-prompt with the
validation-error context on failure, and after the budget is exhausted **degrade to plain
text — never raw passthrough** (G1 survives the failure path).

Retry budget: SPK-3 (TASK-1727) recommended **3 attempts** (1 initial + 2 retries),
grounded in the ``OutputFormatter`` ``max_retries=2`` precedent; live validity numbers
were not obtainable in the spike environment, so this is the documented default.

One-way import rule (G8): no module-level import of LLM clients/agents/DatasetManager —
the ``client`` arrives as a call argument (typed loosely / via ``TYPE_CHECKING``).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ValidationError

from parrot.models.outputs import StructuredOutputConfig
from parrot.outputs.a2ui.catalog import (
    CatalogValidationError,
    ProducerOrigin,
    catalog_instructions,
    validate_envelope,
)
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.serialization import deserialize

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import (G8)
    from parrot.clients.base import AbstractClient

__all__ = ["DEFAULT_MAX_ATTEMPTS", "ProducerResult", "generate_envelope"]

logger = logging.getLogger(__name__)

#: SPK-3 (TASK-1727) recommended budget: 1 initial attempt + 2 catalog-validate retries.
DEFAULT_MAX_ATTEMPTS = 3


class ProducerResult(BaseModel):
    """Outcome of :func:`generate_envelope`.

    On success ``envelope`` is set and ``degraded`` is ``False``. On failure the invalid
    envelope is discarded (G1) and ``text`` carries the plain-text degradation.

    Attributes:
        envelope: The validated ``CreateSurface`` (``None`` when degraded).
        text: Plain-text degradation (``None`` on success).
        degraded: Whether the producer fell back to text.
        failure_reason: Machine-readable reason when degraded.
        attempts: Number of ``ask()`` attempts made.
    """

    model_config = {"arbitrary_types_allowed": True}

    envelope: Optional[CreateSurface] = None
    text: Optional[str] = None
    degraded: bool = False
    failure_reason: Optional[str] = None
    attempts: int = 0


def _extract_envelope(output: Any) -> tuple[Optional[CreateSurface], Optional[str]]:
    """Coerce a client ``output`` into a ``CreateSurface``.

    Returns ``(envelope, error)`` — exactly one is non-None. A raw-text/degraded output
    yields ``(None, <parse error>)`` (client degraded on ValidationError, spec §6).
    """
    if isinstance(output, CreateSurface):
        return output, None
    if isinstance(output, dict):
        # Parse via the serialization layer so a wire ``version`` field is stripped.
        try:
            message = deserialize(output)
        except (ValidationError, ValueError) as exc:
            return None, f"schema violation: {exc}"
        if isinstance(message, CreateSurface):
            return message, None
        return None, f"expected a createSurface envelope, got {type(message).__name__}"
    return None, "response degraded to raw text (not a CreateSurface envelope)"


def _repair_prompt(base_prompt: str, error_text: str, offending: Any) -> str:
    """Build a re-prompt carrying the catalog-validation error context."""
    fragment = ""
    if offending is not None:
        try:
            fragment = json.dumps(offending, default=str)[:800]
        except (TypeError, ValueError):
            fragment = str(offending)[:800]
    return (
        f"{base_prompt}\n\n"
        "Your previous A2UI envelope was rejected. Fix it and return ONLY a valid "
        "createSurface envelope.\n"
        f"Validation errors: {error_text}\n"
        + (f"Rejected fragment: {fragment}\n" if fragment else "")
        + "Use only the catalog components listed; do NOT use action-bearing components "
        "(forms/submit) — this is a display-only surface."
    )


async def generate_envelope(
    client: "AbstractClient",
    prompt: str,
    *,
    catalog: Any = None,  # reserved for per-catalog validation; global registry used today
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    model: str = "",
    system_prompt: Optional[str] = None,
) -> ProducerResult:
    """Produce a catalog-valid display ``CreateSurface`` via a bounded retry loop.

    Args:
        client: An ``AbstractClient`` exposing ``async ask(...)`` (passed in — not imported).
        prompt: The display-UI request.
        catalog: Reserved for a future per-catalog override; the global catalog is used.
        max_attempts: Total ``ask()`` attempts (default from SPK-3: 3).
        model: Model id forwarded to ``client.ask``.
        system_prompt: Optional base system prompt; the catalog instructions are appended.

    Returns:
        A :class:`ProducerResult` — either a validated envelope or a plain-text degradation.
    """
    instructions = catalog_instructions()
    system = (
        (system_prompt + "\n\n" if system_prompt else "")
        + "You produce ONLY an A2UI v1.0 createSurface envelope for the requested "
        "display UI, using these catalog components:\n" + instructions
    )
    config = StructuredOutputConfig(output_type=CreateSurface)

    current_prompt = prompt
    last_text: Optional[str] = None
    last_error = "no attempts made"

    for attempt in range(1, max(1, max_attempts) + 1):
        response = await client.ask(
            current_prompt,
            model=model,
            system_prompt=system,
            structured_output=config,
        )
        last_text = getattr(response, "response", None) or _stringify(
            getattr(response, "output", None)
        )
        envelope, parse_error = _extract_envelope(getattr(response, "output", None))

        if envelope is None:
            last_error = parse_error or "unparseable response"
            logger.warning(
                "A2UI producer attempt %d/%d: %s", attempt, max_attempts, last_error
            )
            current_prompt = _repair_prompt(prompt, last_error, getattr(response, "output", None))
            continue

        try:
            validate_envelope(envelope, origin=ProducerOrigin.LLM)
        except CatalogValidationError as exc:
            last_error = str(exc)
            logger.warning(
                "A2UI producer attempt %d/%d rejected by catalog: %s",
                attempt,
                max_attempts,
                last_error,
            )
            current_prompt = _repair_prompt(
                prompt, last_error, envelope.model_dump(by_alias=True, mode="json")
            )
            continue

        return ProducerResult(envelope=envelope, degraded=False, attempts=attempt)

    # Budget exhausted → plain-text degradation (never the raw invalid payload).
    logger.warning(
        "A2UI producer exhausted %d attempt(s); degrading to plain text. Last error: %s",
        max_attempts,
        last_error,
    )
    return ProducerResult(
        text=last_text or "",
        degraded=True,
        failure_reason=last_error,
        attempts=max_attempts,
    )


def _stringify(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, default=str)
    except (TypeError, ValueError):
        return str(output)
