"""Prepare or validate the durable review handoff from authoritative local state.

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
from pathlib import Path

from parrot.flows.dev_loop.sdd_coder.checkpoint import (
    CheckpointBusyError,
    CheckpointError,
    CheckpointIncompleteError,
    CheckpointStaleError,
    load_review_checkpoint,
    prepare_review_checkpoint,
    validate_review_checkpoint,
)
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import ReviewCheckpoint
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


def main(argv: list[str] | None = None) -> int:
    """Prepare/validate: same codes and JSON output with a reference to the checkpoint.

    Exit codes: 0 success, 1 operation error, 2 invalid input, 3 stale/busy.
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
        else:
            result = asyncio.run(
                _run_validate(
                    feature=args.feature,
                    worktree=worktree,
                    execution_id=args.execution_id,
                    checkpoint_id=args.checkpoint_id,
                    store=store,
                )
            )
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": "invalid_input", "message": str(exc)}))
        return 2
    except (CheckpointBusyError, CheckpointStaleError, CheckpointIncompleteError) as exc:
        print(json.dumps({"ok": False, "error": exc.error_code, "message": str(exc)}))
        return 3
    except CheckpointError as exc:
        print(json.dumps({"ok": False, "error": exc.error_code, "message": str(exc)}))
        return 1
    except OSError as exc:
        print(json.dumps({"ok": False, "error": "operation_error", "message": str(exc)}))
        return 1

    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
