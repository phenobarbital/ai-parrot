"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import List, Optional

import pytest

from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import CompactionReceipt, EvidenceRef, ReviewCheckpoint
from parrot.flows.dev_loop.sdd_coder.phase_boundary import (
    PhaseBoundaryStaleHandoffError,
    prepare_review_boundary,
)

_EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
_FULL_SHA_A = "a" * 40
_FULL_SHA_B = "b" * 40


def _evidence_ref(artifact_id: str = "artifact-1", content: bytes = b"{}") -> EvidenceRef:
    """Build a valid EvidenceRef whose sha256 actually matches `content`."""
    digest = hashlib.sha256(content).hexdigest()
    return EvidenceRef(
        artifact_id=artifact_id,
        sha256=digest,
        relative_path=f"artifacts/{digest}.json",
        size_bytes=len(content),
        media_type="application/json",
    )


def _build_checkpoint(*, context_id: Optional[str], **overrides: object) -> ReviewCheckpoint:
    """Every ReviewCheckpoint field except `checkpoint_id`, with a correctly-computed digest.

    `context_id` is not yet set by any real producer (`checkpoint.py`'s own
    `prepare_review_checkpoint` never fills it) -- it stands in here for a
    future M0-homologated producer.
    """
    fields: dict[str, object] = dict(
        schema_version=1,
        feature="sdd-execution-optimization",
        execution_id=_EXECUTION_ID,
        worktree="/tmp/worktree",
        branch="feat-FEAT-584-sdd-execution-optimization",
        base_sha=_FULL_SHA_A,
        implementation_head=_FULL_SHA_B,
        spec_hash="c" * 64,
        index_hash="d" * 64,
        convention_hashes={"CLAUDE.md": "e" * 64},
        task_refs=[_evidence_ref("task-ref")],
        criteria_refs=[_evidence_ref("criteria-ref")],
        commits=[_FULL_SHA_A],
        validation_refs=[_evidence_ref("validation-ref")],
        evidence_refs=[_evidence_ref("evidence-ref")],
        user_constraints=["never touch clients/base.py"],
        pending_actions=["awaiting semantic review"],
        settlement_ref=_evidence_ref("settlement"),
        neutral_brief="Implement TASK-3568 phase boundary.",
        context_id=context_id,
    )
    fields.update(overrides)
    checkpoint_id = ReviewCheckpoint.compute_checkpoint_id(**fields)
    return ReviewCheckpoint(checkpoint_id=checkpoint_id, **fields)


class _RecordingDriver:
    """Fake `PhaseBoundaryDriver`: records every call, returns a configured outcome."""

    def __init__(
        self,
        *,
        supports: bool = True,
        receipt: Optional[CompactionReceipt] = None,
        raises: Optional[BaseException] = None,
    ) -> None:
        self.supports_calls: List[str] = []
        self.compact_calls: List[ReviewCheckpoint] = []
        self._supports = supports
        self._receipt = receipt
        self._raises = raises

    async def supports(self, context_id: str) -> bool:
        self.supports_calls.append(context_id)
        return self._supports

    async def compact(self, checkpoint: ReviewCheckpoint) -> CompactionReceipt:
        self.compact_calls.append(checkpoint)
        if self._raises is not None:
            raise self._raises
        assert self._receipt is not None, "test driver misconfigured: no receipt and no exception"
        return self._receipt


def test_once_per_checkpoint_and_context(tmp_path: Path) -> None:
    """Concurrent/replayed requests invoke a supported driver at most once."""
    store = ExecutionEvidenceStore(tmp_path / "durable")
    checkpoint = _build_checkpoint(context_id="claude-main")
    final_receipt = CompactionReceipt(
        checkpoint_id=checkpoint.checkpoint_id,
        context_id="claude-main",
        status="completed",
        reason="jev reduced context",
        backend="jev",
        before_bytes=1000,
        after_bytes=400,
        elapsed_ms=42,
    )
    driver = _RecordingDriver(supports=True, receipt=final_receipt)

    first = asyncio.run(prepare_review_boundary(checkpoint, driver=driver, policy="auto", store=store))
    assert first == final_receipt
    assert len(driver.compact_calls) == 1
    assert len(driver.supports_calls) == 1

    # Replay: the exact same checkpoint+context must NOT invoke the driver
    # again -- the durably persisted receipt is returned as-is.
    second = asyncio.run(prepare_review_boundary(checkpoint, driver=driver, policy="auto", store=store))
    assert second == final_receipt
    assert len(driver.compact_calls) == 1
    assert len(driver.supports_calls) == 1

    # Genuine concurrency for a DIFFERENT key: two in-flight requests for
    # the same checkpoint+context still invoke the driver at most once.
    checkpoint2 = _build_checkpoint(context_id="claude-main-2")
    final_receipt2 = CompactionReceipt(
        checkpoint_id=checkpoint2.checkpoint_id,
        context_id="claude-main-2",
        status="completed",
        reason="jev reduced context",
        backend="jev",
        elapsed_ms=5,
    )
    driver2 = _RecordingDriver(supports=True, receipt=final_receipt2)

    async def _concurrent() -> list[CompactionReceipt]:
        return await asyncio.gather(
            prepare_review_boundary(checkpoint2, driver=driver2, policy="auto", store=store),
            prepare_review_boundary(checkpoint2, driver=driver2, policy="auto", store=store),
        )

    results = asyncio.run(_concurrent())
    assert len(driver2.compact_calls) == 1
    for result in results:
        # The "loser" may observe either the in-flight `in_progress`
        # placeholder or the fully settled receipt, depending on
        # scheduling -- but never a fabricated success it did not itself
        # request from the driver.
        assert result.status in ("in_progress", "completed")
        if result.status == "completed":
            assert result == final_receipt2


