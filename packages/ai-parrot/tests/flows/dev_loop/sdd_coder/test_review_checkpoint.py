"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder.checkpoint import (
    CheckpointBusyError,
    CheckpointStaleError,
    prepare_review_checkpoint,
    validate_review_checkpoint,
)
from parrot.flows.dev_loop.sdd_coder.evidence import EvidenceCorruptionError, ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundRegistration, ReviewArtifact
from parrot.flows.dev_loop.sdd_coder.models import ExecutionSnapshot
from parrot.flows.dev_loop.sdd_coder.background import BackgroundRegistry
from parrot.sdd.scripts.review_checkpoint import main

EXECUTION_ID = "33333333-3333-4333-8333-333333333333"
FEATURE_SLUG = "checkpoint-demo"
FEATURE_ID = "FEAT-9101"
BASE_BRANCH = "dev"
FEATURE_BRANCH = "feat-branch"

_CONVENTION_FILES = (
    ".claude/rules/codebase-conventions.md",
    ".agent/rules/codebase-conventions.md",
    "packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md",
)


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _build_repo(tmp_path: Path) -> Path:
    """A real, tiny git repo standing in for a feature worktree.

    Layout: per-spec index + spec + three convention files + one 'done' task
    (with an Acceptance Criteria section) + one 'pending' task, all in ONE
    commit; a same-tip `origin/<base_branch>` ref stands in for the remote
    the worktree was forked from (a locally-named branch resolves through
    `git rev-parse origin/dev` exactly like a real remote-tracking ref).
    """
    worktree = tmp_path / "feature"
    worktree.mkdir()
    _run_git(["init", "-q", "-b", FEATURE_BRANCH], cwd=worktree)
    _run_git(["config", "user.email", "t@example.com"], cwd=worktree)
    _run_git(["config", "user.name", "Test"], cwd=worktree)
    _run_git(["config", "commit.gpgsign", "false"], cwd=worktree)

    (worktree / "sdd" / "specs").mkdir(parents=True)
    (worktree / "sdd" / "specs" / f"{FEATURE_SLUG}.spec.md").write_text("# Spec\n\nDemo spec body.\n", encoding="utf-8")

    for rel_path in _CONVENTION_FILES:
        path = worktree / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Conventions for {rel_path}\n", encoding="utf-8")

    active_dir = worktree / "sdd" / "tasks" / "active"
    completed_dir = worktree / "sdd" / "tasks" / "completed"
    active_dir.mkdir(parents=True)
    completed_dir.mkdir(parents=True)
    (completed_dir / "TASK-1-base.md").write_text(
        "# TASK-1: Base\n\n## Acceptance Criteria\n\n- [x] Base criterion satisfied.\n", encoding="utf-8"
    )
    (active_dir / "TASK-2-thing.md").write_text(
        "# TASK-2: Thing\n\n## Acceptance Criteria\n\n- [ ] Thing criterion pending.\n", encoding="utf-8"
    )

    index_dir = worktree / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    index = {
        "feature": FEATURE_SLUG,
        "feature_id": FEATURE_ID,
        "spec": f"sdd/specs/{FEATURE_SLUG}.spec.md",
        "type": "feature",
        "base_branch": BASE_BRANCH,
        "tasks": [
            {
                "id": "TASK-1",
                "title": "Base",
                "status": "done",
                "depends_on": [],
                "file": "sdd/tasks/completed/TASK-1-base.md",
            },
            {
                "id": "TASK-2",
                "title": "Thing",
                "status": "pending",
                "depends_on": ["TASK-1"],
                "file": "sdd/tasks/active/TASK-2-thing.md",
            },
        ],
    }
    (index_dir / f"{FEATURE_SLUG}.json").write_text(json.dumps(index), encoding="utf-8")

    _run_git(["add", "-A"], cwd=worktree)
    _run_git(["commit", "-q", "-m", "seed"], cwd=worktree)
    base_sha = _run_git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    _run_git(["branch", f"origin/{BASE_BRANCH}", base_sha], cwd=worktree)
    return worktree


def _publish_closed_settlement(
    store: ExecutionEvidenceStore, *, worktree: Path, generation: int = 1
) -> ExecutionSnapshot:
    """Stand in for `SddCoderEngine.end_execution`'s own durable publish (TASK-3565)."""
    snapshot = ExecutionSnapshot(
        execution_id=EXECUTION_ID,
        feature_id=FEATURE_ID,
        worktree_path=str(worktree.resolve()),
        roster_fingerprint="fp-1",
        admitted_attempts={},
        native_reservations={},
        outstanding_job_ids=[],
        local_exclusions=[],
        inherited_exclusions=[],
        status="closed",
        generation=generation,
    )
    asyncio.run(store.put_artifact(EXECUTION_ID, snapshot))
    return snapshot


