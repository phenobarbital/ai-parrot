"""Behavioral acceptance tests for coder checked-pattern evidence and review plumbing."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.flows.dev_loop.models import DevelopmentOutput
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackStore
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview, CoderReviewMeasurement
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.memory.dynamics.models import CheckedPattern, MemoryRef
from parrot.memory.episodic.models import MemoryNamespace

_EXECUTION_ID = "550e0000-0000-4000-8000-000000000076"
_ATTEMPT_UID = "attempt-verified"
_CHECK_ID = "validation-artifact"


def _claim(*, exposure_id: str = _ATTEMPT_UID, check_id: str = _CHECK_ID) -> CheckedPattern:
    """Build one delivery claim bound to the test execution."""
    namespace = MemoryNamespace(
        tenant_id="tenant-a",
        agent_id="agent-a",
        model_id="haiku",
    )
    return CheckedPattern(
        pattern="preserve-coder-evidence",
        ref=MemoryRef(namespace=namespace, kind="episode", memory_id="memory-a", content_version="v1"),
        exposure_id=exposure_id,
        evidence_refs=(check_id,),
    )


def _review(*, claim: CheckedPattern) -> CoderReview:
    """Build a zero-fix review carrying a checked-pattern claim."""
    return CoderReview(
        task_id="TASK-0001",
        attempt_uid=_ATTEMPT_UID,
        backend="native",
        model="haiku",
        fix_commits=[],
        review_evidence="The isolated engine validation passed.",
        checked_patterns=[claim],
    )


def test_empty_checked_patterns_backward_compatible() -> None:
    """Verify omitted checked-pattern claims preserve prior development output parsing."""
    output = DevelopmentOutput(files_changed=["pkg/example.py"], commit_shas=[], summary="Completed safely.")

    assert output.checked_patterns == []
    assert output.model_dump()["checked_patterns"] == []


@pytest.mark.asyncio
async def test_forged_or_wrong_attempt_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject a claim whose exposure does not match the engine-issued attempt."""
    engine, worktree, _store = _engine_with_review_context(tmp_path, monkeypatch)
    engine._review_checks[_ATTEMPT_UID] = (_EXECUTION_ID, (_CHECK_ID,))

    with pytest.raises(CoderFailure, match="exposure must match"):
        await engine.record_review(
            "demo",
            str(worktree),
            _review(claim=_claim(exposure_id="forged-attempt")),
            _EXECUTION_ID,
        )


@pytest.mark.asyncio
async def test_verified_zero_fix_success_keeps_review_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist engine-owned checks and a durable review reference without a fix commit."""
    engine, worktree, store = _engine_with_review_context(tmp_path, monkeypatch)
    engine._review_checks[_ATTEMPT_UID] = (_EXECUTION_ID, (_CHECK_ID,))

    receipt = await engine.record_review("demo", str(worktree), _review(claim=_claim()), _EXECUTION_ID)

    assert receipt.review_ref is not None
    artifact_path = engine._evidence_store.root / receipt.review_ref.relative_path  # type: ignore[union-attr]
    assert artifact_path.is_file()
    event, _offset = next(store.log.iter_events())
    measurement = CoderReviewMeasurement.model_validate_json(event.payload["fact"])
    assert measurement.fix_commits == []
    assert measurement.passed_check_ids == (_CHECK_ID,)
    assert measurement.review_ref == f"coder-review/v1/{_EXECUTION_ID}/TASK-0001/{_ATTEMPT_UID}"


@pytest.mark.asyncio
async def test_many_validation_evidence_ids_are_bounded_and_cited_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verdict with more than 16 evidence ids records only the cited ids and never fails after the artifact write."""
    engine, worktree, store = _engine_with_review_context(tmp_path, monkeypatch)
    many = tuple(f"check-{index}" for index in range(40)) + (_CHECK_ID,)
    engine._review_checks[_ATTEMPT_UID] = (_EXECUTION_ID, many)

    receipt = await engine.record_review("demo", str(worktree), _review(claim=_claim()), _EXECUTION_ID)

    assert receipt.review_ref is not None
    event, _offset = next(store.log.iter_events())
    measurement = CoderReviewMeasurement.model_validate_json(event.payload["fact"])
    assert measurement.passed_check_ids == (_CHECK_ID,)


@pytest.mark.asyncio
async def test_claim_without_a_passed_check_or_receipt_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A claim citing no engine-owned passed check, another execution, or an attempt without a receipt fails closed."""
    engine, worktree, _store = _engine_with_review_context(tmp_path, monkeypatch)

    with pytest.raises(CoderFailure, match="validation receipt"):
        await engine.record_review("demo", str(worktree), _review(claim=_claim()), _EXECUTION_ID)

    engine._review_checks[_ATTEMPT_UID] = (_EXECUTION_ID, (_CHECK_ID,))
    with pytest.raises(CoderFailure, match="engine-owned passed check"):
        await engine.record_review("demo", str(worktree), _review(claim=_claim(check_id="unrelated")), _EXECUTION_ID)

    engine._review_checks[_ATTEMPT_UID] = ("another-execution", (_CHECK_ID,))
    with pytest.raises(CoderFailure, match="calling execution"):
        await engine.record_review("demo", str(worktree), _review(claim=_claim()), _EXECUTION_ID)


def _engine_with_review_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SddCoderEngine, Path, CoderFeedbackStore]:
    """Create an isolated engine with one engine-issued review identity."""
    worktree = tmp_path / "feature"
    worktree.mkdir()
    evidence_root = tmp_path / "evidence"
    store = CoderFeedbackStore(LedgerLog(str(tmp_path / "reviews.jsonl")))
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="native", kind="native")], feedback={"enabled": False}),
        worktree_base_path=str(tmp_path / "worktrees"),
        telemetry_dir=str(evidence_root),
    )
    engine._feedback_sources[_ATTEMPT_UID] = (str(worktree.resolve()), "TASK-0001", "native", "haiku")

    async def resolve_feature(*_args: object) -> SimpleNamespace:
        """Return the feature identity already bound to the isolated attempt."""
        return SimpleNamespace(worktree=str(worktree.resolve()), index_path="sdd/tasks/index/demo.json")

    async def git(*_args: str, **_kwargs: object) -> tuple[int, str, str]:
        """Provide the feature head used only for the durable review artifact."""
        return 0, "a" * 40, ""

    engine_module = importlib.import_module("parrot.flows.dev_loop.sdd_coder.engine")
    monkeypatch.setattr(engine, "_resolve_feature", resolve_feature)
    monkeypatch.setattr(engine_module, "_git", git)
    monkeypatch.setattr(CoderFeedbackStore, "from_root", lambda _root: store)
    return engine, worktree, store
