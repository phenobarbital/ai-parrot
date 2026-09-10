"""`sdd_coder` — orchestration kernel behind the `parrot-sdd-coder` MCP server (FEAT-549).

Composes the FEAT-323 dev-loop primitives (TaskScheduler, SubWorktreeManager,
build_dispatcher) so the interactive `sdd-worker` can run one task per seat in
parallel. Import from submodules only (see agent_pool.py module docstring).
"""
from parrot.flows.dev_loop.sdd_coder.models import (  # noqa: F401
    ERROR_CODES, AttemptRecord, CleanupReport, CoderError, CoderJob, CoderPlan, CoderResult,
    NativePrep, OrphanBranch, PlanChunk, PlannedTask, RosterConfig, RosterSeat,
    SeatKind, SeatProbeResult, TaskOutcome, TaskResult,
    CoderPlanArgs, CoderRunChunkArgs, CoderPrepareNativeArgs, CoderMergeArgs,
    CoderWaitArgs, CoderStatusArgs, CoderCleanupArgs,
)
from parrot.flows.dev_loop.sdd_coder.roster import ChunkAssigner, RosterProbe, available_seats  # noqa: F401
from parrot.flows.dev_loop.sdd_coder.engine import AttemptTelemetryCollector, CoderFailure, SddCoderEngine  # noqa: F401
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit  # noqa: F401

__all__ = [
    "ERROR_CODES", "AttemptRecord", "CleanupReport", "CoderError", "CoderJob", "CoderPlan",
    "CoderResult", "NativePrep", "OrphanBranch", "PlanChunk", "PlannedTask", "RosterConfig",
    "RosterSeat", "SeatKind", "SeatProbeResult", "TaskOutcome", "TaskResult",
    "CoderPlanArgs", "CoderRunChunkArgs", "CoderPrepareNativeArgs", "CoderMergeArgs",
    "CoderWaitArgs", "CoderStatusArgs", "CoderCleanupArgs",
    "ChunkAssigner", "RosterProbe", "available_seats",
    "CoderFailure", "SddCoderEngine", "AttemptTelemetryCollector", "SddCoderToolkit",
]
