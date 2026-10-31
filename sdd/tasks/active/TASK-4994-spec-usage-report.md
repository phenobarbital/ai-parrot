# TASK-4994: build_spec_usage_report — per-feature roll-up by task/model/seat

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4989, TASK-4990
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (report half), G7, AC-12. `build_usage_report` is keyed by run/seat only.
This task adds a per-feature sibling that reads `SpecUsageRecorder` rows and groups by
task, model or seat. It reuses `UsageReport`/`AgentUsage`/`CycleUsage` and the existing
markdown/HTML renderers, so the views cannot disagree.

---

## Scope

- Add `build_spec_usage_report(rows: Iterable[UsageRecord], feat_id: str, *, by: str = "task") -> UsageReport`, with `by ∈ {"task", "model", "seat"}`. Any other value raises `ValueError`.
- Group key per row: `task_id`, `model` or `roster_seat` (a missing key becomes `"(unattributed)"`). Each group becomes one `AgentUsage`: `seat` = the group key, `rounds` = distinct `attempt_uid`s, token sums skip `usage_reported=False`.
- Cost: add **optional, defaulted** fields `cost_usd`/`equivalent_usd` to `AgentUsage` and `total_cost_usd`/`total_equivalent_usd` to `UsageReport`, summed from rows. **Never sum `source_cost_usd` or `cumulative_cost_usd`** (AC-5, spec §7). An all-unpriced group totals `None`.
- Show cost in the markdown/HTML renderers only when present, so existing run reports render byte-identically.
- Tests.

**NOT in scope**: the CLI and MCP tool (TASK-4995).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py` | MODIFY | Builder + optional cost fields + renderer columns |
| `packages/ai-parrot/tests/flows/dev_loop/test_spec_usage_report.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.usage_report import build_usage_report, UsageReport, AgentUsage, CycleUsage   # usage_report.py:125
from parrot.flows.dev_loop.run_bundle import _sum_optional_float, _sum_optional_int                      # usage_report.py:31
from parrot.observability.recorders.models import UsageRecord
```

### Existing Signatures to Use
```python
# usage_report.py
class _Frozen(BaseModel): model_config = ConfigDict(frozen=True, extra="forbid")   # :35
class CycleUsage(_Frozen): cycle: int; model: str=""; input_tokens; output_tokens; duration_seconds; status; error_type  # :44
# AgentUsage(seat, node_id, backend, model, rounds, input_tokens, output_tokens, duration_seconds, cycles, failures)  — see :174-187
# UsageReport(run_id, agents, total_input_tokens, total_output_tokens, total_rounds, partial, partial_reason)       — see :190-198
def build_usage_report(ledger: RunLedgerRecorder, run_id: str) -> UsageReport:   # :125 (1 occurrence) — anchor
# markdown + HTML renderer functions live further down usage_report.py (grep -n '^def ' usage_report.py)
```

### Does NOT Exist
- ~~`usage_report.feat_id`~~ / ~~`UsageReport.feat_id`~~ — the report is run-keyed; use `run_id=feat_id` for the per-feature view, do NOT add a field
- ~~`AgentUsage.cost_usd`~~ — this task adds it (optional, default None)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_spec_usage_report.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py#build_usage_report",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py#UsageReport",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py#AgentUsage",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py#CycleUsage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The module stays a **pure consumer** (no filesystem). The CLI (TASK-4995) reads rows with `read_spec_usage` and passes them in.
- `extra="forbid"` models: new fields must have defaults, or existing constructors break.
- `node_id` for a spec group: use `feat_id`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the optional cost fields with `None` defaults.
2. Add the builder after `build_usage_report`.
3. Add renderer columns guarded by "any agent has cost". Existing snapshot tests must stay byte-identical.
4. Tests.

### `usage_report.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def build_usage_report(ledger: RunLedgerRecorder, run_id: str) -> UsageReport:' usage_report.py)
# AFTER build_usage_report's return (ends ~:200), add:
_SPEC_GROUPINGS = {"task": "task_id", "model": "model", "seat": "roster_seat"}


def build_spec_usage_report(rows: Iterable[UsageRecord], feat_id: str, *, by: str = "task") -> UsageReport:
    """Per-feature sibling of build_usage_report, grouping SpecUsageRecorder rows by task/model/seat.

    Reuses CycleUsage/AgentUsage and the existing renderers so the three views cannot disagree.
    Costs sum `cost_usd` (post-policy) and `equivalent_usd`; `source_cost_usd` and the
    process-cumulative `cumulative_cost_usd` are NEVER summed (AC-5).
    """
    if by not in _SPEC_GROUPINGS:
        raise ValueError(f"by must be one of {sorted(_SPEC_GROUPINGS)}, got {by!r}")
    attr = _SPEC_GROUPINGS[by]
    groups: dict[str, list[UsageRecord]] = {}
    for row in rows:
        if row.feat_id != feat_id:
            continue
        groups.setdefault(getattr(row, attr) or "(unattributed)", []).append(row)
    # FILL IN: one AgentUsage per group (rounds = distinct attempt_uid, legacy rows counted individually;
    # token sums over usage_reported rows else None; cost sums via _sum_optional_float; cycles from rows
    # numbered 1..n), then UsageReport(run_id=feat_id, ...) with totals — bounded by AC-12 / AC-5
    raise NotImplementedError
```
Add `from typing import Iterable` and `from parrot.observability.recorders.models import UsageRecord` to the imports.

### `test_spec_usage_report.py` (CREATE)
```python
"""FEAT-783 AC-12 — per-spec report."""
import pytest

from parrot.flows.dev_loop.usage_report import build_spec_usage_report
from parrot.observability.recorders.models import UsageRecord


def _row(**kw) -> UsageRecord:
    return UsageRecord(provider=kw.pop("provider", "anthropic"), **kw)


def test_groups_by_task_model_seat() -> None:
    # FILL IN
    ...


def test_source_and_cumulative_cost_never_summed() -> None:
    # FILL IN: rows with source_cost_usd/cumulative_cost_usd large, cost_usd small -> totals use cost_usd only
    ...


def test_other_features_rows_excluded_and_bad_by_raises() -> None:
    # FILL IN
    ...


def test_run_report_render_unchanged_without_cost() -> None:
    # FILL IN: build_usage_report on a cost-less ledger renders without a cost column
    ...
```

### FILL IN checklist
- [ ] Builder body; bounded by AC-12/AC-5
- [ ] Renderer cost columns (only when present)
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] AC-12 (report half): tokens and cost grouped by task, model or seat for one feature.
- [ ] AC-5: `source_cost_usd` and `cumulative_cost_usd` are never summed.
- [ ] Existing `test_usage_report.py` stays green (no render drift).

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_spec_usage_report.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Two files only. `PYTHONPATH=packages/ai-parrot/src`.

## Completion Note
_(filled at close)_
