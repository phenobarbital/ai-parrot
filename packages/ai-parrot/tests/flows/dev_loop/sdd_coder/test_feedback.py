"""Persistent correction feedback and dispatch regression coverage."""

from pathlib import Path
from datetime import datetime, timedelta, timezone
import hashlib
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.flows.dev_loop.sdd_coder.optimization_models import ReviewArtifact
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackStore
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview, CoderReviewMeasurement, CoderReviewStore
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.store import estimate_tokens

from .test_engine_dispatch import fake_builder_factory


def feedback(**overrides: object) -> CoderFeedback:
    """Build a confirmed defect with a reusable regression check."""
    data = dict(
        task_id="TASK-0001",
        attempt_uid="attempt-1",
        backend="nova",
        model="qwen",
        source="code_review",
        pattern="fail-open-authorization",
        files=["pkg/t1.py"],
        defect="Exception handler allowed access when authorization failed.",
        evidence="commit abc123, pkg/t1.py:authorize; failing exception-path test.",
        correction="Reject the operation when authorization cannot be verified.",
        verification="pytest test_auth.py::test_lookup_failure_denies: passed after fix.",
    )
    data.update(overrides)
    return CoderFeedback(**data)


@pytest.fixture
def store(tmp_path: Path) -> CoderFeedbackStore:
    """Use an isolated durable ledger without external services."""
    return CoderFeedbackStore(LedgerLog(str(tmp_path / "events.jsonl")))


async def test_replay_deduplicates_occurrences_and_isolates_models(store: CoderFeedbackStore) -> None:
    """Repeated recording is one occurrence; another attempt is reinforcement."""
    first = feedback()
    receipt = await store.record(first)
    await store.record(first)
    await store.record(feedback(attempt_uid="attempt-2"))
    await store.record(feedback(model="mistral", defect="Mistral-only defect"))
    restarted = CoderFeedbackStore(LedgerLog(store.log.path))
    context = await restarted.context("nova", "qwen", ["pkg/new.py"])
    assert "confirmed deliveries: 2" in context
    assert "Required correction: Reject" in context
    assert "Verification: pytest" in context
    assert "Mistral-only" not in context
    assert receipt.feedback_id == first.feedback_id()
    assert await restarted.context("codex", "qwen", ["pkg/t1.py"]) == ""


async def test_scope_ranking_budget_and_issue_closure(store: CoderFeedbackStore) -> None:
    """Closed work cannot erase a lesson; output never exceeds its estimated budget."""
    await store.record(feedback(pattern="unrelated", files=["other/a.py"]))
    await store.record(feedback(pattern="exact"))
    await store.record(feedback(pattern="component", files=["pkg/t2.py"]))
    store.log.append(LedgerEvent(kind="issue.closed", subject="issue:abc", actor="test", payload={"reason": "fixed"}))
    context = await store.context("nova", "qwen", ["pkg/t1.py"], max_tokens=1800)
    assert context.index("] exact;") < context.index("] component;") < context.index("] unrelated;")
    for budget in (0, 1, 50, 300, 700, 1800):
        assert estimate_tokens(await store.context("nova", "qwen", ["pkg/t1.py"], budget)) <= budget


@pytest.mark.parametrize("files", [["../a.py"], ["/tmp/a.py"], ["pkg/../a.py"], ["pkg//a.py"], ["."]])
def test_feedback_rejects_invalid_scope(files: list[str]) -> None:
    """Scope must be normalized and relative to the repository."""
    with pytest.raises(ValidationError):
        feedback(files=files)


async def test_oversize_is_explicit_and_does_not_append(store: CoderFeedbackStore) -> None:
    """Unicode and JSON escaping can exceed the ledger's byte cap even with short fields."""
    with pytest.raises(ValueError, match="4 KiB"):
        await store.record(feedback(defect="漢" * 600, evidence="漢" * 600, correction="漢" * 600))
    assert list(store.log.iter_events()) == []


