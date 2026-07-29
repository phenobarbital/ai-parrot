---
type: Wiki Overview
title: 'TASK-1483: Package exports + advisor documentation'
id: doc:sdd-tasks-completed-task-1483-exports-and-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Make the new advisory components importable from the package's public surface
relates_to:
- concept: mod:parrot_tools.security
  rel: mentions
---

# TASK-1483: Package exports + advisor documentation

**Feature**: FEAT-226 — SecurityAdvisor (SOC2-Oriented Read-Only Advisory Agent)
**Spec**: `sdd/specs/security-advisor.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1480, TASK-1481
**Assigned-to**: unassigned

---

## Context

Make the new advisory components importable from the package's public surface
and document the read-only advisor + its reuse of `ComplianceMapper` for SOC2
mapping. Final polish task.

Implements spec §3 Module 4.

---

## Scope

- Export from `parrot_tools/security/__init__.py`:
  `SecurityAdvisoryEngine`, `AdvisoryReport`, `FindingDelta`,
  `AdvisoryRecommendation`, `SOC2AdvisoryToolkit` (add to imports + `__all__`).
- Add a short doc page (`docs/`) describing:
  - What `SecurityAdvisor` is (read-only consumer of the report catalog).
  - Day-over-day drift + SOC2 mapping **via the existing `ComplianceMapper`**.
  - Outputs: persisted `ADVISORY` ReportRef + Jira tickets + email + on-demand.
- A smoke test that the public imports resolve.

**NOT in scope**:
- Re-documenting `SecurityAgent` or the scanners.
- Exporting any non-existent SOC2 catalog symbol.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/security/__init__.py` | MODIFY | Add advisor exports to imports + `__all__` |
| `docs/security-advisor.md` | CREATE | Advisor overview + SOC2-via-ComplianceMapper note |
| `packages/ai-parrot-tools/tests/security/test_advisor_exports.py` | CREATE | Import smoke test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current __init__ pattern (verified: parrot_tools/security/__init__.py)
from .compliance_report_toolkit import ComplianceReportToolkit
from .models import (CloudProvider, ComparisonDelta, ComplianceFramework, ...)
# __all__ is an explicit list — append new names, do not overwrite it.

# New symbols to export (from TASK-1480 / TASK-1481):
from .advisory_engine import (
    SecurityAdvisoryEngine, AdvisoryReport, FindingDelta, AdvisoryRecommendation,
)
from .soc2_advisory import SOC2AdvisoryToolkit
```

### Existing Signatures to Use
```python
# parrot_tools/security/__init__.py — has an explicit __all__ list (verified)
__all__ = [
    "SeverityLevel", "FindingSource", "ComplianceFramework", "CloudProvider",
    "SecurityFinding", "ScanSummary", "ScanResult", "ComparisonDelta",
    "ConsolidatedReport", ...   # append the new advisor names here
]
```

### Does NOT Exist
- ~~`SOC2_CONTROL_CATALOG`, `SOC2Control`, `map_finding_to_controls` (new)~~ — do NOT export;
  the SOC2 catalog is the existing `ComplianceMapper` + `soc2_controls.yaml`.
- ~~`parrot_tools.security.soc2_controls`~~ — module does not exist and must not be created.

---

## Implementation Notes

### Key Constraints
- Append to the existing `__all__`; preserve current exports and ordering style.
- Keep the doc page concise and accurate; emphasize **read-only** and **reuse**.
- The export test must not require AWS/Postgres — import-only.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/security/__init__.py` — export style to match.

---

## Acceptance Criteria

- [ ] `from parrot_tools.security import SOC2AdvisoryToolkit, SecurityAdvisoryEngine, AdvisoryReport` works.
- [ ] New names appear in `parrot_tools.security.__all__`.
- [ ] `docs/security-advisor.md` exists and states read-only + ComplianceMapper reuse.
- [ ] Existing exports are unchanged.
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/security/test_advisor_exports.py -v`
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/security/__init__.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/security/test_advisor_exports.py
def test_advisor_public_exports():
    from parrot_tools.security import (
        SecurityAdvisoryEngine, AdvisoryReport, SOC2AdvisoryToolkit,
    )
    import parrot_tools.security as sec
    for name in ("SecurityAdvisoryEngine", "AdvisoryReport", "SOC2AdvisoryToolkit"):
        assert name in sec.__all__
```

---

## Agent Instructions

1. Read the spec (§3 Module 4) and confirm TASK-1480/1481 are completed.
2. Append exports to `__all__`; write the doc page; add the smoke test.
3. Run pytest + ruff.
4. Move this file to `sdd/tasks/completed/` and set the per-spec index to `done`;
   set `completed_at` on the index header (last task of the feature).
5. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-05
**Notes**: Modified parrot_tools/security/__init__.py to add imports and __all__ entries for SecurityAdvisoryEngine, AdvisoryReport, FindingDelta, AdvisoryRecommendation, SOC2AdvisoryToolkit. Created docs/security-advisor.md documenting the read-only advisor, SOC2-via-ComplianceMapper pipeline, daily advisory flow, materiality rules, data models, and configuration. Created test_advisor_exports.py with 6 smoke tests (all pass). ruff clean. index completed_at set.

**Deviations from spec**: none
