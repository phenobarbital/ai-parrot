---
id: FC-005
query_id: Q019
type: read
intent: "Read close_task: what state it writes when the LAST task of a feature closes (completed_at? any event?)."
executed_at: 2026-11-07T01:21:26Z
duration_ms: 2000
parent_id: null
depth: 0
---

# FC-005 — close_task stamps feature completed_at when the last task closes and emits a best-effort task.closed ledger event

## Summary

`packages/ai-parrot/src/parrot/sdd/scripts/close_task.py` (port of `close_task.sh` C1–C14) is what both the worker and /sdd-done call to close a task. `update_index()` (65-95) sets the task `done`, write-once `completed_at`/`verification`, and when **all** tasks are done stamps the top-level `data["completed_at"]` — i.e. the per-spec index header already carries a feature-completion marker that the worker itself writes. After the ✅ line, `_emit_task_closed()` (97-126) appends a `task.closed` `LedgerEvent` (actor `agent:close_task.sh`, payload `{feature, verification}`) to `<shared_root>/.parrot/ledger/events.jsonl` via `LedgerLog.append`, best-effort ("never raises, never changes the exit code"). This is the exact pattern — and the exact call site — where a `work.completed` event would naturally be emitted when the last task closes, except that today the emitter is the worker's own process, which violates the separation-of-powers goal if the event is treated as a verdict rather than a trigger.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py`
  lines: 65-69
  symbol: `update_index`
  excerpt: |
    def update_index(index: Path, task_id: str, verification: str, completed_file: str, now: str) -> None:
        """C10: mark ``task_id`` done in the per-spec index; stamp top-level completed_at when every task is done.
        ``completed_at`` and ``verification`` are write-once (dev f9e08bee3, issue:732f350600d1): a re-run on an
        already-closed task — the idempotent path — re-asserts status/file but never moves recorded history to now.

- path: `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py`
  lines: 83-88
  symbol: `update_index`
  excerpt: |
            task["status"] = "done"
            task["completed_at"] = task.get("completed_at") or now
            task["verification"] = task.get("verification") or verification
    if all(t.get("status") == "done" for t in tasks):
        data["completed_at"] = data.get("completed_at") or now

- path: `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py`
  lines: 97-98
  symbol: `_emit_task_closed`
  excerpt: |
    def _emit_task_closed(start_dir: Path, task_id: str, feature_slug: str, verification: str) -> None:
        """C14: best-effort ``task.closed`` ledger event; never raises, never changes the exit code.

- path: `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py`
  lines: 129-144
  symbol: `_emit_task_closed_inprocess`
  excerpt: |
    def _emit_task_closed_inprocess(start_dir: Path, task_id: str, feature_slug: str, verification: str) -> None:
        from parrot.knowledge.wiki.ledger.events import LedgerEvent  # lazy: navconfig chdirs on import
        from parrot.knowledge.wiki.ledger.log import LedgerLog
        from parrot.knowledge.wiki.project import find_shared_root
        shared_root = find_shared_root(start_dir) or start_dir
        ledger_dir = shared_root / ".parrot" / "ledger"
        event = LedgerEvent(
            kind="task.closed",
            subject=f"task:{task_id}",
            actor="agent:close_task.sh",
            payload={"feature": feature_slug, "verification": verification},
        )
        LedgerLog(str(ledger_dir / "events.jsonl")).append(event)

- path: `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py`
  lines: 223-224
  symbol: `main`
  excerpt: |
        _out(f"✅ {task_id} closed (verification={verification}). active/ is clean.")
        _emit_task_closed(repo_root, task_id, feature_slug, verification)  # C14 — after the ✅ line

## Notes

- Lines 108-121: an `override` interpreter (`PARROT_SDD_LEDGER_PYTHON`-style) is used when the current interpreter cannot import `parrot` (sandbox) — relevant for emitting from inside the worker sandbox.
- The feature-level `completed_at` is stamped by the worker's own close call, so today "feature completed" is literally the worker grading itself.
