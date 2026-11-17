---
id: F011
query_id: Q026
type: read
intent: "Read the review checkpoint script — the worker's own adversarial review record (what /sdd-done checks)."
executed_at: 2026-11-07T01:23:30Z
duration_ms: 1500
parent_id: null
depth: 0
merged_from: [FC-011]
---

# F011 — review_checkpoint binds the worker's review to implementation_head/base_sha and exits 3 on stale/busy — a head-bound-verdict precedent

## Summary

`packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py` (145 lines, FEAT-584 M4) exposes `parrot sdd task review prepare|validate`. `prepare` resolves HEAD/branch/base SHA locally via git — "never from a SHA the caller supplies" — and publishes a durable `ReviewCheckpoint` under `executions/<execution_id>/review/<checkpoint_id>.json` in the worktree's `ExecutionEvidenceStore`; `validate` rejects a stale checkpoint. Exit codes: 0 success, 1 operation error, 2 invalid input, 3 stale/busy. The summary projection carries `base_sha`, `implementation_head`, `commits`, `pending_actions`, `neutral_brief`. The escrow verdict needs exactly this binding (verdict ↔ head SHA, stale when HEAD moves) and could reuse `CheckpointStaleError` semantics and the evidence store instead of a new store. Note: this checkpoint is written by the worker (same lineage), so it is evidence *for* an external judge, not a verdict.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py`
  lines: 1-9
  symbol: null
  excerpt: |
    """Prepare or validate the durable review handoff from authoritative local state.
    Spec `sdd/specs/sdd-execution-optimization.spec.md` (FEAT-584), module M4
    (R5 "Checkpoint antes del code reviewer"). Every fact this CLI reports comes
    from durable, on-disk state ... and never from a SHA the caller supplies: `prepare` always
    resolves HEAD/branch/base SHA locally via `git`.

- path: `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py`
  lines: 19-25
  symbol: null
  excerpt: |
    from parrot.flows.dev_loop.sdd_coder.checkpoint import (
        CheckpointBusyError,
        CheckpointError,
        CheckpointIncompleteError,
        CheckpointStaleError,
        load_review_checkpoint,
        prepare_review_checkpoint,

- path: `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py`
  lines: 38-56
  symbol: `_checkpoint_summary`
  excerpt: |
    def _checkpoint_summary(checkpoint: ReviewCheckpoint) -> dict[str, object]:
            "checkpoint_id": checkpoint.checkpoint_id,
            "execution_id": checkpoint.execution_id,
            "base_sha": checkpoint.base_sha,
            "implementation_head": checkpoint.implementation_head,
            "commits": len(checkpoint.commits),
            "pending_actions": checkpoint.pending_actions,
            "neutral_brief": checkpoint.neutral_brief,
            "relative_path": f"executions/{checkpoint.execution_id}/review/{checkpoint.checkpoint_id}.json",

- path: `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py`
  lines: 59-59
  symbol: `_build_store`
  excerpt: |
    def _build_store(worktree: Path) -> ExecutionEvidenceStore:

- path: `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py`
  lines: 84-87
  symbol: `main`
  excerpt: |
    def main(argv: list[str] | None = None) -> int:
        """Prepare/validate: same codes and JSON output with a reference to the checkpoint.
        Exit codes: 0 success, 1 operation error, 2 invalid input, 3 stale/busy.

## Notes

- [cross-lane: type=wiki_page, intent=parrot.flows.dev_loop.sdd_coder.checkpoint ReviewCheckpoint model fields and ExecutionEvidenceStore layout]
