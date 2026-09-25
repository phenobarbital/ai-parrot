"""Procedures answering layer — retrieval, assembly, verification, and release."""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "READ_ROLES": "retrieval", "CURATOR_ROLE": "retrieval", "PATTERNS": "retrieval",
    "RequestContext": "retrieval", "AuthorizationDenied": "retrieval", "Clarification": "retrieval",
    "PatternPlan": "retrieval", "RetrievalResult": "retrieval", "classify": "retrieval",
    "ProcedureRetrieval": "retrieval", "AssembledProcedure": "assembly", "assemble_procedure": "assembly",
    "ProcedureVerifier": "verifier", "VerificationOutcome": "verifier", "AnswerProducer": "service",
    "AnswerOutcome": "service", "ProceduresAnswerService": "service", "ProceduresToolkit": "toolkit",
    "ProceduresAgent": "agent", "PROCEDURES_SYSTEM_PROMPT": "agent",
    "ProcedureAnswer": "parrot.knowledge.manuals.models",
}

__all__ = tuple(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve a public name on first access.

    Raises:
        AttributeError: When the requested name is not publicly exported.
    """
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    target = module_name if "." in module_name else f"{__name__}.{module_name}"
    value = getattr(importlib.import_module(target), name)
    globals()[name] = value
    return value
