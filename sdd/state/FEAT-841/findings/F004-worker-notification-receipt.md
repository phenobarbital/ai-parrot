---
id: F004
query_id: Q018
type: read
intent: "Read the host-side worker notification script — what the worker emits to the host today (candidate for work.completed)."
executed_at: 2026-11-07T01:21:26Z
duration_ms: 2500
parent_id: null
depth: 0
merged_from: [FC-004]
---

# F004 — worker_notification.py already writes a head-SHA-bound completion receipt (desktop notify only)

## Summary

`packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py` (344 lines, stdlib only) is the only existing "worker → host" completion signal. `record_completion()` (lines 208-242) runs inside the sandbox at the end of a feature: it validates the launch context in `$PARROT_SDD_CACHE_DIR`, re-reads the per-spec index and refuses unless **every** task is `status == "done"`, resolves `git rev-parse HEAD` (`_head`, 40-hex validated) and writes an atomic 0600 receipt `notify-complete.json` = `{schema_version:1, launch_id, feature_id, worktree, head}`. On the host, a Claude `Stop` hook (`handle_stop`, line 273) consumes it exactly once, and `_receipt()` (244-261) only accepts it if the current HEAD still equals the recorded `head`. Delivery is a `notify-send` desktop toast — nothing is written to the ledger and no bus is involved. This is a near-complete `work.completed` emitter in shape (feature id, worktree, head SHA, all-tasks-done precondition, one-shot claim) but with a dead-end sink.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py`
  lines: 1-1
  symbol: null
  excerpt: |
    """Best-effort feature completion receipts and host desktop delivery (stdlib only)."""

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py`
  lines: 208-230
  symbol: `record_completion`
  excerpt: |
    def record_completion(env: Mapping[str, str]) -> bool:
        """Atomically record eligible feature completion in the existing session cache."""
        if (
            not isinstance(tasks, list)
            or not tasks
            or any(not isinstance(task, dict) or task.get("status") != "done" for task in tasks)
        ):
            _warn("feature tasks are incomplete")
            return False
        head = _head(worktree)

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py`
  lines: 232-242
  symbol: `record_completion`
  excerpt: |
        receipt: dict[str, object] = {
            "schema_version": 1,
            "launch_id": context["launch_id"],
            "feature_id": context["feature_id"],
            "worktree": context["worktree"],
            "head": head,
        }
        if not _write(cache / "notify-complete.json", receipt):

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py`
  lines: 110-120
  symbol: `_head`
  excerpt: |
    def _head(worktree: Path) -> str | None:
        """Return the validated current Git HEAD hash."""
        result = subprocess.run([git, "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, timeout=2)
        head = result.stdout.strip()
        return head if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", head) else None

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py`
  lines: 244-261
  symbol: `_receipt`
  excerpt: |
    def _receipt(cache: Path, context: Mapping[str, object]) -> bool:
        """Return whether a strict receipt matches context and the current Git HEAD."""
        if any(document[key] != context[key] for key in ("launch_id", "feature_id", "worktree")):
            return False
        return _head(Path(document["worktree"])) == document["head"]

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py`
  lines: 164-165
  symbol: `configure_notification`
  excerpt: |
    def configure_notification(cache: Path, *, worktree: Path, env: Mapping[str, str]) -> str | None:
        """Write validated launch context and return a quoted Stop command."""

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py`
  lines: 273-286
  symbol: `handle_stop`
  excerpt: |
    def handle_stop(payload: Mapping[str, object], *, cache: Path) -> None:
        """Attempt one notification for a valid Stop and receipt without propagating errors."""
            if payload.get("hook_event_name") != "Stop" or payload.get("background_tasks") or payload.get("session_crons"):
            notify_send = shutil.which("notify-send", path=desktop.get("PATH", os.defpath))

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py`
  lines: 315-321
  symbol: `main`
  excerpt: |
    def main(argv: Sequence[str] | None = None) -> int:
        modes.add_argument("--complete", action="store_true")
        modes.add_argument("--hook", action="store_true")
        parser.add_argument("--cache")

## Notes

- `configure_notification` is called by the launcher (`feature_launcher`) and installs the Stop hook command — the host side of the worker lifecycle already exists; a `work.completed` ledger event could be appended by the same Stop hook on the host (outside the sandbox).
- The receipt is deliberately stdlib-only and runs with `python -S` inside the sandbox — the sandbox cannot import `parrot`.
