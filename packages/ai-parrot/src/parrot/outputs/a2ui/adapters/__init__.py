"""Deterministic adapters from legacy Parrot output models to A2UI envelopes.

Each adapter is a **pure function**: same input → byte-identical ``CreateSurface``.
No clocks, no uuids, no network, no LLM tokens — the D1a (tool-producer) lane of
spec FEAT-273 §1/G2 applied to output models that predate the A2UI catalog.

One-way import rule (spec G8): this subpackage imports only the a2ui core plus
pure Pydantic model modules under ``parrot.models``. It MUST NEVER import
``parrot.bots``, ``parrot.clients`` or ``parrot.tools.dataset_manager``.
"""

from parrot.outputs.a2ui.adapters.infographic import (
    CHART_TYPE_MAP,
    infographic_response_to_envelope,
)

__all__ = ["CHART_TYPE_MAP", "infographic_response_to_envelope"]
