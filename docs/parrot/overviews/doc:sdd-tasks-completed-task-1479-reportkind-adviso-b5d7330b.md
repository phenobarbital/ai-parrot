---
type: Wiki Overview
title: 'TASK-1479: Add `ReportKind.ADVISORY` enum value'
id: doc:sdd-tasks-completed-task-1479-reportkind-advisory-enum-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The daily advisory output produced by the new `SecurityAdvisor` agent must
  be
relates_to:
- concept: mod:parrot.storage.security_reports
  rel: mentions
---

# TASK-1479: Add `ReportKind.ADVISORY` enum value

**Feature**: FEAT-226 — SecurityAdvisor (SOC2-Oriented Read-Only Advisory Agent)
**Spec**: `sdd/specs/security-advisor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The daily advisory output produced by the new `SecurityAdvisor` agent must be
persisted in the existing security-report catalog as a `ReportRef`, and must be
**distinguishable** from raw scans (`SCAN`), the existing summaries
(`DAILY_SUMMARY` / `WEEKLY_SUMMARY` / `MONTHLY_SUMMARY`) and drift comparisons
(`DRIFT_COMPARISON`). This task adds one additive enum member so downstream
tasks can set `report_kind=ReportKind.ADVISORY`.

Implements spec §3 Module 0.

---

## Scope

- Add a single member `ADVISORY = "advisory"` to the `ReportKind` enum.
- Add/extend a unit test asserting the member exists and its value is `"advisory"`.

**NOT in scope**:
- Any DDL / Postgres migration — `security_reports.report_kind` is a **text**
  column; the additive value needs no schema change.
- Touching `store.py`, parsers, or the toolkits.
- Producing advisory reports (that is TASK-1482 / TASK-1483).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/security_reports/models.py` | MODIFY | Add `ADVISORY = "advisory"` to `ReportKind` |
| `tests/storage/security_reports/test_models.py` | MODIFY | Assert `ReportKind.ADVISORY.value == "advisory"` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage.security_reports import ReportKind  # verified: .../security_reports/__init__.py:6-12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/storage/security_reports/models.py:25
class ReportKind(str, Enum):
    SCAN = "scan"                       # :28
    DAILY_SUMMARY = "daily_summary"     # :29
    WEEKLY_SUMMARY = "weekly_summary"   # :30
    MONTHLY_SUMMARY = "monthly_summary" # :31
    DRIFT_COMPARISON = "drift_comparison"  # :32
    # ADD: ADVISORY = "advisory"
```

The `report_kind` column is inserted as text via `ref.report_kind.value`
(verified: `store.py:235` `_INSERT_SQL`, and `save_report` passes
`ref.report_kind.value`). `_row_to_ref` reconstructs via
`ReportKind(row["report_kind"])` (verified: `store.py:127`), so the new value
round-trips with no further change.

### Does NOT Exist
- ~~A `report_kind` CHECK constraint / Postgres enum type~~ — the column is text;
  no DB migration is required (do not write one).
- ~~`ReportKind.ADVISORY`~~ — this task creates it.

---

## Implementation Notes

### Pattern to Follow
```python
class ReportKind(str, Enum):
    SCAN = "scan"
    DAILY_SUMMARY = "daily_summary"
    WEEKLY_SUMMARY = "weekly_summary"
    MONTHLY_SUMMARY = "monthly_summary"
    DRIFT_COMPARISON = "drift_comparison"
    ADVISORY = "advisory"   # NEW (FEAT-226)
```

### Key Constraints
- Pure additive change; do not reorder or rename existing members.
- Keep the `str, Enum` base so `.value` continues to be the inserted text.

---

## Acceptance Criteria

- [ ] `ReportKind.ADVISORY` exists and `ReportKind.ADVISORY.value == "advisory"`.
- [ ] Existing `ReportKind` members are unchanged.
- [ ] Tests pass: `pytest tests/storage/security_reports/test_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/storage/security_reports/models.py`
- [ ] Import works: `from parrot.storage.security_reports import ReportKind`

---

## Test Specification

```python
# tests/storage/security_reports/test_models.py
from parrot.storage.security_reports import ReportKind


def test_reportkind_advisory_member():
    assert ReportKind.ADVISORY.value == "advisory"
    assert ReportKind("advisory") is ReportKind.ADVISORY
```

---

## Agent Instructions

1. Read the spec at the path above (§3 Module 0, §6 Codebase Contract).
2. Verify the `ReportKind` enum still matches the contract before editing.
3. Make the additive change, add the test, run pytest + ruff.
4. Move this file to `sdd/tasks/completed/` and update the per-spec index to `done`.
5. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-05
**Notes**: Added `ADVISORY = "advisory"` to `ReportKind` enum in models.py. Added `test_reportkind_advisory_member` to existing test class. 21/21 tests pass, ruff clean.

**Deviations from spec**: none