def test_settlement_and_unknown_gate(tmp_path: Path) -> None:
    """Unknown validation or unclosed execution prevents publication."""
    worktree = _build_repo(tmp_path)
    store = ExecutionEvidenceStore(tmp_path / "durable")

    # No settlement was ever published -- a separate CLI process has no
    # in-memory pool to consult, so this is indistinguishable from busy.
    with pytest.raises(CheckpointBusyError):
        asyncio.run(
            prepare_review_checkpoint(feature=FEATURE_SLUG, worktree=worktree, execution_id=EXECUTION_ID, store=store)
        )

    _publish_closed_settlement(store, worktree=worktree)

    # A closed settlement exists, but an admitted validation is still
    # `pending` (never transitioned) -- checkpoint stays busy.
    registry = BackgroundRegistry(store=store, owner_instance_id="owner-A")
    registration = BackgroundRegistration(
        handle="validation-1",
        execution_id=EXECUTION_ID,
        task_id="TASK-2",
        launch_id="launch-1",
        owner_instance_id="owner-A",
        kind="validation",
        authority="supervisor",
        worktree=str(worktree.resolve()),
        backend="pytest",
    )
    handle = asyncio.run(registry.register(registration))
    with pytest.raises(CheckpointBusyError):
        asyncio.run(
            prepare_review_checkpoint(feature=FEATURE_SLUG, worktree=worktree, execution_id=EXECUTION_ID, store=store)
        )

    # Settling the validation (a durable terminal receipt) lifts the gate.
    log_dir = store.root / "executions" / EXECUTION_ID / "background_logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "validation.log"
    log_path.write_text("all green\n", encoding="utf-8")
    asyncio.run(
        registry._record_transition(
            EXECUTION_ID, handle, state="finished", outcome="completed", exit_code=0, log_path=log_path
        )
    )

    checkpoint = asyncio.run(
        prepare_review_checkpoint(feature=FEATURE_SLUG, worktree=worktree, execution_id=EXECUTION_ID, store=store)
    )
    assert checkpoint.execution_id == EXECUTION_ID
    assert len(checkpoint.validation_refs) == 1


def test_stale_head_spec_index_and_conventions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each covered revision change invalidates the handoff before review."""
    worktree = _build_repo(tmp_path)
    store = ExecutionEvidenceStore(tmp_path / "durable")
    # `validate_review_checkpoint` takes no store/root of its own -- it reads
    # the SAME env-var override `scripts.sdd.finalize_task`/`review_checkpoint`
    # use, so it resolves the durable root this test actually published to.
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(store.root))
    _publish_closed_settlement(store, worktree=worktree)

    checkpoint = asyncio.run(
        prepare_review_checkpoint(feature=FEATURE_SLUG, worktree=worktree, execution_id=EXECUTION_ID, store=store)
    )
    # A fresh baseline validates cleanly.
    asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))

    spec_path = worktree / "sdd" / "specs" / f"{FEATURE_SLUG}.spec.md"
    original_spec = spec_path.read_text(encoding="utf-8")
    spec_path.write_text(original_spec + "\nmutated\n", encoding="utf-8")
    with pytest.raises(CheckpointStaleError):
        asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))
    spec_path.write_text(original_spec, encoding="utf-8")
    asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))

    convention_path = worktree / _CONVENTION_FILES[0]
    original_convention = convention_path.read_text(encoding="utf-8")
    convention_path.write_text(original_convention + "\nmutated\n", encoding="utf-8")
    with pytest.raises(CheckpointStaleError):
        asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))
    convention_path.write_text(original_convention, encoding="utf-8")
    asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))

    index_path = worktree / "sdd" / "tasks" / "index" / f"{FEATURE_SLUG}.json"
    original_index = index_path.read_text(encoding="utf-8")
    mutated_index = json.loads(original_index)
    mutated_index["tasks"][1]["status"] = "done"
    index_path.write_text(json.dumps(mutated_index), encoding="utf-8")
    with pytest.raises(CheckpointStaleError):
        asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))
    index_path.write_text(original_index, encoding="utf-8")
    asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))

    # A new commit moves HEAD away from the checkpoint's implementation_head.
    (worktree / "sdd" / "specs" / "extra.md").write_text("extra\n", encoding="utf-8")
    _run_git(["add", "-A"], cwd=worktree)
    _run_git(["commit", "-q", "-m", "moved on"], cwd=worktree)
    with pytest.raises(CheckpointStaleError):
        asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))


def test_durable_neutral_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new reader with no development conversation recovers criteria, diff and constraints."""
    worktree = _build_repo(tmp_path)
    store = ExecutionEvidenceStore(tmp_path / "durable")
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(store.root))
    _publish_closed_settlement(store, worktree=worktree)

    checkpoint = asyncio.run(
        prepare_review_checkpoint(feature=FEATURE_SLUG, worktree=worktree, execution_id=EXECUTION_ID, store=store)
    )

    # A completely fresh reader loads ONLY the durable, content-addressed
    # evidence -- no conversation, no in-memory engine state.
    fresh_store = ExecutionEvidenceStore(store.root)
    criteria_page = asyncio.run(fresh_store.read_artifact(EXECUTION_ID, checkpoint.criteria_refs[0].artifact_id))
    assert "criterion" in criteria_page["content"]

    task_page = asyncio.run(fresh_store.read_artifact(EXECUTION_ID, checkpoint.task_refs[0].artifact_id))
    assert "Acceptance Criteria" in task_page["content"]

    # Pending work (TASK-2, still 'pending' in the index) survives into both
    # the structured field and the bounded neutral brief -- never silently
    # dropped, never editorialized.
    assert any("TASK-2" in item for item in checkpoint.pending_actions)
    assert "TASK-2" in checkpoint.neutral_brief
    assert len(checkpoint.neutral_brief.encode("utf-8")) <= 8192

    # The immutable diff is recoverable from durable refs alone.
    assert checkpoint.base_sha
    assert checkpoint.implementation_head
    assert checkpoint.branch == FEATURE_BRANCH

    # Re-validating the SAME checkpoint from a brand-new process-local object
    # (nothing carried over except the durable files) still succeeds.
    asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))


