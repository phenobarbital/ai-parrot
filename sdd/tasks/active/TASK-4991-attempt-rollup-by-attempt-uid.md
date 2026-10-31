# TASK-4991: Attempt roll-up derived from the sink; by_seat aggregates by attempt_uid

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4990
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, design review S3, AC-11. Two defects:

1. `RunLedgerRecorder.by_seat()` sets `rounds=len(cycles)`, so one attempt that emits a usage event **and** its paired `ClientCallFailedEvent` (claude.py's failure path) counts as two cycles.
2. `AttemptUsageRow` provider counters are read from `record.usage` independently, rather than derived from the per-call source of truth.

---

## Scope

- `RunLedgerRecorder.by_seat()`: group records by `attempt_uid` (records without one keep today's one-record-one-cycle behaviour) before counting `rounds`. Token sums and `failures` semantics are unchanged.
- `build_attempt_row(...)`: add an optional keyword `spec_rows: Optional[list[UsageRecord]] = None`. When rows for this `attempt_uid` are given, derive `provider_input_tokens`/`provider_output_tokens` from them (sum over `usage_reported` rows). Otherwise keep today's `record.usage` path. `ledger_*` fields and `calibration_eligible` are unchanged.
- Tests.

**NOT in scope**: wiring `spec_rows` at the engine call site (TASK-4992); the report (TASK-4994).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/recorders/run_ledger.py` | MODIFY | Aggregate by `attempt_uid` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py` | MODIFY | `spec_rows` derivation |
| `packages/ai-parrot/tests/observability/test_run_ledger_attempt_cycles.py` | CREATE | AC-11 |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_attempt_row_from_spec_rows.py` | CREATE | Derivation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.recorders.run_ledger import RunLedgerRecorder, SeatUsage   # run_ledger.py:65, :30
from parrot.observability.recorders.models import UsageRecord                        # attempt_uid added by TASK-4985
from parrot.flows.dev_loop.sdd_coder.telemetry import build_attempt_row, AttemptUsageRow  # telemetry.py:160
```

### Existing Signatures to Use
```python
# run_ledger.py
    def by_seat(self) -> list[SeatUsage]:   # :134 — rounds=len(cycles) at ~:162; SeatUsage(frozen, extra="forbid")
# sdd_coder/telemetry.py
def build_attempt_row(record: AttemptRecord, *, feature_id: str, job_id: str, task_id: str, declared_files: Optional[int]) -> AttemptUsageRow  # :160
#   provider_input_tokens=record.usage.get("input_tokens") if isinstance(record.usage, dict) else None,   (~:248)
#   provider_output_tokens=record.usage.get("output_tokens") if isinstance(record.usage, dict) else None,
```

### Does NOT Exist
- ~~`SeatUsage.attempts`~~ — do not add a field; `SeatUsage` is `extra="forbid"` and report-facing
- ~~`build_attempt_row(..., spec_rows=...)`~~ — this task adds it (keyword-only, defaulted)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/run_ledger.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/observability/test_run_ledger_attempt_cycles.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_attempt_row_from_spec_rows.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/recorders/run_ledger.py#RunLedgerRecorder.by_seat",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#build_attempt_row"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `cycles` on `SeatUsage` still lists **every** record (the report shows them). Only `rounds` changes meaning, to "distinct attempts".
- Keep `build_attempt_row`'s explicit-allowlist rule (never `model_dump()` an AttemptRecord).

---

## Implementation Blueprint

### Steps (in order)
1. In `by_seat`, compute `rounds = len({r.attempt_uid or f"_cycle{i}" for i, r in enumerate(cycles)})`. A missing `attempt_uid` keeps one-record-one-round, so FEAT-479 tests stay green.
2. Add `spec_rows` to `build_attempt_row` and the derivation branch.
3. Tests.

### `run_ledger.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def by_seat(self) -> list\[SeatUsage\]:' run_ledger.py), :134
# inside the per-seat loop, before SeatUsage(...):
            # FEAT-783 S3: one attempt that emitted a usage event AND a failure event is ONE round.
            attempts = {r.attempt_uid or f"_cycle{i}" for i, r in enumerate(cycles)}
# and change `rounds=len(cycles),` to:
                    rounds=len(attempts),
```
Update the docstring and the `SeatUsage.rounds` attribute doc ("distinct attempts; records without attempt_uid count individually").

### `telemetry.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def build_attempt_row(' telemetry.py), :160 — widen the signature:
def build_attempt_row(
    record: AttemptRecord,
    *,
    feature_id: str,
    job_id: str,
    task_id: str,
    declared_files: Optional[int],
    spec_rows: "Optional[List[UsageRecord]]" = None,
) -> AttemptUsageRow:
```
```python
# before `return AttemptUsageRow(`:
    provider_input_tokens, provider_output_tokens = _provider_counters(record, attempt_uid, spec_rows)
# and use those two names in place of the record.usage expressions.

def _provider_counters(record, attempt_uid: str, spec_rows) -> "tuple[Optional[int], Optional[int]]":
    """FEAT-783 M6: derive from SpecUsageRecorder rows for this attempt_uid; else legacy record.usage."""
    # FILL IN: rows = [r for r in spec_rows or [] if r.attempt_uid == attempt_uid and r.usage_reported];
    # rows -> (sum input, sum output); no rows -> legacy expressions — bounded by "never fabricate 0"
    raise NotImplementedError
```
Import `UsageRecord` under `TYPE_CHECKING` only.

### Tests (CREATE)
```python
# test_run_ledger_attempt_cycles.py
"""FEAT-783 AC-11 — usage + failure for one attempt is one round."""
import pytest

@pytest.mark.asyncio
async def test_usage_and_failure_same_attempt_is_one_round() -> None:
    # FILL IN: two records same seat, same attempt_uid (one completed, one failed) -> rounds == 1, failures == 1, len(cycles) == 2
    ...

@pytest.mark.asyncio
async def test_records_without_attempt_uid_keep_legacy_count() -> None:
    # FILL IN
    ...
```
```python
# test_attempt_row_from_spec_rows.py
"""FEAT-783 M6 — attempt row derived from spec rows."""

def test_spec_rows_override_record_usage() -> None:
    # FILL IN: build a minimal AttemptRecord (follow tests/flows/dev_loop/sdd_coder/test_telemetry.py fixtures)
    ...

def test_no_spec_rows_keeps_legacy_path() -> None:
    # FILL IN
    ...
```

### FILL IN checklist
- [ ] `_provider_counters`; bounded by "never fabricate 0"
- [ ] Test bodies; bounded by AC-11

---

## Acceptance Criteria

- [ ] AC-11: one attempt with a usage event and a failure event counts as one round.
- [ ] Existing run-ledger, usage-report and telemetry tests stay green.

## Validation Commands
- `pytest packages/ai-parrot/tests/observability/test_run_ledger_attempt_cycles.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_attempt_row_from_spec_rows.py -q`
- `pytest packages/ai-parrot/tests/observability/test_run_ledger_recorder.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Four files only. `PYTHONPATH=packages/ai-parrot/src`.

## Completion Note
_(filled at close)_