def test_unsupported_off_and_fallback(tmp_path: Path) -> None:
    """Unsupported/off/skipped/failed/backend-unknown are explicit and never fake Jev success."""
    store = ExecutionEvidenceStore(tmp_path / "durable")

    # policy='off' never even asks the driver whether it supports the context.
    off_checkpoint = _build_checkpoint(context_id="claude-main")
    off_driver = _RecordingDriver(supports=True, receipt=None)
    off_receipt = asyncio.run(prepare_review_boundary(off_checkpoint, driver=off_driver, policy="off", store=store))
    assert off_receipt.status == "skipped"
    assert off_receipt.backend == "unknown"
    assert not off_driver.supports_calls
    assert not off_driver.compact_calls

    # An explicitly unsupported context never fakes a completed compaction.
    unsupported_checkpoint = _build_checkpoint(context_id="codex-subagent")
    unsupported_driver = _RecordingDriver(supports=False, receipt=None)
    unsupported_receipt = asyncio.run(
        prepare_review_boundary(unsupported_checkpoint, driver=unsupported_driver, policy="auto", store=store)
    )
    assert unsupported_receipt.status == "unsupported"
    assert unsupported_receipt.backend == "unknown"
    assert len(unsupported_driver.supports_calls) == 1
    assert not unsupported_driver.compact_calls

    # A driver-reported clean failure (e.g. Jev errored, builtin fallback
    # also failed) is recorded verbatim -- never upgraded to "completed".
    failed_checkpoint = _build_checkpoint(context_id="claude-main-failed")
    failed_receipt_from_driver = CompactionReceipt(
        checkpoint_id=failed_checkpoint.checkpoint_id,
        context_id="claude-main-failed",
        status="failed",
        reason="jev reduction below threshold and builtin fallback also failed",
        backend="builtin",
        elapsed_ms=17,
    )
    failed_driver = _RecordingDriver(supports=True, receipt=failed_receipt_from_driver)
    failed_receipt = asyncio.run(
        prepare_review_boundary(failed_checkpoint, driver=failed_driver, policy="auto", store=store)
    )
    assert failed_receipt.status == "failed"
    assert failed_receipt.backend == "builtin"
    assert failed_receipt == failed_receipt_from_driver

    # An unsupported outcome is durably recorded: replaying the same
    # checkpoint+context never re-asks a driver that would now say yes.
    supports_now_driver = _RecordingDriver(supports=True, receipt=None)
    replay_receipt = asyncio.run(
        prepare_review_boundary(unsupported_checkpoint, driver=supports_now_driver, policy="auto", store=store)
    )
    assert replay_receipt.status == "unsupported"
    assert not supports_now_driver.supports_calls
    assert not supports_now_driver.compact_calls


def test_crash_timeout_and_stale_resume(tmp_path: Path) -> None:
    """Unknown in-progress state is reconciled without retry and stale handoff blocks continuation."""
    store = ExecutionEvidenceStore(tmp_path / "durable")

    # A driver crash mid-`compact()` leaves the durable record `in_progress`
    # (already persisted before the call) -- the NEXT attempt must not
    # retry the driver at all, it just returns the unresolved state.
    crash_checkpoint = _build_checkpoint(context_id="claude-main-crash")
    crashing_driver = _RecordingDriver(supports=True, raises=RuntimeError("runtime vanished mid-call"))
    with pytest.raises(RuntimeError, match="runtime vanished mid-call"):
        asyncio.run(prepare_review_boundary(crash_checkpoint, driver=crashing_driver, policy="auto", store=store))
    assert len(crashing_driver.compact_calls) == 1

    reconciling_driver = _RecordingDriver(supports=True, receipt=None)
    reconciled = asyncio.run(
        prepare_review_boundary(crash_checkpoint, driver=reconciling_driver, policy="auto", store=store)
    )
    assert reconciled.status == "in_progress"
    # Reconciliation never blindly retries: a fresh driver instance is
    # given for this call and it is never invoked.
    assert not reconciling_driver.supports_calls
    assert not reconciling_driver.compact_calls

    # A driver that answers with a receipt scoped to a DIFFERENT
    # checkpoint/context (a stale handoff) is rejected outright, blocking
    # continuation instead of reviewing over the wrong evidence.
    stale_checkpoint = _build_checkpoint(context_id="claude-main-stale")
    mismatched_receipt = CompactionReceipt(
        checkpoint_id="0" * 64,
        context_id="some-other-context",
        status="completed",
        reason="looks fine from the wrong context",
        backend="jev",
        elapsed_ms=3,
    )
    stale_driver = _RecordingDriver(supports=True, receipt=mismatched_receipt)
    with pytest.raises(PhaseBoundaryStaleHandoffError):
        asyncio.run(prepare_review_boundary(stale_checkpoint, driver=stale_driver, policy="auto", store=store))

    # The stale handoff is itself durably recorded as `failed` -- a replay
    # never re-invokes the driver, and never resurfaces as `completed`.
    another_driver = _RecordingDriver(supports=True, receipt=None)
    replay = asyncio.run(prepare_review_boundary(stale_checkpoint, driver=another_driver, policy="auto", store=store))
    assert replay.status == "failed"
    assert not another_driver.supports_calls
    assert not another_driver.compact_calls
