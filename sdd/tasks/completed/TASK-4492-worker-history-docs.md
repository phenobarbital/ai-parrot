# TASK-4492: Documentation page for Workday worker history

**Feature**: FEAT-706 — Workday Worker Event History and Job Changes
**Spec**: `sdd/specs/workday-worker-event-history-and-job-changes.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4490, TASK-4491
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (docs part) and spec §8 resolution 3: the page lives at
`docs/tools/workday-worker-history.md`. It documents the finished surfaces, so it waits for
the registration (TASK-4490, operation keys and routing) and the toolkit tools (TASK-4491,
tool names and parameters). Note: `docs/tools/` already exists (it holds `compression.md`
and `jira-templates.md`), contrary to spec §6 "Does NOT Exist" — just add the file.

---

## Scope

- Write `docs/tools/workday-worker-history.md` covering, in this order:
  1. What each tool returns (`wd_get_worker_event_history`, `wd_get_worker_job_changes`) and the matching `fetch` / `fetch_models` keys.
  2. Worker resolution: WID by shape; otherwise Employee_ID then Contingent_Worker_ID on an `"Invalid ID value"` fault; explicit `worker_id_type` disables the fallback; the WID is sent to `Get_Worker_Event_History` as `Integration_ID_Reference` with `System_ID="WD-WID"`.
  3. The "references only, no delta" limitation of `Get_Worker_Event_History`, and how job changes are reconstructed (as-of snapshots the day before and the day of each event date, field diff, `kind` hire / change / no_change).
  4. Default job event types and the `include_compensation` flag: extra fields, widened event filter, and the compensation security-domain requirement (missing domain → pay fields `None` or a security fault).
  5. Call budget `2 + 2N` for `N` distinct dates, the concurrency of 4, and `effective_from/through` as the lever.
  6. Limitations: primary job only (`Worker_Job_Data[0]`), tenant-specific event names, contingent path tested by fixtures only, `Updated_Through` cannot be in the future.
  7. One example for each tool (agent call + abbreviated output) with synthetic ids.

**NOT in scope**: code changes; README or index updates elsewhere.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/tools/workday-worker-history.md` | CREATE | User-facing doc page |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none — documentation only. Every name the page cites must exist after TASK-4490/4491:
# WorkdayToolkit.wd_get_worker_event_history / wd_get_worker_job_changes   (TASK-4491, workday/tool.py)
# "get_worker_event_history" / "get_worker_job_changes" keys               (TASK-4490, config.py + service.py)
# JOB_CHANGE_EVENT_TYPES / COMPENSATION_EVENT_TYPES                        (TASK-4487, models/worker_event.py)
```

### Existing Signatures to Use
```python
# Re-read before writing (names/params must match the merged code, not this list):
# packages/ai-parrot-tools/src/parrot_tools/workday/tool.py — GetWorkerEventHistoryInput, GetWorkerJobChangesInput
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/worker_event.py — field names for the examples
```

### Does NOT Exist
- ~~A real worker's name, WID or Employee ID in examples~~ — use synthetic values only (e.g. `Jane Doe`, `0123456789abcdef0123456789abcdef`, `100001`).
- ~~`event_types` on the toolkit tool~~ — it is a handler/`fetch` parameter only; say so.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/tools/workday-worker-history.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Match the tone and heading style of `docs/tools/compression.md`.
- Every parameter, key and field name must be copied from the merged code; re-read it first.

---

## Implementation Blueprint

### Steps (in order)
1. Re-read `tool.py` input models and `models/worker_event.py` — *why*: names in the doc must match the merged code.
2. Write the page with the seven sections of Scope — *why*: AC lists each topic.
3. Run the Validation Commands — *why*: they prove every documented surface exists.

### `docs/tools/workday-worker-history.md` (CREATE)
```markdown
# Workday worker history

<!-- FILL IN: one-paragraph summary of the two tools and when to use which. -->

## Tools and operation keys
<!-- FILL IN: table tool → operation key → returns. -->

## How a worker is identified
<!-- FILL IN: Scope item 2. -->

## Event history is references only
<!-- FILL IN: Scope item 3, with the before/after diagram in prose. -->

## Job event types and compensation
<!-- FILL IN: Scope item 4. -->

## Cost and performance
<!-- FILL IN: Scope item 5. -->

## Limitations
<!-- FILL IN: Scope item 6. -->

## Examples
<!-- FILL IN: Scope item 7, synthetic ids only. -->
```

### FILL IN checklist
- [ ] All seven sections; bounded by the AC below.

---

## Acceptance Criteria

- [ ] `docs/tools/workday-worker-history.md` documents both tools, the WID/`WD-WID` resolution and the Employee→Contingent fallback, the `include_compensation` flag and its security-domain requirement, the call budget formula, and the "references only, no delta" limitation of `Get_Worker_Event_History`.
- [ ] No real worker data appears in the page.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/workday/test_worker_history_toolkit.py -q`
- `pytest packages/ai-parrot-tools/tests/workday/test_worker_history_registry.py -q`

---

## Test Specification

None beyond the Validation Commands: they confirm the documented tools and keys exist.

---

## Agent Instructions

1. Work in the feature worktree; TASK-4490 and TASK-4491 must be `done`.
2. Mark `in-progress`, write the page, run the Validation Commands.
3. Commit only the doc file; close with `scripts/sdd/close_task.sh TASK-4492 workday-worker-event-history-and-job-changes verified`.

---

## Completion Note


- Task: TASK-4492
- Feature: workday-worker-event-history-and-job-changes
- Implementation SHA: f0a52c177ba8423bc7a837e90b765a79f232fbd6
- Closed at (UTC): 2026-10-19T20:57:38+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 · Duration: 195.0s · Tokens: 552032/6322 |
