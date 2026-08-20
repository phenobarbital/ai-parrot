"""GraphIndex Retrieval Layer (L2) — FEAT-435.

Turns a natural-language question into a bounded, attributable
``ContextBundle`` over the existing structural code graph (L0), with an
optional LLM-synthesized wiki cache (L1) in between.

This package consumes ``parrot.knowledge.graphindex`` (L0) **read-only**
(spec §1.2) and does not modify or refactor the shipped
``GraphExpandedRetriever`` / ``GraphIndexOrigin`` (FEAT-217 / FEAT-379).

See ``sdd/specs/graphindex-retriever.spec.md`` (FEAT-435) for the full
design and invariants.

The public surface here grows task by task; re-export new symbols as they
land so downstream code can do ``from parrot.knowledge.retrieval import X``.
"""

from parrot.knowledge.retrieval.models import EdgeRef, NodeRef

__all__ = [
    "EdgeRef",
    "NodeRef",
]
