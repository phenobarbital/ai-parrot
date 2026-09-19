"""Typed errors and exit-code mapping for the deterministic E2E gate (FEAT-581, M2).

Every raised error maps to exactly one CLI exit code defined by spec §2
"New Public Interfaces" (``sdd/specs/agentic-e2e-testing.spec.md``):

| Exit | Meaning for run/verify |
|---|---|
| 0 | Valid successful evidence / satisfied required coverage, or explicit policy ``none`` with no execution |
| 1 | Executed assertion, target, budget, teardown or coverage failure |
| 2 | Invalid plan, unsupported config/model, unsafe path or malformed evidence |
| 3 | Required prerequisite absent, or no codified scenario executed; BLOCKED |
| 4 | Missing/stale/revision-mismatched evidence, or source changed during execution |
| 130 / 143 | Interrupted by SIGINT / SIGTERM, after bounded cleanup and incomplete evidence |

This module has no target/provider imports and no side effects — it only
defines exception types and the exit-code constants other ``parrot.e2e``
modules (``runner.py``, ``cli.py``, out of this task's scope) translate
these into.
"""

from __future__ import annotations

from typing import Optional

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
]

# Exact §2 exit-code mapping.
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2
EXIT_BLOCKED = 3
EXIT_EVIDENCE = 4
EXIT_SIGINT = 130
EXIT_SIGTERM = 143


class E2EError(Exception):
    """Base class for every typed ``parrot.e2e`` error.

    Attributes:
        exit_code: The CLI process exit code this error class maps to (spec §2).
        reason_code: Optional machine-readable reason code recorded in evidence
            (e.g. persisted onto :class:`parrot.e2e.models.ScenarioResult.reason_code`
            or :class:`parrot.e2e.models.VerificationResult.reason_codes`).
    """

    exit_code: int = EXIT_FAILURE

    def __init__(self, message: str, *, reason_code: Optional[str] = None) -> None:
        """Initialize the error.

        Args:
            message: Human-readable description of the failure.
            reason_code: Optional machine-readable reason code.
        """
        super().__init__(message)
        self.reason_code = reason_code


class E2EConfigError(E2EError):
    """Invalid plan, unsupported config/model, unsafe path or malformed evidence.

    Maps to exit code 2. Raised before any target startup — e.g. by
    ``load_plan()`` for duplicate/missing nodes, path traversal, spec/plan
    policy mismatch or an arbitrary shell command in a target config.
    """

    exit_code = EXIT_CONFIG


class E2EPrerequisiteError(E2EError):
    """Required prerequisite absent, or no codified scenario executed.

    Maps to exit code 3 (BLOCKED). Raised for a missing service, a missing
    installed extra, or a required scenario that never ran.
    """

    exit_code = EXIT_BLOCKED


class E2ETargetError(E2EError):
    """Executed assertion, target or teardown failure.

    Maps to exit code 1. Raised for a target that failed to become ready,
    an executed assertion regression, or a target/runner cleanup failure —
    including when the underlying test assertions otherwise passed.
    """

    exit_code = EXIT_FAILURE


class E2EBudgetError(E2EError):
    """Live provider request/byte/output/deadline budget exhausted.

    Maps to exit code 1. Non-retryable: no fallback executes after this
    error, and no further network call may be attempted for the exhausted
    budget scope.
    """

    exit_code = EXIT_FAILURE


class E2EEvidenceError(E2EError):
    """Missing/stale/revision-mismatched evidence, or source changed during execution.

    Maps to exit code 4. Raised by ``verify_evidence()`` for an unknown or
    malformed schema, a source manifest mutation, or a spec/plan/environment
    hash mismatch between the run's recorded evidence and the current
    implementation identity.
    """

    exit_code = EXIT_EVIDENCE
