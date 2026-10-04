"""Deterministic E2E gate and agentic exploration package (FEAT-581).

``parrot.e2e`` ships from ``ai-parrot-server`` (spec §2 Option B) and is
registered lazily in the core CLI's ``LazyGroup``. This ``__init__`` stays
deliberately light: it only re-exports the M2 schema/error surface (pure
Pydantic + stdlib, no side effects). Target/provider/supervisor modules
(``plan``, ``evidence``, ``supervisor``, ``runner``, ``cli``, ``targets/``)
land in later tasks and must not be imported here.
"""

from __future__ import annotations

from parrot.e2e.errors import (
    EXIT_BLOCKED,
    EXIT_CONFIG,
    EXIT_EVIDENCE,
    EXIT_FAILURE,
    EXIT_SIGINT,
    EXIT_SIGTERM,
    EXIT_SUCCESS,
    E2EBudgetError,
    E2EConfigError,
    E2EError,
    E2EEvidenceError,
    E2EPrerequisiteError,
    E2ETargetError,
)
from parrot.e2e.models import (
    E2EPlan,
    E2EVerdict,
    LiveBudget,
    ProcessIdentity,
    RunState,
    ScenarioResult,
    ScenarioSpec,
    SourceIdentity,
    TargetConfig,
    VerificationResult,
)

__all__ = [
    "EXIT_SUCCESS",
    "EXIT_FAILURE",
    "EXIT_CONFIG",
    "EXIT_BLOCKED",
    "EXIT_EVIDENCE",
    "EXIT_SIGINT",
    "EXIT_SIGTERM",
    "E2EError",
    "E2EConfigError",
    "E2EPrerequisiteError",
    "E2ETargetError",
    "E2EBudgetError",
    "E2EEvidenceError",
    "E2EPlan",
    "TargetConfig",
    "ScenarioSpec",
    "LiveBudget",
    "ProcessIdentity",
    "RunState",
    "SourceIdentity",
    "ScenarioResult",
    "E2EVerdict",
    "VerificationResult",
]
