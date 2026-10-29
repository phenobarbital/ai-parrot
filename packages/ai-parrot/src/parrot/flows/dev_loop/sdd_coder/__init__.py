"""`sdd_coder` — orchestration kernel behind the `parrot-sdd-coder` MCP server (FEAT-549).

Composes the FEAT-323 dev-loop primitives (TaskScheduler, SubWorktreeManager,
build_dispatcher) so the interactive `sdd-worker` can run one task per seat in
parallel. Import from submodules only (see agent_pool.py module docstring).

Public names are resolved lazily (PEP 562) so that importing one submodule (e.g. ``fidelity`` or
``checkpoint``) does not load the roster, the engine or navconfig (FEAT-633 R9).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from parrot.flows.dev_loop.sdd_coder.models import (
        ERROR_CODES, AttemptRecord, CleanupReport, CoderError, CoderJob, CoderPlan, CoderResult,
        NativePrep, OrphanBranch, PlanChunk, PlannedTask, RosterConfig, RosterSeat,
        SeatKind, SeatProbeResult, TaskOutcome, TaskResult,
        CoderPlanArgs, CoderRunChunkArgs, CoderPrepareNativeArgs, CoderMergeArgs,
        CoderWaitArgs, CoderStatusArgs, CoderCleanupArgs,
    )
    from parrot.flows.dev_loop.sdd_coder.roster import ChunkAssigner, RosterProbe, available_seats
    from parrot.flows.dev_loop.sdd_coder.engine import AttemptTelemetryCollector, CoderFailure, SddCoderEngine
    from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit

_LAZY_EXPORTS: dict[str, str] = {
    "ERROR_CODES": "models",
    "AttemptRecord": "models",
    "CleanupReport": "models",
    "CoderError": "models",
    "CoderJob": "models",
    "CoderPlan": "models",
    "CoderResult": "models",
    "NativePrep": "models",
    "OrphanBranch": "models",
    "PlanChunk": "models",
    "PlannedTask": "models",
    "RosterConfig": "models",
    "RosterSeat": "models",
    "SeatKind": "models",
    "SeatProbeResult": "models",
    "TaskOutcome": "models",
    "TaskResult": "models",
    "CoderPlanArgs": "models",
    "CoderRunChunkArgs": "models",
    "CoderPrepareNativeArgs": "models",
    "CoderMergeArgs": "models",
    "CoderWaitArgs": "models",
    "CoderStatusArgs": "models",
    "CoderCleanupArgs": "models",
    "ChunkAssigner": "roster",
    "RosterProbe": "roster",
    "available_seats": "roster",
    "CoderFailure": "engine",
    "SddCoderEngine": "engine",
    "AttemptTelemetryCollector": "engine",
    "SddCoderToolkit": "toolkit",
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Import the submodule defining ``name`` on first access and cache the attribute (PEP 562)."""
    submodule = _LAZY_EXPORTS.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{submodule}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Advertise the lazy exports alongside the module globals."""
    return sorted({*globals(), *__all__})
