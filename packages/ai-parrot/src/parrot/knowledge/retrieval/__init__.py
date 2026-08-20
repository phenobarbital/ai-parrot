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

from parrot.knowledge.retrieval.classifier import (
    EscalationStep,
    GraphStats,
    QueryClass,
    QueryClassifier,
    RetrievalRoutingDecision,
)
from parrot.knowledge.retrieval.digest import DigestScope, derive_digest
from parrot.knowledge.retrieval.exceptions import IndexPinMismatchError, StalePinError
from parrot.knowledge.retrieval.features import QueryFeatures, extract_features
from parrot.knowledge.retrieval.lexicon import (
    DEFAULT_LEXICON,
    CompiledMarkerLexicon,
    Interrogative,
    MarkerLexicon,
)
from parrot.knowledge.retrieval.models import (
    ContextBundle,
    ContextUnit,
    EdgeRef,
    Evidence,
    EvidenceOrigin,
    NodeRef,
    RetrievalBudget,
    RetrievalRequest,
)
from parrot.knowledge.retrieval.pin import (
    CoherenceReport,
    WorkspacePin,
    check_pin_coherence,
    read_at_rev,
    resolve_workspace,
)
from parrot.knowledge.retrieval.policies import (
    DirectSymbolPolicy,
    RetrievalPolicyProtocol,
    Seed,
    Subgraph,
)
from parrot.knowledge.retrieval.sections import (
    GOTCHA_TAGS,
    RATIONALE_TAGS,
    SectionKind,
    SectionSelector,
    selector_for,
)
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex

__all__ = [
    "DEFAULT_LEXICON",
    "GOTCHA_TAGS",
    "RATIONALE_TAGS",
    "CoherenceReport",
    "CompiledMarkerLexicon",
    "ContextBundle",
    "ContextUnit",
    "DerivedSymbolIndex",
    "DigestScope",
    "DirectSymbolPolicy",
    "EdgeRef",
    "EscalationStep",
    "Evidence",
    "EvidenceOrigin",
    "GraphStats",
    "IndexPinMismatchError",
    "Interrogative",
    "MarkerLexicon",
    "NodeRef",
    "QueryClass",
    "QueryClassifier",
    "QueryFeatures",
    "RetrievalBudget",
    "RetrievalPolicyProtocol",
    "RetrievalRequest",
    "RetrievalRoutingDecision",
    "SectionKind",
    "SectionSelector",
    "Seed",
    "StalePinError",
    "Subgraph",
    "WorkspacePin",
    "check_pin_coherence",
    "derive_digest",
    "extract_features",
    "read_at_rev",
    "resolve_workspace",
    "selector_for",
]
