# TASK-2143: Residual parser & model hunks (curated sweep)

**Feature**: FEAT-415 — Workday Interfaces Homologation (flowtask → ai-parrot)
**Spec**: `sdd/specs/workday-interfaces-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the sweep half of **Module 6** of the spec — the long tail of
small differences left after the big capability slices
(TASK-2136…TASK-2142) are done.

This is the task where the spec's central discipline matters most: **the
drift is bidirectional**. Some hunks are flowtask fixes ai-parrot needs;
others are ai-parrot cleanups that must NOT be reverted. Every hunk is
judged individually. There is no wholesale copy in this task.

Known ai-parrot-ahead hunks (do NOT revert):
- `locations.py`, `organizations.py` — unused `asyncio`/`math`/`datetime`/`Optional` imports removed
- `locations.py` — `except Exception as e:` → `except Exception:`
- `worker_parsers.py` — duplicate `from typing import ...` / `from ..utils import extract_by_type` blocks removed

Known flowtask-ahead hunks (adopt):
- `parsers/job_requisition_parsers.py` (+23), `parsers/worker_parsers.py` (+7),
  `parsers/time_request_parsers.py` (+3), `parsers/organization_parsers.py` (+3),
  `parsers/location_parsers.py` (+2), `parsers/location_hierarchy_assignments_parsers.py` (+2)
- `models/cost_center.py` (+12), `models/organizations.py` (+6),
  `models/time_request.py` (+2), `models/job_requisition.py` (+2), and 1-line
  hunks in `applicant.py`, `candidate.py`, `custom_punch_field_report.py`,
  `job_posting.py`, `job_posting_site.py`, `location_hierarchy_assignments.py`,
  `time_off_balance.py`
- `handlers/import_time_clock_events.py` (+7), `handlers/time_blocks.py` (+8),
  `handlers/organizations.py` (+10 — beyond the TASK-2142 fix),
  `handlers/time_block_report.py` (+6), `handlers/job_postings.py` (+5),
  `handlers/job_posting_sites.py` (+5), `handlers/job_requisitions.py` (+5),
  `handlers/locations.py` (+5), plus assorted 1-4 line hunks

`models/time_block.py` is bidirectional (+23 / -18) — its **defaults** half
belongs to TASK-2142; anything left over after that fix belongs here.

---

## Scope

- Regenerate the normalised diff (command below) **after** TASK-2136…2142
  have landed, so already-closed gaps drop out.
- Walk every remaining hunk and classify it as:
  - **adopt** — a flowtask fix ai-parrot lacks
  - **reject** — an ai-parrot cleanup or deliberate divergence
  - **skip** — cosmetic (docstring wording, import order) with no functional effect
- Apply the *adopt* hunks.
- Record the classification of every non-trivial hunk in the Completion Note
  so the decision trail survives.
- Add or extend tests wherever an adopted hunk changes parsing behaviour.

**NOT in scope**:
- The two latent bug fixes (TASK-2142) — `time_block.py` defaults and the `Organization_Type_ID` form.
- Any capability already covered by TASK-2136…2141.
- Chasing byte-level parity. The spec's target is **functional** parity;
  docstring and import-ordering differences are accepted and should be
  classified *skip*.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/*.py` | MODIFY | Adopted parser hunks |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/*.py` | MODIFY | Adopted model hunks |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/*.py` | MODIFY | Adopted handler hunks |
| `packages/ai-parrot-tools/tests/workday/test_residual_hunks.py` | CREATE | Tests for behaviour-changing adoptions |

---

## Codebase Contract (Anti-Hallucination)

### The normalisation command (regenerate before starting)

```bash
SCR=$(mktemp -d)
rsync -a --exclude __pycache__ ../flowtask/flowtask/interfaces/workday/ "$SCR/ft/"
rsync -a --exclude __pycache__ packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/ "$SCR/ap/"
find "$SCR/ft" -name '*.py' -exec sed -i 's/\bflowtask\b/PKG/g' {} +
find "$SCR/ap" -name '*.py' -exec sed -i 's/\bparrot_tools\b/PKG/g' {} +
diff -ru "$SCR/ft" "$SCR/ap"
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py
class WorkdayTypeBase(ABC):                              # line 11
    def _get_default_payload(self) -> Dict[str, Any]:    # line 42
    async def execute(self, **kwargs) -> Any:            # line 53
    async def _paginate_soap_operation(...)              # line 60
class WorkdayWriteTypeBase(WorkdayTypeBase):             # line 178
    def build_request(self, **kwargs) -> Dict[str, Any]: # line 212
    def parse_ack(self, raw: Any) -> Any:                # line 227
```

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/__init__.py
# 21 handler exports at lines 1-31, __all__ at 33-62. The FEAT-230/232 entries
# (lines 24-27 / 57-62) are ai-parrot-ONLY — flowtask has no equivalent.
# NEVER "restore" them from flowtask; NEVER let a sweep drop them.
```

### Known ai-parrot-ahead hunks — REJECT these (do not revert)

```python
# handlers/locations.py, handlers/organizations.py — ai-parrot REMOVED these as unused:
#   import asyncio
#   import math
#   from datetime import date, datetime
#   from typing import ..., Optional        (narrowed to `from typing import List`)
# handlers/locations.py — ai-parrot tidied:
#   except Exception as e:   ->   except Exception:
# parsers/worker_parsers.py — ai-parrot removed DUPLICATE import blocks:
#   from decimal import Decimal / from typing import Any, Dict / from ..utils import extract_by_type
```

### Does NOT Exist

- ~~`flowtask/interfaces/workday/handlers/payroll.py`~~ — flowtask has NO payroll handler. Same for `time_off_request.py` and `time_off_eligibility.py`. These are **ai-parrot-only** (FEAT-230/232). Do not go looking for them in flowtask and do not "sync" them away.
- ~~`flowtask/interfaces/workday/models/time_off_eligibility.py`~~ — ai-parrot-only
- ~~`_PROD_WORKDAY_URL`~~ / ~~`tenant="troc"`~~ / ~~`report_owner="jtorres@trocglobal.com"`~~ — flowtask-only vendor constants. **Never adopt.**
- ~~`SOAPClient.__aenter__` / `__aexit__`~~ — ai-parrot's base class lacks them. If a swept docstring contains `async with WorkdayService(...)`, rewrite it to explicit `start()`/`close()`.

---

## Implementation Notes

### Key Constraints
- **Judge every hunk; copy no file wholesale.** A file-level `cp` from flowtask in this task would revert ai-parrot cleanups and is an automatic failure.
- Re-run the normalised diff AFTER the earlier tasks land — do not work from a stale worklist.
- `ruff check` must stay clean; that is the mechanical guard against re-introducing removed imports.
- Cosmetic-only differences are *skip*, not *adopt*. The target is functional parity.
- Record classifications in the Completion Note — that record is the deliverable that stops the next person redoing this analysis.

### References in Codebase
- `sdd/specs/workday-interfaces-homologation.spec.md` §7 "Patterns to Follow" — the normalisation recipe
- `packages/ai-parrot-tools/tests/workday/test_vendor_rebase.py`, `test_legacy_removed.py` — existing guard tests worth extending

---

## Acceptance Criteria

- [ ] The normalised diff was regenerated after TASK-2136…2142 landed
- [ ] Every remaining non-cosmetic hunk is classified adopt / reject / skip, and the classification is recorded in the Completion Note
- [ ] All *adopt* hunks are applied
- [ ] No previously-removed import is re-introduced anywhere (`ruff check` clean)
- [ ] `except Exception:` cleanups are NOT reverted to `except Exception as e:`
- [ ] `grep -rn "troc\|jtorres@trocglobal.com\|_PROD_WORKDAY_URL" packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/` returns nothing
- [ ] All 21 handler exports in `handlers/__init__.py` survive, including the five FEAT-230/232 entries
- [ ] Behaviour-changing adoptions are covered by tests
- [ ] The pre-existing `tests/workday/` suite still passes unchanged
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/workday/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/workday/test_residual_hunks.py
import pytest


class TestAdoptedParserHunks:
    def test_job_requisition_parser_handles_new_fields(self):
        """Covers the +23-line job_requisition_parsers adoption."""

    def test_worker_parser_hunk(self):
        """Covers the +7-line worker_parsers adoption."""


class TestNoRegressions:
    def test_all_handler_exports_present(self):
        """All 21 exports survive, including the five FEAT-230/232 handlers."""
        from parrot_tools.interfaces.workday import handlers
        for name in (
            "RequestTimeOffType", "TimeOffEligibilityType",
            "PayrollBalancesType", "PayrollResultsType", "CompanyPaymentDatesType",
        ):
            assert hasattr(handlers, name)

    def test_no_vendor_strings(self):
        """No troc / jtorres@trocglobal.com / _PROD_WORKDAY_URL anywhere."""

    def test_removed_imports_not_reintroduced(self):
        """locations.py and organizations.py stay free of asyncio/math/datetime."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none formally, but this task is most efficient LAST, after TASK-2136…2142 have closed their gaps
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/workday-interfaces-homologation.json` → `"in-progress"`
5. **Regenerate the normalised diff**, then implement hunk by hunk
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-2143-workday-residual-hunks.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below, including the hunk classification table

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Hunk classification** (file → adopt / reject / skip → why):

| File | Hunk | Decision | Rationale |
|---|---|---|---|
| | | | |

**Deviations from spec**: none | describe if any