def test_record_publishes_manual_review_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The manual CLI stores a typed review artifact at the durable root."""
    worktree = _build_repo(tmp_path)
    durable_root = tmp_path / "durable"
    execution_id = "44444444-4444-4444-8444-444444444444"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))
    head_sha = _run_git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()

    exit_code = main(
        [
            "record",
            "--feature",
            FEATURE_SLUG,
            "--task",
            "TASK-2",
            "--worktree",
            str(worktree),
            "--summary",
            "Manual semantic review passed.",
            "--execution-id",
            execution_id,
            "--fix-commit",
            head_sha,
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["ok"] is True
    assert result["execution_id"] == execution_id
    assert result["execution_id_generated"] is False
    review_ref = result["review_ref"]
    page = asyncio.run(ExecutionEvidenceStore(durable_root).read_artifact(execution_id, review_ref["artifact_id"]))
    artifact = ReviewArtifact.model_validate_json(page["content"])
    assert artifact.source == "manual"
    assert artifact.head_sha == head_sha
    assert artifact.fix_commits == [head_sha]
    assert artifact.feature_slug == FEATURE_SLUG


def test_record_generates_execution_id_when_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An omitted execution ID becomes a fresh canonical UUID."""
    worktree = _build_repo(tmp_path)
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))

    exit_code = main(
        [
            "record",
            "--feature",
            FEATURE_SLUG,
            "--task",
            "TASK-2",
            "--worktree",
            str(worktree),
            "--summary",
            "Manual semantic review passed.",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["ok"] is True
    assert str(uuid.UUID(result["execution_id"])) == result["execution_id"]
    assert result["execution_id_generated"] is True
    assert (durable_root / "executions" / result["execution_id"] / "artifacts").is_dir()


@pytest.mark.parametrize(
    ("arguments", "error_fragment"),
    [
        (["--task", "invalid-task"], "invalid-task"),
        (["--summary", ""], "String should have at least 1 character"),
        (["--fix-commit", "abc123"], "full 40-hex-char git SHA"),
    ],
)
def test_record_rejects_invalid_input_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    error_fragment: str,
) -> None:
    """Model-invalid manual reviews return input errors before an artifact write."""
    worktree = _build_repo(tmp_path)
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))
    argv = [
        "record",
        "--feature",
        FEATURE_SLUG,
        "--task",
        "TASK-2",
        "--worktree",
        str(worktree),
        "--summary",
        "Manual semantic review passed.",
        "--execution-id",
        EXECUTION_ID,
        *arguments,
    ]

    exit_code = main(argv)

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert result["ok"] is False
    assert result["error"] == "invalid_input"
    assert error_fragment in result["message"]
    assert not (durable_root / "executions" / EXECUTION_ID / "artifacts").exists()


