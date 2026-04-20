"""Ontology Pre-Annotator adapter (FEAT-111 Module 5).

Wraps ``OntologyIntentResolver`` — which is soft-deprecated for strategy
routing — into a thin adapter that:

* Suppresses ``DeprecationWarning`` surgically (only during resolver calls).
* Returns a plain ``dict`` with keys like ``action``, ``pattern`` etc.
* No-ops cleanly when no resolver is configured.
* Swallows all resolver exceptions (logs WARNING + returns ``{}``).
* Works with both sync and async resolver methods (duck-typed).

Usage::

    from parrot.registry.routing import OntologyPreAnnotator

    adapter = OntologyPreAnnotator(resolver)          # or None
    annotations = await adapter.annotate("my query")  # → {"action": "graph_query", ...}
"""

from __future__ import annotations

import inspect
import logging
import warnings
from typing import Any, Optional

_logger = logging.getLogger(__name__)


class OntologyPreAnnotator:
    """Adapter that exposes ``OntologyIntentResolver`` as a simple annotator.

    Args:
        resolver: An ``OntologyIntentResolver`` instance, any object that
            supports ``resolve_intent(query)`` or ``resolve(query)`` (sync or
            async), or ``None`` for a no-op annotator.
    """

    def __init__(self, resolver: Optional[Any] = None) -> None:
        self._resolver = resolver

    async def annotate(self, query: str) -> dict:
        """Annotate *query* using the configured resolver.

        If no resolver is configured or any error occurs, returns ``{}``
        without raising.

        Args:
            query: The user query to annotate.

        Returns:
            A flat ``dict`` with keys such as ``action``, ``pattern``,
            ``aql``, ``suggested_post_action`` (and any extra fields the
            resolver might produce).  Empty dict when annotation is
            unavailable.
        """
        if self._resolver is None:
            return {}

        # Try resolve_intent first; fall back to resolve.
        method = getattr(self._resolver, "resolve_intent", None)
        if method is None:
            method = getattr(self._resolver, "resolve", None)
        if method is None:
            _logger.warning(
                "OntologyPreAnnotator: resolver %r has no resolve_intent or "
                "resolve method — returning empty annotations",
                type(self._resolver).__name__,
            )
            return {}

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                if inspect.iscoroutinefunction(method):
                    result = await method(query)
                else:
                    # Sync resolver — call directly (blocks briefly, acceptable
                    # since the fast-path resolver is deterministic and fast).
                    result = method(query)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "OntologyPreAnnotator: resolver raised an exception — "
                "returning empty annotations. Error: %s",
                exc,
            )
            return {}

        return _normalize_annotation(result)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_annotation(result: Any) -> dict:
    """Convert a resolver result into a plain ``dict``.

    Handles:
    * Already-a-dict: returned as-is.
    * Pydantic ``BaseModel`` (``IntentDecision``, ``ResolvedIntent``):
      ``model_dump(exclude_none=True)`` called.
    * Objects with public attributes (dataclasses, simple objects):
      extracted via ``vars()`` with fallback to manual attribute inspection.

    Unknown/unparseable results → empty dict.
    """
    if result is None:
        return {}

    if isinstance(result, dict):
        return result

    # Pydantic v2
    if hasattr(result, "model_dump"):
        try:
            return result.model_dump(exclude_none=True)
        except Exception:  # noqa: BLE001
            pass

    # Pydantic v1 / dataclasses / plain objects with instance __dict__
    if hasattr(result, "__dict__"):
        try:
            instance_attrs = {
                k: v for k, v in vars(result).items()
                if not k.startswith("_") and v is not None
            }
            if instance_attrs:
                return instance_attrs
        except Exception:  # noqa: BLE001
            pass

    # Last resort — attribute inspection (handles class-level attributes and
    # plain objects that expose known fields as class variables).
    try:
        _known = ("action", "pattern", "aql", "suggested_post_action",
                  "post_action", "post_query", "source")
        out = {}
        for attr in _known:
            val = getattr(result, attr, None)
            if val is not None:
                out[attr] = val
        return out
    except Exception:  # noqa: BLE001
        return {}