async def test_native_handoff_records_then_recalls_verified_correction(
    git_sandbox_feature: tuple, noop_probe: object
) -> None:
    """A new native dispatch gets feedback saved from the previous prepared attempt."""
    worktree, _branch, base_path, index_path = git_sandbox_feature
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    first = await engine.prepare_native("demo", str(worktree), "TASK-0001")
    assert first.coder_feedback == ""
    correction = feedback(attempt_uid=first.attempt_uid, backend="native", model=first.model)
    receipt = await engine.record_feedback("demo", str(worktree), correction)
    index = json.loads(index_path.read_text())
    index["tasks"][0]["status"] = "done"
    index_path.write_text(json.dumps(index))
    await engine.plan("demo", str(worktree))
    second = await engine.prepare_native("demo", str(worktree), "TASK-0002")
    assert first.attempt_uid != second.attempt_uid
    assert receipt.feedback_id in second.coder_feedback
    assert "You previously delivered:" in second.coder_feedback
    with pytest.raises(CoderFailure, match="feedback must match"):
        await engine.record_feedback("demo", str(worktree), correction.model_copy(update={"model": "qwen"}))


async def test_mcp_retry_refreshes_feedback_for_each_model(
    git_sandbox_feature: tuple, noop_probe: object, monkeypatch: pytest.MonkeyPatch, store: CoderFeedbackStore
) -> None:
    """Both dispatch briefs carry their own model's history, refreshed at attempt time."""
    worktree, _branch, base_path, _index = git_sandbox_feature
    await store.record(feedback())
    builder = fake_builder_factory({"nova": "fail"})
    engine = SddCoderEngine(
        roster=RosterConfig(
            seats=[
                RosterSeat(label="q", backend="nova", model="qwen"),
                RosterSeat(label="m", backend="codex", model="mistral"),
            ]
        ),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    monkeypatch.setattr(CoderFeedbackStore, "from_root", lambda root: store)
    original = store.context

    async def retrieve(backend: str, model: str, files: list[str], max_tokens: int, max_age_days: int) -> str:
        """Simulate feedback becoming available between attempts."""
        result = await original(backend, model, files, max_tokens, max_age_days)
        if model == "qwen":
            await store.record(feedback(backend="codex", model="mistral", defect="Mistral previous attribute bug"))
        return result

    monkeypatch.setattr(store, "context", retrieve)
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    result = await engine.wait(job.job_id, 10)
    assert result.tasks[0].outcome == "merged"
    assert len(result.tasks[0].attempts) == 2
    briefs = [call["brief"] for dispatcher in builder.dispatchers.values() for call in dispatcher.calls]
    assert len(briefs) == 2
    assert "Exception handler allowed" in briefs[0].coder_feedback
    assert "Mistral previous attribute bug" in briefs[1].coder_feedback
    assert "Exception handler allowed" not in briefs[1].coder_feedback
    rec = result.tasks[0].attempts[-1]
    receipt = await engine.record_feedback(
        "demo", str(worktree), feedback(backend=rec.backend, model=rec.model, attempt_uid=rec.attempt_uid)
    )
    assert receipt.feedback_id.startswith("coder-feedback:")


async def test_feedback_outage_is_visible_without_breaking_dispatch(
    git_sandbox_feature: tuple, noop_probe: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unavailable ledger is distinguishable from a clean model history."""
    worktree, _branch, base_path, _index = git_sandbox_feature
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    monkeypatch.setattr(CoderFeedbackStore, "context", AsyncMock(side_effect=OSError("ledger unavailable")))
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001")
    assert "Feedback unavailable:" in prep.coder_feedback


@pytest.mark.parametrize("overrides", [{"source": "lint"}, {"lesson_scope": "repo"}])
def test_lint_and_repo_lessons_are_not_model_feedback(overrides: dict) -> None:
    """Only reviewer-confirmed model lessons enter this plane."""
    with pytest.raises(ValidationError):
        feedback(**overrides)


async def test_expired_patterns_do_not_return_until_a_new_occurrence(store: CoderFeedbackStore) -> None:
    """Expiry removes injected context, not durable evidence or future recurrence."""
    await store.record(feedback())
    event, _ = next(store.log.iter_events())
    aged_log = LedgerLog(store.log.path + ".aged")
    aged_log.append(event.model_copy(update={"ts": (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()}))
    aged = CoderFeedbackStore(aged_log)
    assert await aged.context("nova", "qwen", ["pkg/t1.py"]) == ""
    # Re-recording the same delivery must not reset the expiry clock.
    await aged.record(feedback())
    assert await aged.context("nova", "qwen", ["pkg/t1.py"]) == ""
    await aged.record(feedback(attempt_uid="new-occurrence"))
    assert "fail-open-authorization" in await aged.context("nova", "qwen", ["pkg/t1.py"])


async def test_review_metrics_include_clean_deliveries_and_deduplicate_commits(store: CoderFeedbackStore) -> None:
    """One fix in two tasks is 0.5 commits/task; missing cohorts are not zero."""
    reviews = CoderReviewStore(store.log)
    base = dict(
        task_id="TASK-0001",
        attempt_uid="a",
        backend="nova",
        model="qwen",
        fix_commits=["a" * 40, "a" * 40],
        review_evidence="review R1 completed",
        exposure="without_feedback",
        feedback_tokens=0,
    )
    review = CoderReviewMeasurement(**base)
    await reviews.record(review)
    await reviews.record(review)
    await reviews.record(review.model_copy(update={"task_id": "TASK-0002", "attempt_uid": "b", "fix_commits": []}))
    await reviews.record(
        review.model_copy(
            update={
                "task_id": "TASK-0003",
                "attempt_uid": "c",
                "fix_commits": [],
                "exposure": "with_feedback",
                "feedback_tokens": 400,
            }
        )
    )
    report = await CoderReviewStore(LedgerLog(store.log.path)).report()
    before = next(row for row in report.rows if row.exposure == "without_feedback")
    after = next(row for row in report.rows if row.exposure == "with_feedback")
    assert before.reviewed_tasks == before.reviewed_attempts == 2
    assert before.correction_commits_per_task == 0.5
    assert before.task_correction_commits == {"TASK-0001": 1, "TASK-0002": 0}
    assert after.correction_commits_per_task == 0
    assert after.mean_feedback_tokens == 400
    assert len(report.rows) == 2


async def test_review_commit_validation_and_zero_fix_baseline(git_sandbox_feature: tuple, noop_probe: object) -> None:
    """Engine checks git review-fix provenance and records clean baseline deliveries."""
    from .conftest import _run_git
    from .test_engine_dispatch import _git

    worktree, _branch, base_path, _index = git_sandbox_feature
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")], feedback={"enabled": False}),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001")
    review = CoderReview(
        task_id=prep.task_id,
        attempt_uid=prep.attempt_uid,
        backend="native",
        model=prep.model,
        fix_commits=[],
        review_evidence="Review completed, pytest passed",
    )
    await engine.record_review("demo", str(worktree), review)
    report = await engine.feedback_report("demo", str(worktree))
    assert report.rows[0].exposure == "without_feedback"
    assert report.rows[0].correction_commits == 0
    await _run_git("commit", "--allow-empty", "-m", "style(demo): engine lint", cwd=worktree)
    _, sha, _ = await _git("rev-parse", "HEAD", cwd=str(worktree))
    with pytest.raises(CoderFailure, match="review fixes commit"):
        await engine.record_review("demo", str(worktree), review.model_copy(update={"fix_commits": [sha.strip()]}))
    await _run_git("commit", "--allow-empty", "-m", "fix(demo): TASK-0001 review fixes", cwd=worktree)
    _, sha, _ = await _git("rev-parse", "HEAD", cwd=str(worktree))
    await engine.record_review("demo", str(worktree), review.model_copy(update={"fix_commits": [sha.strip()]}))
    report = await engine.feedback_report("demo", str(worktree))
    assert report.rows[0].reviewed_tasks == 1
    assert report.rows[0].correction_commits == 1


async def test_record_review_publishes_review_artifact(git_sandbox_feature: tuple, noop_probe: object) -> None:
    """A review with execution identity publishes a resolvable content-addressed artifact."""
    from .test_engine_dispatch import _git

    worktree, _branch, base_path, _index = git_sandbox_feature
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")], feedback={"enabled": False}),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    execution_id = "550e0000-0000-4000-8000-000000000072"
    await engine.begin_execution("demo", str(worktree), execution_id)
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)
    review = CoderReview(
        task_id=prep.task_id,
        attempt_uid=prep.attempt_uid,
        backend="native",
        model=prep.model,
        fix_commits=[],
        review_evidence="Semantic review completed; task validation passed.",
    )

    receipt = await engine.record_review("demo", str(worktree), review, execution_id)

    assert receipt.review_ref is not None
    assert engine._evidence_store is not None
    artifact_path = engine._evidence_store.root / receipt.review_ref.relative_path
    encoded = artifact_path.read_bytes()
    assert receipt.review_ref.sha256 == hashlib.sha256(encoded).hexdigest()
    assert receipt.review_ref.size_bytes == len(encoded)
    artifact = ReviewArtifact.model_validate_json(encoded)
    _rc, head_sha, _error = await _git("rev-parse", "HEAD", cwd=str(worktree))
    assert artifact.kind == "task_review"
    assert artifact.source == "coder_review"
    assert artifact.task_id == prep.task_id
    assert artifact.execution_id == execution_id
    assert artifact.head_sha == head_sha.strip()
    assert artifact.feature_slug == "demo"


@pytest.mark.parametrize(
    ("index_path", "slug"),
    [
        ("/wt/sdd/tasks/index/FEAT-156.json", "FEAT-156"),
        ("/wt/sdd/tasks/index/lyria-toolkit.json", "lyria-toolkit"),
        ("/wt/sdd/briefs/agy-permission-hook.index.json", "agy-permission-hook"),
    ],
)
def test_index_slug_inverts_resolve_index_path(index_path: str, slug: str) -> None:
    """Per-spec indexes yield their file stem, brief indexes their name minus `.index.json`."""
    from parrot.flows.dev_loop.sdd_coder.engine import _index_slug

    assert _index_slug(index_path) == slug


async def test_record_review_writes_index_file_slug(git_sandbox_feature: tuple, noop_probe: object) -> None:
    """The stored feature_slug is the index file's slug, not its header `feature` (issue:b9ff30bf709e).

    Legacy indexes such as FEAT-213-telegram-voice-reply-tts.json carry a header `feature` without the FEAT
    prefix; finalize_task opens sdd/tasks/index/<feature_slug>.json, so only the file slug can finalize.
    """
    from .conftest import _run_git

    worktree, _branch, base_path, _index = git_sandbox_feature
    await _run_git("mv", "sdd/tasks/index/demo.json", "sdd/tasks/index/FEAT-549-demo.json", cwd=worktree)
    await _run_git("commit", "-m", "rename index to a legacy file name", cwd=worktree)
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")], feedback={"enabled": False}),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    execution_id = "550e0000-0000-4000-8000-000000000075"
    await engine.begin_execution("demo", str(worktree), execution_id)
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)
    review = CoderReview(
        task_id=prep.task_id,
        attempt_uid=prep.attempt_uid,
        backend="native",
        model=prep.model,
        fix_commits=[],
        review_evidence="Semantic review completed; task validation passed.",
    )

    receipt = await engine.record_review("demo", str(worktree), review, execution_id)

    assert receipt.review_ref is not None
    assert engine._evidence_store is not None
    encoded = (engine._evidence_store.root / receipt.review_ref.relative_path).read_bytes()
    assert ReviewArtifact.model_validate_json(encoded).feature_slug == "FEAT-549-demo"


async def test_record_review_without_store_fails_before_ledger_write(
    git_sandbox_feature: tuple, noop_probe: object
) -> None:
    """Execution-scoped review recording fails closed before appending its ledger row."""
    worktree, _branch, base_path, _index = git_sandbox_feature
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")], feedback={"enabled": False}),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    execution_id = "550e0000-0000-4000-8000-000000000073"
    await engine.begin_execution("demo", str(worktree), execution_id)
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)
    review = CoderReview(
        task_id=prep.task_id,
        attempt_uid=prep.attempt_uid,
        backend="native",
        model=prep.model,
        fix_commits=[],
        review_evidence="Semantic review completed.",
    )
    ledger = CoderFeedbackStore.from_root(Path(worktree)).log
    before = list(ledger.iter_events())
    engine._evidence_store = None

    with pytest.raises(CoderFailure) as exc_info:
        await engine.record_review("demo", str(worktree), review, execution_id)

    assert exc_info.value.code == "evidence_persistence_failed"
    assert list(ledger.iter_events()) == before


async def test_record_review_without_execution_id_is_ledger_only(
    git_sandbox_feature: tuple, noop_probe: object
) -> None:
    """Historical callers retain ledger-only behavior without an execution identity."""
    worktree, _branch, base_path, _index = git_sandbox_feature
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")], feedback={"enabled": False}),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001")
    review = CoderReview(
        task_id=prep.task_id,
        attempt_uid=prep.attempt_uid,
        backend="native",
        model=prep.model,
        fix_commits=[],
        review_evidence="Semantic review completed.",
    )

    receipt = await engine.record_review("demo", str(worktree), review)

    assert receipt.feedback_id.startswith("coder-review:")
    assert receipt.review_ref is None


async def test_record_review_invalid_artifact_raises_coder_failure(
    git_sandbox_feature: tuple, noop_probe: object
) -> None:
    """A review that cannot form a ReviewArtifact is a CoderFailure, before any ledger write (issue:f64fd3bb663f)."""
    worktree, _branch, base_path, _index = git_sandbox_feature
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")], feedback={"enabled": False}),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    execution_id = "550e0000-0000-4000-8000-000000000074"
    await engine.begin_execution("demo", str(worktree), execution_id)
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)
    review = CoderReview(
        task_id=prep.task_id,
        attempt_uid=prep.attempt_uid,
        backend="native",
        model=prep.model,
        fix_commits=[],
        review_evidence="Semantic review completed.",
    )
    ledger = CoderFeedbackStore.from_root(Path(worktree)).log
    before = list(ledger.iter_events())

    with pytest.raises(CoderFailure) as exc_info:
        await engine.record_review("demo", str(worktree), review, "not-a-uuid")

    assert exc_info.value.code == "invalid_arguments"
    assert list(ledger.iter_events()) == before


def test_coder_review_accepts_brief_task_ids() -> None:
    """Review measurements accept both formal and brief-local task identifiers."""
    common = {
        "attempt_uid": "attempt-1",
        "backend": "native",
        "model": "codex",
        "fix_commits": [],
        "review_evidence": "Semantic review completed.",
    }

    assert CoderReview(task_id="HOTFIX-review-evidence-producer-1", **common).task_id.startswith("HOTFIX-")
    assert CoderReview(task_id="TASK-12345", **common).task_id == "TASK-12345"


async def test_feedback_tool_validates_source_through_mcp_adapter(
    three_seat_roster: RosterConfig,
) -> None:
    """MCP validation rejects lint sources before reaching the recording engine."""
    from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
    from parrot.mcp.adapter import MCPToolAdapter

    toolkit = SddCoderToolkit(roster=three_seat_roster)
    tool = next(tool for tool in toolkit.get_tools() if tool.name == "coder_record_feedback")
    data = feedback().model_dump()
    data["source"] = "lint"
    result = await MCPToolAdapter(tool).execute({"feature": "demo", "worktree": "/abs", "feedback": data})
    assert result["isError"] is True


def test_real_codex_prompt_contains_injected_feedback(tmp_path: Path) -> None:
    """Ensure the additional brief field reaches a real dispatcher prompt builder."""
    from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher
    from parrot.flows.dev_loop.models import DevelopmentOutput, ResearchOutput, TaskScopedBrief
    from parrot.flows.dev_loop.models.codex import CodexCodeDispatchProfile

    brief = TaskScopedBrief(
        research=ResearchOutput(
            jira_issue_key="",
            spec_path="sdd/specs/demo.spec.md",
            feat_id="FEAT-549",
            branch_name="feature",
            worktree_path=str(tmp_path),
        ),
        task_id="TASK-0001",
        coder_feedback="You previously delivered a confirmed fail-open bug.",
    )
    dispatcher = CodexCodeDispatcher(redis_url="redis://localhost/0", max_concurrent=1, stream_ttl_seconds=60)
    prompt = dispatcher._build_codex_prompt(
        CodexCodeDispatchProfile(subagent="sdd-coder"), brief, DevelopmentOutput, cwd=str(tmp_path)
    )
    assert brief.coder_feedback in prompt


class TestExecutionAttribution:
    """FEAT-559: execution attribution for feedback and review records."""

    async def test_feedback_identity_is_stable_with_execution_attribution(self, store: CoderFeedbackStore) -> None:
        """Adding execution_id preserves feedback_id and review cohort totals."""
        # Record feedback without execution_id (legacy)
        legacy = feedback()
        legacy_receipt = await store.record(legacy)
        legacy_id = legacy.feedback_id()

        # Record same feedback with execution_id
        with_exec = feedback(execution_id="550e8400-e29b-41d4-a716-446655440000")
        with_exec_receipt = await store.record(with_exec)

        # feedback_id must be stable (based on backend/model/task/attempt/pattern, not execution_id)
        assert legacy_receipt.feedback_id == with_exec_receipt.feedback_id
        assert legacy_id == with_exec.feedback_id()

        # Verify context retrieval works for both
        context = await store.context("nova", "qwen", ["pkg/t1.py"])
        assert "fail-open-authorization" in context
        assert "confirmed deliveries: 1" in context

    async def test_legacy_feedback_record_round_trip(self, store: CoderFeedbackStore) -> None:
        """Old feedback records parse without rewriting history."""
        # Create a legacy feedback JSON without execution_id
        legacy_json = json.dumps(
            {
                "task_id": "TASK-0001",
                "attempt_uid": "attempt-1",
                "backend": "nova",
                "model": "qwen",
                "source": "code_review",
                "lesson_scope": "model",
                "pattern": "fail-open-authorization",
                "files": ["pkg/t1.py"],
                "defect": "Exception handler allowed access when authorization failed.",
                "evidence": "commit abc123, pkg/t1.py:authorize; failing exception-path test.",
                "correction": "Reject the operation when authorization cannot be verified.",
                "verification": "pytest test_auth.py::test_lookup_failure_denies: passed after fix.",
            }
        )

        # Parse and verify execution_id defaults to empty
        parsed = CoderFeedback.model_validate_json(legacy_json)
        assert parsed.execution_id == ""
        assert parsed.pattern == "fail-open-authorization"

        # Record and verify it round-trips
        receipt = await store.record(parsed)
        assert receipt.feedback_id.startswith("coder-feedback:")

        # Verify context still works
        context = await store.context("nova", "qwen", ["pkg/t1.py"])
        assert "fail-open-authorization" in context

    async def test_review_with_execution_attribution(self, store: CoderFeedbackStore) -> None:
        """Review records accept execution_id without changing cohort totals."""
        reviews = CoderReviewStore(store.log)

        # Record review without execution_id
        base = dict(
            task_id="TASK-0001",
            attempt_uid="a",
            backend="nova",
            model="qwen",
            fix_commits=["a" * 40],
            review_evidence="review R1 completed",
            exposure="without_feedback",
            feedback_tokens=0,
        )
        legacy_review = CoderReviewMeasurement(**base)
        await reviews.record(legacy_review)

        # Record review with execution_id
        with_exec_review = CoderReviewMeasurement(
            **base
            | {
                "attempt_uid": "b",
                "execution_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        )
        await reviews.record(with_exec_review)

        # Verify report aggregates both correctly
        report = await reviews.report()
        assert len(report.rows) == 1
        row = report.rows[0]
        assert row.reviewed_tasks == 1
        assert row.reviewed_attempts == 2
        assert row.correction_commits == 1

    async def test_legacy_review_record_round_trip(self, store: CoderFeedbackStore) -> None:
        """Old review records parse without rewriting history."""
        reviews = CoderReviewStore(store.log)

        # Create a legacy review JSON without execution_id
        legacy_json = json.dumps(
            {
                "task_id": "TASK-0001",
                "attempt_uid": "attempt-legacy",
                "backend": "nova",
                "model": "qwen",
                "fix_commits": [],
                "review_evidence": "Review completed, pytest passed",
                "exposure": "without_feedback",
                "feedback_tokens": 0,
            }
        )

        # Parse and verify execution_id defaults to empty
        parsed = CoderReviewMeasurement.model_validate_json(legacy_json)
        assert parsed.execution_id == ""
        assert parsed.task_id == "TASK-0001"

        # Record and verify it round-trips
        await reviews.record(parsed)

        # Verify report includes it
        report = await reviews.report()
        assert report.rows[0].reviewed_attempts == 1


async def test_review_and_feedback_coexist(git_sandbox_feature: tuple, noop_probe: object) -> None:
    """A critical reviewed code defect produces both a suspension and a valid code lesson;
    a timeout produces a suspension only -- it is never itself a fabricated code lesson (FEAT-559 TASK-3281)."""
    from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
    from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat

    worktree, _branch, base_path, _index = git_sandbox_feature
    # Two distinct native models so suspending one (timeout) never blocks admitting the other.
    roster = RosterConfig(
        seats=[
            RosterSeat(label="h1", kind="native", model="haiku"),
            RosterSeat(label="h2", kind="native", model="haiku-b"),
        ]
    )
    engine = SddCoderEngine(roster=roster, probe=noop_probe, worktree_base_path=str(base_path))
    execution_id = "550e0000-0000-0000-0000-000000000061"
    await engine.begin_execution("demo", str(worktree), execution_id)

    # --- Timeout: suspension only, no code lesson.
    prep1 = await engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)
    receipt_timeout = await engine.suspend_model(execution_id, prep1.attempt_uid, "timeout", "log:timeout")
    assert receipt_timeout.persisted is True

    # --- A critical reviewed defect on a DIFFERENT (still-eligible) model: suspension AND a code lesson.
    prep2 = await engine.prepare_native("demo", str(worktree), "TASK-0002", execution_id)
    assert prep2.model != prep1.model  # distinct seats -- confirms the timeout above did not block this one
    receipt_critical = await engine.suspend_model(execution_id, prep2.attempt_uid, "review_critical", "commit:abc123")
    assert receipt_critical.persisted is True

    feedback = CoderFeedback(
        task_id="TASK-0002",
        attempt_uid=prep2.attempt_uid,
        backend="native",
        model=prep2.model,
        source="code_review",
        pattern="fail-open-authorization",
        files=["pkg/t2.py"],
        defect="Exception handler allowed access when authorization failed.",
        evidence="commit abc123, pkg/t2.py:authorize; failing exception-path test.",
        correction="Reject the operation when authorization cannot be verified.",
        verification="pytest test_auth.py::test_lookup_failure_denies: passed after fix.",
    )
    fb_receipt = await engine.record_feedback("demo", str(worktree), feedback, execution_id=execution_id)
    assert fb_receipt.feedback_id.startswith("coder-feedback:")

    # Both models are now suspended (one from the timeout report, one from the critical review) --
    # but ONLY the critical-review incident also produced a code lesson.
    pool = engine._executions[execution_id]
    assert all(seat.suspended for seat in pool.view().seats)
    store = CoderFeedbackStore.from_root(Path(worktree))
    context_h2 = await store.context("native", prep2.model, ["pkg/t2.py"])
    assert "fail-open-authorization" in context_h2
    context_h1 = await store.context("native", prep1.model, ["pkg/t1.py"])
    assert context_h1 == ""  # the timeout never fabricated a lesson for the OTHER model


async def test_retracted_feedback_is_dropped_from_replay(store: CoderFeedbackStore) -> None:
    """A misattributed correction can be withdrawn without rewriting the append-only log.

    FEAT-589 recorded four "forgot `git add -f`" defects against a codex model whose
    sandbox cannot commit at all (the engine's extraction was the bug). Retraction
    appends an `insight.superseded` tombstone; replay drops the record, other
    patterns and other models are untouched, and a later re-recording of the same
    occurrence is a fresh confirmation again.
    """
    wrong = feedback(pattern="gitignored-file-not-force-added", files=["artifacts/x.py"], model="gpt-5.6-terra")
    real = feedback(pattern="unverified-fixture-schema-drift", model="gpt-5.6-terra")
    await store.record(wrong)
    await store.record(real)

    assert await store.retract(wrong.feedback_id(), reason="engine extraction bug, not the model", actor="human:t")
    assert not await store.retract("coder-feedback:000000000000000000000000", reason="unknown", actor="human:t")
    assert not await store.retract(wrong.feedback_id(), reason="already gone", actor="human:t")

    restarted = CoderFeedbackStore(LedgerLog(store.log.path))
    context = await restarted.context("nova", "gpt-5.6-terra", ["artifacts/x.py"])
    assert "gitignored-file-not-force-added" not in context
    assert "unverified-fixture-schema-drift" in context
    kinds = [event.kind for event, _offset in restarted.log.iter_events()]
    assert kinds.count("insight.recorded") == 2 and kinds.count("insight.superseded") == 1

    await restarted.record(wrong)
    context = await restarted.context("nova", "gpt-5.6-terra", ["artifacts/x.py"])
    assert "gitignored-file-not-force-added" in context and "confirmed deliveries: 1" in context


@pytest.mark.parametrize("as_model", [True, False])
async def test_record_review_and_feedback_accept_model_or_mapping(
    three_seat_roster: RosterConfig, monkeypatch: pytest.MonkeyPatch, as_model: bool
) -> None:
    """Regression: the MCP layer passes validated models; ``Model(**instance)`` used to raise TypeError."""
    from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
    from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview

    toolkit = SddCoderToolkit(roster=three_seat_roster)
    seen: dict[str, object] = {}

    async def fake_record_review(feature, worktree, review, execution_id=None):
        seen["review"] = review
        return {"ok": True}

    async def fake_record_feedback(feature, worktree, item, execution_id=None):
        seen["feedback"] = item
        return {"ok": True}

    monkeypatch.setattr(toolkit._engine, "record_review", fake_record_review)
    monkeypatch.setattr(toolkit._engine, "record_feedback", fake_record_feedback)

    review = CoderReview(
        task_id="TASK-0001",
        attempt_uid="attempt-1",
        backend="nova",
        model="qwen",
        fix_commits=[],
        review_evidence="orchestrator diff review, no fixes",
    )
    fb = feedback()
    review_arg = review if as_model else review.model_dump()
    feedback_arg = fb if as_model else fb.model_dump()
    # _run wraps the engine result; only the argument coercion is under test, so call the coroutine bodies directly.
    await toolkit.coder_record_review("demo", "/abs", review_arg, "3f2b8c1e-5d4a-4e7b-9a6c-1d2e3f4a5b6c")
    await toolkit.coder_record_feedback("demo", "/abs", feedback_arg, "3f2b8c1e-5d4a-4e7b-9a6c-1d2e3f4a5b6c")
    assert isinstance(seen["review"], CoderReview) and seen["review"].task_id == "TASK-0001"
    assert isinstance(seen["feedback"], CoderFeedback) and seen["feedback"].pattern == "fail-open-authorization"


async def test_record_tools_store_a_valid_payload_through_mcp_adapter(
    git_sandbox_feature: tuple, noop_probe: object
) -> None:
    """A valid review/feedback sent over MCP is recorded, not rejected by its own schema.

    The advertised arg schema validates the nested payload into a model before the
    toolkit method runs, so the method receives ``CoderReview``/``CoderFeedback``
    instances rather than the raw dict a direct caller passes.
    """
    from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
    from parrot.mcp.adapter import MCPToolAdapter

    worktree, _branch, base_path, _index = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native")], feedback={"enabled": False})
    toolkit = SddCoderToolkit(roster=roster, worktree_base_path=str(base_path))
    toolkit._engine = SddCoderEngine(roster=roster, probe=noop_probe, worktree_base_path=str(base_path))
    execution_id = "550e0000-0000-4000-8000-000000000071"
    await toolkit._engine.begin_execution("demo", str(worktree), execution_id)
    prep = await toolkit._engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)
    tools = {tool.name: tool for tool in toolkit.get_tools()}
    scope = {"feature": "demo", "worktree": str(worktree), "execution_id": execution_id}

    review = {
        "task_id": prep.task_id,
        "attempt_uid": prep.attempt_uid,
        "backend": "native",
        "model": prep.model,
        "fix_commits": [],
        "review_evidence": "Orchestrator read the diff; task tests passed.",
    }
    result = await MCPToolAdapter(tools["coder_record_review"]).execute({**scope, "review": review})
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "ok", payload
    assert payload["data"]["feedback_id"].startswith("coder-review:")
    assert payload["data"]["review_ref"]["artifact_id"]

    lesson = feedback(
        task_id=prep.task_id, attempt_uid=prep.attempt_uid, backend="native", model=prep.model
    ).model_dump(mode="json")
    result = await MCPToolAdapter(tools["coder_record_feedback"]).execute({**scope, "feedback": lesson})
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "ok", payload

    report = await toolkit._engine.feedback_report("demo", str(worktree))
    assert report.rows[0].reviewed_tasks == 1