def _record_argv(worktree: Path, *extra: str) -> list[str]:
    """A valid `record` argv for `worktree` with a fixed execution ID, plus any extra arguments."""
    return [
        "record",
        "--feature",
        FEATURE_SLUG,
        "--task",
        "TASK-2",
        "--worktree",
        str(worktree),
        "--summary",
        "Manual semantic review passed.",
        "--execution-id",
        EXECUTION_ID,
        *extra,
    ]


@pytest.mark.parametrize(
    "error",
    [OSError("disk full"), EvidenceCorruptionError("artifact hash mismatch")],
    ids=["os_error", "evidence_corruption"],
)
def test_record_reports_store_errors_as_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    """A failed artifact write is an operation_error JSON result, never a traceback (issue:f64fd3bb663f)."""
    worktree = _build_repo(tmp_path)
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(tmp_path / "durable"))

    async def failing_put_artifact(self: ExecutionEvidenceStore, execution_id: str, payload: object) -> None:
        raise error

    monkeypatch.setattr(ExecutionEvidenceStore, "put_artifact", failing_put_artifact)

    exit_code = main(_record_argv(worktree))

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert result == {"ok": False, "error": "operation_error", "message": str(error)}


@pytest.mark.parametrize("failure", ["not_a_repository", "git_missing"])
def test_record_reports_git_failures_as_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    """A failed or missing git is an operation_error JSON result with exit 1 and nothing stored."""
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))
    if failure == "not_a_repository":
        worktree = tmp_path / "plain"
        worktree.mkdir()
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    else:
        worktree = _build_repo(tmp_path)
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()
        monkeypatch.setenv("PATH", str(empty_bin))

    exit_code = main(_record_argv(worktree))

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert result["ok"] is False
    assert result["error"] == "operation_error"
    assert "git" in result["message"]
    assert not (durable_root / "executions" / EXECUTION_ID / "artifacts").exists()


def test_record_reads_head_without_blocking_subprocess_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`record` reads HEAD through the async run_bounded helper, never a blocking subprocess.run (issue:f64fd3bb663f)."""
    worktree = _build_repo(tmp_path)
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))
    head_sha = _run_git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()

    def blocking_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("record must not call the blocking subprocess.run")

    monkeypatch.setattr(subprocess, "run", blocking_run)

    exit_code = main(_record_argv(worktree))

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    page = asyncio.run(
        ExecutionEvidenceStore(durable_root).read_artifact(EXECUTION_ID, result["review_ref"]["artifact_id"])
    )
    assert ReviewArtifact.model_validate_json(page["content"]).head_sha == head_sha


def _record_argv_for(worktree: Path, feature: str) -> list[str]:
    """`_record_argv` with `--feature` set to `feature` instead of FEATURE_SLUG."""
    argv = _record_argv(worktree)
    argv[argv.index("--feature") + 1] = feature
    return argv


@pytest.mark.parametrize(
    "feature",
    [FEATURE_ID, "checkpoint", f"../index/{FEATURE_SLUG}"],
    ids=["feature_id", "substring", "path_traversal"],
)
def test_record_rejects_feature_without_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], feature: str
) -> None:
    """A --feature that is not an index slug is invalid_input with nothing stored (issue:b9ff30bf709e).

    finalize_task matches the stored feature_slug against the per-spec index file stem, so any other form would
    only fail later, at finalize. The traversal case resolves to the real index and is refused for its separator.
    """
    worktree = _build_repo(tmp_path)
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))

    exit_code = main(_record_argv_for(worktree, feature))

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert result["ok"] is False
    assert result["error"] == "invalid_input"
    assert repr(feature) in result["message"]
    assert not (durable_root / "executions" / EXECUTION_ID / "artifacts").exists()


def test_record_accepts_brief_index_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A brief index slug resolves like in `prepare` and is stored as the artifact's feature_slug."""
    worktree = _build_repo(tmp_path)
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))
    brief_dir = worktree / "sdd" / "briefs"
    brief_dir.mkdir(parents=True)
    (brief_dir / "brief-demo.index.json").write_text(
        json.dumps({"feature": "brief-demo", "tasks": []}), encoding="utf-8"
    )

    exit_code = main(_record_argv_for(worktree, "brief-demo"))

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    page = asyncio.run(
        ExecutionEvidenceStore(durable_root).read_artifact(EXECUTION_ID, result["review_ref"]["artifact_id"])
    )
    assert ReviewArtifact.model_validate_json(page["content"]).feature_slug == "brief-demo"
