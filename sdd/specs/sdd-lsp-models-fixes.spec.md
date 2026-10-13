# SDD LSP Benchmark Models Fixes — FEAT-661

```yaml
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [benchmarks, sdd-lsp, tech-debt, ledger-fix]
```

## 1. Problem

Two issues from the FEAT-580 adversarial code review of the SDD LSP benchmark:

1. **Unpopulated AttemptRecord fields** (issue:65185c6c4f4a, major) —
   `_run_one_attempt` in `runner.py` never sets `tool_calls`,
   `lsp_operations`, `correction_cycles`, or `retries` on `AttemptRecord` —
   they silently default to 0. `report.py`'s per-arm totals always read 0
   in a real run.

2. **Dead 'result_limit' code** (issue:4b0e5d3b1a42, low) — `result_limit`
   is a named operational error code in the spec's Data Models table but
   doesn't appear to be used in toolkit.py's merged code.

## 2. Solution

### M1 — Populate AttemptRecord metrics from trace (runner.py)

Parse the seat's `trace.jsonl` per-attempt summary (or `attempt_meta.json`)
to extract tool_calls, lsp_operations, correction_cycles, and retries counts.
Thread them into `AttemptRecord` construction.

### M2 — Confirm or remove result_limit (models.py)

Grep for `result_limit` across the codebase. If used, document where; if
dead, remove it from the error-code enum/model.

## 3. Files

| File | Module | Action |
|---|---|---|
| `benchmarks/sdd_lsp/runner.py` | M1 | MODIFY |
| `benchmarks/sdd_lsp/models.py` | M2 | MODIFY |

## 4. Acceptance Criteria

- AC1: `AttemptRecord.tool_calls` etc. are populated from real trace data (not hardcoded 0)
- AC2: `result_limit` is confirmed used or removed
- AC3: `ruff check benchmarks/sdd_lsp/` passes
- AC4: Existing benchmark tests pass
