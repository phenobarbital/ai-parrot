"""LLM envelope producer with a catalog-validate-retry loop (Module 9, D1b).

The LLM produces A2UI envelopes only for freeform DISPLAY UI. This module wraps the
existing ``client.ask(..., structured_output=StructuredOutputConfig(output_type=CreateSurface))``
machinery — which silently degrades to raw text on a Pydantic ``ValidationError`` — with
a bounded catalog-validate-retry loop: validate against the catalog allowlist (LLM
origin, so ``requires_actions`` components are rejected — D10b), re-prompt with the
validation-error context on failure, and after the budget is exhausted **degrade to plain
text — never raw passthrough** (G1 survives the failure path).

The ``CreateSurface`` fed to ``structured_output`` and validated against the catalog is
the A2UI **v1.0** wire model (:mod:`parrot.outputs.a2ui.models`, spec FEAT-470 §2); the
system prompt's :func:`~parrot.outputs.a2ui.catalog.catalog_instructions` covers BOTH the
official Basic Catalog (18 primitives) and the Parrot catalog (which ``$ref``-includes it)
— this module imports both catalog packages for their registration side effect (see
``generate_envelope``) so the instructions are complete regardless of import order
elsewhere in the process.

Retry budget: SPK-3 (TASK-1727) recommended **3 attempts** (1 initial + 2 retries),
grounded in the ``OutputFormatter`` ``max_retries=2`` precedent; live validity numbers
were not obtainable in the spike environment, so this is the documented default.

One-way import rule (G8): no module-level import of LLM clients/agents/DatasetManager —
the ``client`` arrives as a call argument (typed loosely / via ``TYPE_CHECKING``).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from parrot.models.outputs import StructuredOutputConfig
from parrot.outputs.a2ui.catalog import (
    CatalogValidationError,
    ProducerOrigin,
    catalog_instructions,
    validate_envelope,
)
from parrot.outputs.a2ui.models import A2UIAgentMessage, CreateSurface
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

    envelope: CreateSurface | None = None
    text: str | None = None
    degraded: bool = False
    failure_reason: str | None = None
    attempts: int = 0


def _extract_envelope(output: Any) -> tuple[CreateSurface | None, str | None]:
    """Coerce a client ``output`` into a ``CreateSurface``.

    Returns ``(envelope, error)`` — exactly one is non-None. A raw-text/degraded output
    yields ``(None, <parse error>)`` (client degraded on ValidationError, spec §6).

    Two dict shapes are accepted:

    * A **bare** ``CreateSurface`` payload — the realistic shape a client's
      structured-output machinery returns for ``output_type=CreateSurface``
      (no wire envelope wrapper; e.g. ``{"surfaceId": ..., "components": [...]}``).
    * A full **wire envelope-by-key** dict (``{"version": "v1.0", "createSurface":
      {...}}``) — e.g. if a caller round-trips the output through
      :func:`~parrot.outputs.a2ui.serialization.serialize` before handing it
      back here. Routed through :func:`~parrot.outputs.a2ui.serialization.deserialize`
      (v1.0 ``A2UIAgentMessage``, TASK-2533+) and unwrapped to its
      ``create_surface`` field.
    """
    if isinstance(output, CreateSurface):
        return output, None
    if isinstance(output, dict):
        if "createSurface" in output or "version" in output:
            try:
                message = deserialize(output)
            except (ValidationError, ValueError) as exc:
                return None, f"schema violation: {exc}"
            if isinstance(message, A2UIAgentMessage) and message.create_surface is not None:
                return message.create_surface, None
            return None, f"expected a createSurface envelope, got {type(message).__name__}"
        try:
            return CreateSurface.model_validate(output), None
        except ValidationError as exc:
            return None, f"schema violation: {exc}"
    return None, "response degraded to raw text (not a CreateSurface envelope)"


def _format_catalog_error(error: CatalogValidationError) -> str:
    """Render every structured issue as ``[CODE] message (path: /components/<id>)``.

    Surfaces the machine-readable ``code`` and a JSON-pointer-style ``path`` into
    the envelope's ``components`` array for EACH problem the catalog found — not
    just the first — so the re-prompt can target every offending component at
    once (spec §7 "reporta TODOS los errores"; Module 9 re-prompt requirement).
    """
    lines = []
    for issue in error.issues or [{"code": error.code, "message": str(error), "path": None}]:
        code = issue.get("code")
        message = issue.get("message")
        path = issue.get("path")
        pointer = f" (path: /components/{path})" if path else ""
        lines.append(f"- [{code}] {message}{pointer}")
    return "\n".join(lines)


def _repair_prompt(base_prompt: str, error: str | CatalogValidationError, offending: Any) -> str:
    """Build a re-prompt carrying the catalog-validation error context.

    Args:
        base_prompt: The original display-UI request.
        error: Either a plain parse-failure string (schema violation / raw-text
            degradation), or the :class:`CatalogValidationError` raised by
            :func:`~parrot.outputs.a2ui.catalog.validate_envelope` — in which
            case every issue's ``code`` and JSON-pointer ``path`` are rendered
            explicitly (see :func:`_format_catalog_error`) instead of a free-text
            summary, so the retry can address the exact problem.
        offending: The rejected envelope/output, embedded (truncated) as context.
    """
    error_text = _format_catalog_error(error) if isinstance(error, CatalogValidationError) else str(error)
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
        f"Validation errors:\n{error_text}\n"
        + (f"Rejected fragment: {fragment}\n" if fragment else "")
        + "Use only the catalog components listed; do NOT use action-bearing components "
        "(forms/submit) — this is a display-only surface. The envelope MUST contain "
        "exactly one component with id \"root\"."
    )


def _ensure_catalogs_registered() -> None:
    """Import both catalog packages for their component-registration side effect.

    :func:`~parrot.outputs.a2ui.catalog.catalog_instructions` only aggregates
    whatever is already registered in the process-wide catalog dict — it does
    not itself trigger registration. The Basic Catalog (18 primitives) and the
    Parrot catalog (which ``$ref``-includes it) each register on import, but
    nothing in THIS module's own import chain imports either eagerly (both are
    imported lazily elsewhere — e.g. ``builders.py`` imports ``catalog.parrot``,
    ``catalog/__init__.py`` imports ``catalog.basic`` only inside function
    bodies). Calling this before :func:`catalog_instructions` guarantees the
    system prompt covers BOTH catalogs regardless of what else has run first in
    the process (spec Module 9: "instructions básico + parrot").
    """
    import parrot.outputs.a2ui.catalog.basic
    import parrot.outputs.a2ui.catalog.parrot  # noqa: F401


async def generate_envelope(
    client: AbstractClient,
    prompt: str,
    *,
    catalog: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    model: str = "",
    system_prompt: str | None = None,
) -> ProducerResult:
    """Produce a catalog-valid display ``CreateSurface`` via a bounded retry loop.

    Args:
        client: An ``AbstractClient`` exposing ``async ask(...)`` (passed in — not imported).
        prompt: The display-UI request.
        catalog: Optional surface ``catalogId`` override, forwarded to
            :func:`~parrot.outputs.a2ui.catalog.validate_envelope` as
            ``surface_catalog_id`` (v1.0 catalog resolution, spec §2 G2). When
            omitted, resolution falls back to each component's own
            ``catalogId`` (the structured-output ``CreateSurface`` the LLM
            returns normally carries its own ``catalogId`` already).
        max_attempts: Total ``ask()`` attempts (default from SPK-3: 3).
        model: Model id forwarded to ``client.ask``.
        system_prompt: Optional base system prompt; the catalog instructions are appended.

    Returns:
        A :class:`ProducerResult` — either a validated envelope or a plain-text degradation.
    """
    _ensure_catalogs_registered()
    instructions = catalog_instructions()
    system = (
        (system_prompt + "\n\n" if system_prompt else "")
        + "You produce ONLY an A2UI v1.0 createSurface envelope for the requested "
        "display UI, using ONLY these catalog components (Basic Catalog + Parrot "
        "catalog):\n" + instructions + "\n\n"
        "Rule: the envelope MUST contain exactly one component with id \"root\" — "
        "every other component must be reachable from it via child/children."
    )
    config = StructuredOutputConfig(output_type=CreateSurface)

    current_prompt = prompt
    last_text: str | None = None
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
            validate_envelope(envelope, origin=ProducerOrigin.LLM, surface_catalog_id=catalog)
        except CatalogValidationError as exc:
            last_error = str(exc)
            logger.warning(
                "A2UI producer attempt %d/%d rejected by catalog: %s",
                attempt,
                max_attempts,
                last_error,
            )
            current_prompt = _repair_prompt(
                prompt, exc, envelope.model_dump(by_alias=True, mode="json")
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
