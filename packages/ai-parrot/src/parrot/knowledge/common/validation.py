"""Verbatim-quote validation helpers shared by knowledge carding passes (FEAT-601 M1)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Iterable, Mapping, Optional

from .provenance import UNSUBSTANTIATED_CONFIDENCE_CAP, Evidence, Extracted

__all__ = ("normalize_whitespace", "quote_supported", "validate_extracted", "load_bodies")

logger = logging.getLogger(__name__)


def normalize_whitespace(text: str) -> str:
    """Collapse whitespace so re-wrapped quotes still match their source."""
    return " ".join(text.split())


def quote_supported(evidence: Optional[Evidence], bodies: Mapping[str, str]) -> bool:
    """Whether an evidence quote appears verbatim in its cited node body."""
    if evidence is None or not evidence.quote.strip():
        return False
    body = bodies.get(evidence.node_id)
    if not body:
        return False
    return normalize_whitespace(evidence.quote) in normalize_whitespace(body)


def validate_extracted(field: Extracted[Any], bodies: Mapping[str, str]) -> tuple[Extracted[Any], bool]:
    """Drop unsupported evidence and cap the resulting confidence."""
    if field.evidence is None and field.value is None:
        return field, False
    if quote_supported(field.evidence, bodies):
        return field, False
    updated = field.model_copy(
        update={
            "evidence": None,
            "confidence": min(field.confidence, UNSUBSTANTIATED_CONFIDENCE_CAP),
        }
    )
    return updated, field.evidence is not None


async def load_bodies(loader: Callable[[str], Optional[str]], node_ids: Iterable[str]) -> dict[str, str]:
    """Read node bodies off the event loop; returns only nonempty bodies keyed by node id."""
    ids = list(node_ids)

    def _read() -> dict[str, str]:
        bodies: dict[str, str] = {}
        for node_id in ids:
            try:
                body = loader(node_id)
            except Exception:  # noqa: BLE001 - a missing sidecar is not fatal
                logger.debug("Unreadable node body: %s", node_id)
                body = None
            if body and body.strip():
                bodies[node_id] = body
        return bodies

    return await asyncio.to_thread(_read)
