"""Checkpoint-derived run resolution for ExecutionPlanToolkit (FEAT-585 M3).

The checkpoint is the SOLE persisted execution state (spec §2, §8 D3): there is
no receipt store, tombstone or second persisted run object. Everything an
agent-facing tool needs — status, artifacts, resume eligibility, repair
lineage — is derived fresh from the latest checkpoint(s) by this module.

Registration (`register_plan_checkpoint_types`) must run before ANY checkpoint
encode or decode touches an `ArtifactRef` — otherwise `FlowStateSerializer`
degrades it to a lossy repr (finding R1) and `project_run` fails closed with
`checkpoint_invalid` rather than silently trusting a `repr()` string.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
from typing import Dict, List, Optional, Tuple

from parrot.bots.flows.core.checkpoint import (
    CheckpointStore,
    FlowCheckpoint,
    FlowStateSerializer,
    register_checkpoint_type,
)
from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, build_manifest
from parrot.tools.working_memory.task_memory.models import TaskScope

from .models import (
    PLAN_RUN_SHARED_KEY,
    PlanRecoveryEnvelope,
    PlanRun,
    PlanRunError,
    PlanRunMetadata,
    ResumeLevel,
    RunStatus,
)

__all__ = (
    "PlanRunResolver",
    "classify_miss",
    "plan_fingerprint",
    "process_identity",
    "project_run",
    "read_run_metadata",
    "register_plan_checkpoint_types",
    "select_latest",
)
_logger = logging.getLogger(__name__)
_TERMINAL = frozenset({"completed", "failed"})
# Statuses (checkpoint-level, or derived "partial") that still permit a
# resume attempt provided undispatched/pending nodes remain (spec §2 Recovery
# capabilities). "completed" is deliberately excluded — a completed run is
# never resumable, even with cross-restart storage.
_RESUMABLE_CHECKPOINT_STATUSES = frozenset({"running", "suspended", "failed"})


def register_plan_checkpoint_types() -> None:
    """Idempotently register ArtifactRef before any checkpoint encode or decode (R1)."""
    register_checkpoint_type(ArtifactRef)


def process_identity() -> str:
    """``host:pid`` — identity of memory-mode artifacts (§2)."""
    return f"{socket.gethostname()}:{os.getpid()}"


def plan_fingerprint(plan: ExecutionPlan) -> str:
    """sha256 over canonical JSON of the effective plan."""
    return hashlib.sha256(
        json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_run_metadata(checkpoint: FlowCheckpoint) -> PlanRunMetadata:
    """Parse the ``plan_run`` envelope; anything malformed is ``checkpoint_invalid``."""
    raw = checkpoint.context.shared_data.get(PLAN_RUN_SHARED_KEY)
    if not isinstance(raw, dict):
        raise PlanRunError(
            "checkpoint_invalid", f"checkpoint {checkpoint.flow_id}@{checkpoint.checkpoint_id} has no plan_run envelope"
        )
    try:
        return PlanRunMetadata.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - converted to a bounded structured error
        raise PlanRunError("checkpoint_invalid", f"plan_run envelope rejected: {str(exc)[:300]}") from exc


def _derive_run_state(
    *,
    checkpoint_status: str,
    metadata: PlanRunMetadata,
    refs: List[ArtifactRef],
    dispatched_node_ids: List[str],
) -> Tuple[RunStatus, int, ResumeLevel, bool, Optional[str]]:
    """Derive (status, nodes_done, resume_level, resumable, recovery_reason).

    Shared by :func:`project_run` and :class:`PlanRunResolver`'s repair-lineage
    consolidation so both compute the exact same recovery semantics from
    whatever (possibly merged) set of refs/dispatched ids they hold.
    """
    terminal = checkpoint_status in _TERMINAL
    manifest = build_manifest(metadata.plan, refs, duration_seconds=0.0)
    nodes_done = manifest.nodes_ok + manifest.nodes_skipped + manifest.nodes_failed

    if terminal:
        if manifest.nodes_failed == 0:
            status: RunStatus = "completed"
        elif manifest.nodes_ok > 0 or manifest.nodes_skipped > 0:
            status = "partial"
        else:
            status = "failed"
    else:
        status = "running"

    resume_level: ResumeLevel = "process" if metadata.artifact_mode == "memory" else "cross_restart"

    has_pending = len(dispatched_node_ids) < len(metadata.plan.nodes)
    run_status_resumable = checkpoint_status in _RESUMABLE_CHECKPOINT_STATUSES or status == "partial"
    recovery_reason: Optional[str] = None
    resumable = False
    if run_status_resumable and has_pending:
        if metadata.artifact_mode == "memory" and metadata.process_id != process_identity():
            recovery_reason = "artifacts_unavailable"
        else:
            resumable = True
    else:
        recovery_reason = "run_not_resumable"

    return status, nodes_done, resume_level, resumable, recovery_reason


def project_run(checkpoint: FlowCheckpoint, *, metadata: PlanRunMetadata) -> PlanRun:
    """Derive typed refs, progress and status; reject lossy or inconsistent state."""
    register_plan_checkpoint_types()
    serializer = FlowStateSerializer()
    terminal = checkpoint.status in _TERMINAL
    refs: List[ArtifactRef] = []
    dispatched: List[str] = []
    for node in metadata.plan.nodes:
        if node.id in checkpoint.context.results:
            value = serializer.from_safe(checkpoint.context.results[node.id])
            if not isinstance(value, ArtifactRef):
                raise PlanRunError("checkpoint_invalid", f"node {node.id!r} result is not a typed ArtifactRef")
            refs.append(value)
            dispatched.append(node.id)
        elif node.id in checkpoint.context.errors:
            refs.append(
                ArtifactRef(
                    node_id=node.id,
                    status="error",
                    errors=[str(checkpoint.context.errors[node.id].get("message", ""))[:300]],
                )
            )
            dispatched.append(node.id)
        elif terminal:
            refs.append(
                ArtifactRef(
                    node_id=node.id,
                    status="error",
                    errors=["node never dispatched: blocked by a failed dependency"],
                )
            )
        # else: pending — running/suspended run, no ref yet.

    status, nodes_done, resume_level, resumable, recovery_reason = _derive_run_state(
        checkpoint_status=checkpoint.status,
        metadata=metadata,
        refs=refs,
        dispatched_node_ids=dispatched,
    )

    return PlanRun(
        metadata=metadata,
        checkpoint_id=checkpoint.checkpoint_id,
        status=status,
        refs=refs,
        nodes_done=nodes_done,
        checkpoint_enabled=True,
        resume_level=resume_level,
        resumable=resumable,
        recovery_reason=recovery_reason,
        dispatched_node_ids=dispatched,
    )


async def select_latest(
    store: Optional[CheckpointStore], durable_store: Optional[CheckpointStore], flow_id: str
) -> Optional[FlowCheckpoint]:
    """Greatest checkpoint_id across configured tiers; equal ids with different state are corruption."""
    candidates = [
        cp for cp in [await s.latest(flow_id) for s in (store, durable_store) if s is not None] if cp is not None
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda cp: cp.checkpoint_id)
    for cp in candidates:
        if cp.checkpoint_id == best.checkpoint_id and cp.model_dump(mode="json") != best.model_dump(mode="json"):
            raise PlanRunError("checkpoint_invalid", f"tiers disagree on {flow_id}@{best.checkpoint_id}")
    return best


def classify_miss(store: Optional[CheckpointStore], durable_store: Optional[CheckpointStore]) -> str:
    """§8 D3: durable tier configured → unknown_run; ephemeral-only → missing_or_expired; none → checkpoint_unavailable."""
    if durable_store is not None:
        return "unknown_run"
    return "missing_or_expired" if store is not None else "checkpoint_unavailable"


class PlanRunResolver:
    """Resolve every agent-facing run operation from the same authority (the checkpoint)."""

    def __init__(
        self,
        *,
        store: Optional[CheckpointStore],
        durable_store: Optional[CheckpointStore],
        scope: Optional[TaskScope],
        cache: Dict[str, PlanRun],
    ) -> None:
        """Bind trusted scope and store handles, never serialized clients."""
        self._store, self._durable, self._scope, self._cache = store, durable_store, scope, cache
        self.logger = logging.getLogger(f"{__name__}.PlanRunResolver")

    def _check_scope(self, run_id: str, metadata: PlanRunMetadata) -> None:
        """Raise ``scope_mismatch`` when a trusted scope is bound and disagrees."""
        if self._scope is not None and metadata.scope_key not in (None, self._scope.cache_key()):
            raise PlanRunError("scope_mismatch", f"run {run_id!r} belongs to another scope")

    async def resolve(self, run_id: str) -> PlanRun:
        """Resolve latest authorized lineage; classify misses by configured tier capability."""
        checkpoint = await select_latest(self._store, self._durable, run_id)
        if checkpoint is None:
            cached = self._cache.get(run_id)
            if cached is not None and not cached.checkpoint_enabled:
                return cached
            raise PlanRunError(
                classify_miss(self._store, self._durable),
                f"run {run_id!r} has no checkpoint in the configured tiers "
                f"(durable={self._durable is not None}, ephemeral={self._store is not None})",
            )

        metadata = read_run_metadata(checkpoint)
        self._check_scope(run_id, metadata)
        run = project_run(checkpoint, metadata=metadata)

        # Follow the repair-lineage chain (spec §2 "Root lookup follows this
        # bounded chain"): each hop's typed refs override the running
        # consolidation for the ids it produced; every other id keeps
        # whatever the previous link resolved. Bounded by the recorded
        # repair_children so a corrupt/cyclic chain fails closed instead of
        # looping forever.
        current_checkpoint = checkpoint
        current_metadata = metadata
        current_refs: Dict[str, ArtifactRef] = {ref.node_id: ref for ref in run.refs}
        current_dispatched: set = set(run.dispatched_node_ids)
        visited = {run_id}
        max_hops = len(metadata.repair_children) + 1
        hops = 0
        consolidated = False

        while current_metadata.active_child_run_id is not None:
            child_id = current_metadata.active_child_run_id
            if child_id in visited:
                raise PlanRunError("checkpoint_invalid", f"run {run_id!r} repair lineage cycles back to {child_id!r}")
            hops += 1
            if hops > max_hops:
                raise PlanRunError(
                    "checkpoint_invalid", f"run {run_id!r} repair lineage exceeds its recorded repair_children bound"
                )
            visited.add(child_id)

            child_checkpoint = await select_latest(self._store, self._durable, child_id)
            if child_checkpoint is None:
                raise PlanRunError(
                    "checkpoint_invalid", f"run {run_id!r} active_child_run_id {child_id!r} has no checkpoint"
                )
            child_metadata = read_run_metadata(child_checkpoint)
            if child_metadata.root_run_id != metadata.root_run_id:
                raise PlanRunError(
                    "checkpoint_invalid", f"child run {child_id!r} does not share root_run_id with {run_id!r}"
                )
            self._check_scope(child_id, child_metadata)
            child_run = project_run(child_checkpoint, metadata=child_metadata)

            # Only the ids the child ACTUALLY dispatched (real results/
            # errors) may override the parent — a terminal child's own
            # blocked-error synthesis for ids it never touched must not
            # clobber a good parent ref (spec §2: "child refs override the
            # parent's for the replaced ids; every other ref comes from the
            # parent").
            child_ids = set(child_run.dispatched_node_ids)
            current_refs.update({ref.node_id: ref for ref in child_run.refs if ref.node_id in child_ids})
            current_dispatched = (current_dispatched - child_ids) | child_ids
            current_checkpoint, current_metadata = child_checkpoint, child_metadata
            consolidated = True

        cached = self._cache.get(run_id)
        if cached is not None and cached.checkpoint_enabled and cached.checkpoint_id == checkpoint.checkpoint_id:
            # A local live cache may add explicitly-marked uncheckpointed
            # progress on top of the checkpointed state — never override
            # what the checkpoint already recorded, and only for the exact
            # revision the cache entry was built against (spec §2).
            extra_ids = [nid for nid in cached.dispatched_node_ids if nid not in current_dispatched]
            if extra_ids:
                extra_refs = {ref.node_id: ref for ref in cached.refs if ref.node_id in extra_ids}
                current_refs.update(extra_refs)
                current_dispatched |= set(extra_ids)
                consolidated = True

        if not consolidated:
            return run

        ordered_refs = [current_refs[node.id] for node in metadata.plan.nodes if node.id in current_refs]
        ordered_dispatched = [node.id for node in metadata.plan.nodes if node.id in current_dispatched]
        status, nodes_done, resume_level, resumable, recovery_reason = _derive_run_state(
            checkpoint_status=current_checkpoint.status,
            metadata=current_metadata,
            refs=ordered_refs,
            dispatched_node_ids=ordered_dispatched,
        )
        return PlanRun(
            metadata=current_metadata,
            checkpoint_id=current_checkpoint.checkpoint_id,
            status=status,
            refs=ordered_refs,
            nodes_done=nodes_done,
            checkpoint_enabled=True,
            resume_level=resume_level,
            resumable=resumable,
            recovery_reason=recovery_reason,
            dispatched_node_ids=ordered_dispatched,
        )

    def envelope(self, run: PlanRun) -> PlanRecoveryEnvelope:
        """Build the response envelope from a resolved run."""
        m = run.metadata
        return PlanRecoveryEnvelope(
            run_id=m.run_id,
            root_run_id=m.root_run_id,
            parent_run_id=m.parent_run_id,
            checkpoint_enabled=run.checkpoint_enabled,
            artifact_mode=m.artifact_mode,
            resume_level=run.resume_level,
            resumable=run.resumable,
            recovery_reason=run.recovery_reason,
            repair_attempts_used=m.repair_attempts_used,
            max_repair_rounds=m.max_repair_rounds,
            active_child_run_id=m.active_child_run_id,
        )
