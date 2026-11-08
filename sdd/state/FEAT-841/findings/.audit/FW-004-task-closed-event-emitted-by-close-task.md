---
id: FW-004
query_id: Q002
type: wiki_page
intent: "Existing worker-side ledger emission: close_task appends task.closed in-process."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 400
parent_id: FW-002
depth: 2
---

# FW-004 — close_task already appends a task.closed ledger event from inside the worktree (actor agent:close_task.sh) — the natural emission point for work.completed when the last task closes

## Summary

`parrot/sdd/scripts/close_task.py:_emit_task_closed_inprocess` builds `LedgerEvent(kind="task.closed", subject="task:<id>", actor="agent:close_task.sh", payload={feature, verification})` and appends it to `<shared_root>/.parrot/ledger/events.jsonl` via `LedgerLog.append`, resolving the primary checkout with `find_shared_root(start_dir)` (the sandbox mounts `.parrot/ledger/` writable). It is the one place in the close path that already emits a ledger event from inside the sandbox; a `work.completed` on "all tasks of the feature closed" fits here or in the worker's Completion step.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py`
  lines: 129-144
  symbol: `_emit_task_closed_inprocess`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/sdd/scripts/close_task.py#_emit_task_closed_inprocess
  score: 0.06
  excerpt: |
    def _emit_task_closed_inprocess(start_dir, task_id, feature_slug, verification) -> None:
        shared_root = find_shared_root(start_dir) or start_dir
        ledger_dir = shared_root / ".parrot" / "ledger"
        event = LedgerEvent(kind="task.closed", subject=f"task:{task_id}",
                            actor="agent:close_task.sh",
                            payload={"feature": feature_slug, "verification": verification})
        LedgerLog(str(ledger_dir / "events.jsonl")).append(event)

## Notes

[cross-lane: type=read, intent=codebase lane Q019 should check whether close_task knows it closed the LAST pending task of the feature and whether it stamps completed_at.]
