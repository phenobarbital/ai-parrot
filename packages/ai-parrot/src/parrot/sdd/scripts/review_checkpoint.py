"""Prepare, validate, or record the durable review handoff from authoritative local state.

Spec `sdd/specs/sdd-execution-optimization.spec.md` (FEAT-584), module M4
(R5 "Checkpoint antes del code reviewer"). Every fact this CLI reports comes
from durable, on-disk state (the settlement `end_execution` published, the
per-spec index/spec/convention files, and `git`) -- never from an in-memory
engine table, and never from a SHA the caller supplies: `prepare` always
resolves HEAD/branch/base SHA locally via `git`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from parrot.flows.dev_loop.procs import git_env, run_bounded
from parrot.flows.dev_loop.sdd_coder.checkpoint import (
    GIT_TIMEOUT_S,
    CheckpointBusyError,
    CheckpointError,
    CheckpointIncompleteError,
    CheckpointStaleError,
    load_review_checkpoint,
    prepare_review_checkpoint,
    validate_review_checkpoint,
)
from parrot.flows.dev_loop.sdd_coder.evidence import EvidenceCorruptionError, ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import ReviewArtifact, ReviewCheckpoint
from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root

#: Mirrors `scripts.sdd.finalize_task._TELEMETRY_ROOT_ENV` -- the same
#: env-var contract, so `prepare` and `validate_review_checkpoint`'s own
#: internal resolution (`checkpoint.py`) always agree on one durable root.
_TELEMETRY_ROOT_ENV = "SDD_CODER_TELEMETRY_DIR"


def _checkpoint_summary(checkpoint: ReviewCheckpoint) -> dict[str, object]:
    """Bounded, JSON-serializable projection -- never the full brief/refs payload twice."""
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "execution_id": checkpoint.execution_id,
        "feature": checkpoint.feature,
        "worktree": checkpoint.worktree,
        "branch": checkpoint.branch,
        "base_sha": checkpoint.base_sha,
        "implementation_head": checkpoint.implementation_head,
        "commits": len(checkpoint.commits),
        "task_refs": len(checkpoint.task_refs),
        "criteria_refs": len(checkpoint.criteria_refs),
        "validation_refs": len(checkpoint.validation_refs),
        "evidence_refs": len(checkpoint.evidence_refs),
        "pending_actions": checkpoint.pending_actions,
        "neutral_brief": checkpoint.neutral_brief,
        "relative_path": f"executions/{checkpoint.execution_id}/review/{checkpoint.checkpoint_id}.json",
    }


def _build_store(worktree: Path) -> ExecutionEvidenceStore:
    configured_root = os.environ.get(_TELEMETRY_ROOT_ENV) or None
    root = resolve_durable_root(configured_root, worktree_base_path=str(worktree))
    return ExecutionEvidenceStore(root)


async def _run_prepare(
    *, feature: str, worktree: Path, execution_id: str, store: ExecutionEvidenceStore
) -> dict[str, object]:
    checkpoint = await prepare_review_checkpoint(
        feature=feature, worktree=worktree, execution_id=execution_id, store=store
    )
    return _checkpoint_summary(checkpoint)


async def _run_validate(
    *, feature: str, worktree: Path, execution_id: str, checkpoint_id: str, store: ExecutionEvidenceStore
) -> dict[str, object]:
    checkpoint = await load_review_checkpoint(execution_id, checkpoint_id, store=store)
    if checkpoint.feature != feature:
        raise ValueError(f"--feature {feature!r} does not match checkpoint.feature {checkpoint.feature!r}")
    await validate_review_checkpoint(checkpoint, worktree=worktree)
    return {**_checkpoint_summary(checkpoint), "valid": True}


async def _run_record(
    *,
    feature: str,
    task: str,
    worktree: Path,
    summary: str,
    execution_id: str,
    fix_commits: list[str],
    store: ExecutionEvidenceStore,
) -> dict[str, object]:
    """Publish a manual semantic review artifact for task finalization.

    HEAD is read through the bounded, headless ``run_bounded`` helper so the
    event loop never blocks on git; a failed, timed-out or missing git raises
    ``subprocess.CalledProcessError`` with git's stderr attached.
    """
    argv = ["git", "-C", str(worktree), "rev-parse", "HEAD"]
    rc, stdout, stderr = await run_bounded(argv, timeout_s=GIT_TIMEOUT_S, env=git_env())
    if rc:
        raise subprocess.CalledProcessError(rc, argv, output=stdout, stderr=stderr)
    head_sha = stdout.strip()
    artifact = ReviewArtifact(
        feature_slug=feature,
        task_id=task,
        execution_id=execution_id,
        source="manual",
        summary=summary,
        fix_commits=fix_commits,
        head_sha=head_sha,
        recorded_at=datetime.now(timezone.utc),
    )
    review_ref = await store.put_artifact(execution_id, artifact)
    return {"execution_id": execution_id, "review_ref": review_ref.model_dump()}


def main(argv: list[str] | None = None) -> int:
    """Prepare, validate, or record reviews with stable JSON output.

    Exit codes: 0 success, 1 operation error, 2 invalid input, 3 stale/busy.

    ``record`` without ``--execution-id`` generates a fresh execution UUID; the
    output reports it as ``execution_id`` with ``execution_id_generated: true``.
    """
    parser = argparse.ArgumentParser(prog="python -m scripts.sdd.review_checkpoint", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare", help="Publish a durable review checkpoint from local settlement.")
    prepare_parser.add_argument("--feature", required=True)
    prepare_parser.add_argument("--worktree", required=True)
    prepare_parser.add_argument("--execution-id", required=True)

    validate_parser = sub.add_parser("validate", help="Reject a stale checkpoint before starting review.")
    validate_parser.add_argument("--feature", required=True)
    validate_parser.add_argument("--worktree", required=True)
    validate_parser.add_argument("--execution-id", required=True)
    validate_parser.add_argument("--checkpoint-id", required=True)

    record_parser = sub.add_parser("record", help="Publish a semantic review as durable evidence for finalize.")
    record_parser.add_argument("--feature", required=True)
    record_parser.add_argument("--task", required=True)
    record_parser.add_argument("--worktree", required=True)
    record_parser.add_argument("--summary", required=True)
    record_parser.add_argument(
        "--execution-id",
        help="Execution UUID that owns the review artifact. When omitted, a fresh UUID is generated and "
        "reported as execution_id with execution_id_generated=true.",
    )
    record_parser.add_argument("--fix-commit", action="append", default=[])

    args = parser.parse_args(argv)
    worktree = Path(args.worktree)

    try:
        store = _build_store(worktree)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": "invalid_input", "message": str(exc)}))
        return 2

    try:
        if args.command == "prepare":
            result = asyncio.run(
                _run_prepare(feature=args.feature, worktree=worktree, execution_id=args.execution_id, store=store)
            )
        elif args.command == "validate":
            result = asyncio.run(
                _run_validate(
                    feature=args.feature,
                    worktree=worktree,
                    execution_id=args.execution_id,
                    checkpoint_id=args.checkpoint_id,
                    store=store,
                )
            )
        else:
            execution_id_generated = not args.execution_id
            execution_id = args.execution_id or str(uuid.uuid4())
            result = asyncio.run(
                _run_record(
                    feature=args.feature,
                    task=args.task,
                    worktree=worktree,
                    summary=args.summary,
                    execution_id=execution_id,
                    fix_commits=args.fix_commit,
                    store=store,
                )
            )
            result["execution_id_generated"] = execution_id_generated
    except (ValidationError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": "invalid_input", "message": str(exc)}))
        return 2
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        message = f"{exc}: {detail}" if detail else str(exc)
        print(json.dumps({"ok": False, "error": "operation_error", "message": message}))
        return 1
    except (CheckpointBusyError, CheckpointStaleError, CheckpointIncompleteError) as exc:
        print(json.dumps({"ok": False, "error": exc.error_code, "message": str(exc)}))
        return 3
    except CheckpointError as exc:
        print(json.dumps({"ok": False, "error": exc.error_code, "message": str(exc)}))
        return 1
    except (OSError, EvidenceCorruptionError) as exc:
        print(json.dumps({"ok": False, "error": "operation_error", "message": str(exc)}))
        return 1

    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
