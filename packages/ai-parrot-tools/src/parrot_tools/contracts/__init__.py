"""Contracts answering layer — toolkit, agents, flow and jobs (FEAT-539).

The core data plane lives in ``parrot.knowledge.contracts``; this satellite
package owns everything agent-facing: deterministic authorized retrieval,
the citation verifier, the shared answer service, the toolkit, the ReAct
agent, the fixed answer flow, the watcher jobs and the operator CLI.

Retrieval is LLM-free by construction and every protected read passes the
same authorization gate.
"""

from __future__ import annotations

from .retrieval import (
    MAX_TOP_K,
    PATTERNS,
    READ_ROLES,
    AuthorizationDenied,
    Clarification,
    ContractRetrieval,
    PatternPlan,
    RequestContext,
    RetrievalResult,
    classify,
)

__all__ = (
    "MAX_TOP_K",
    "PATTERNS",
    "READ_ROLES",
    "AuthorizationDenied",
    "Clarification",
    "ContractRetrieval",
    "PatternPlan",
    "RequestContext",
    "RetrievalResult",
    "classify",
)
