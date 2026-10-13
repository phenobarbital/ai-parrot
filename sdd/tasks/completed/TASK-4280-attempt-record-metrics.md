# TASK-4280: Populate AttemptRecord metrics from trace

**Feature**: FEAT-661 — sdd-lsp-models-fixes
**Spec**: sdd/specs/sdd-lsp-models-fixes.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: agent

## Context

`_run_one_attempt` in `runner.py` never sets `tool_calls`, `lsp_operations`,
`correction_cycles`, or `retries` on `AttemptRecord` — they silently default
to 0. `report.py`'s per-arm `correction_cycles_total`/`retries_total` will
always read 0 in a real benchmark run.

Resolves ledger issue:65185c6c4f4a.

## Scope

Parse the seat's `trace.jsonl` per-attempt summary (or `attempt_meta.json`)
to extract tool_calls, lsp_operations, correction_cycles, and retries counts.
Thread them into `AttemptRecord` construction in `_run_one_attempt`.

### NOT in scope
- Changing the AttemptRecord model definition
- Modifying the seat protocol itself

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `benchmarks/sdd_lsp/runner.py` | MODIFY | Parse trace data and populate AttemptRecord fields |

## Acceptance Criteria

- [ ] `AttemptRecord.tool_calls` etc. are populated from real trace data (not hardcoded 0)
- [ ] Handles missing trace files gracefully (defaults to 0)
- [ ] `ruff check benchmarks/sdd_lsp/runner.py` passes

## Validation Commands

```bash
ruff check benchmarks/sdd_lsp/runner.py
PYTHONPATH=benchmarks pytest benchmarks/sdd_lsp/ -x -q --timeout=30 2>/dev/null || echo "benchmark tests may require fixtures"
```

## Completion Note

(filled by implementing agent)
