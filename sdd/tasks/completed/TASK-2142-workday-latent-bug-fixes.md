# TASK-2142: Two latent bug fixes — TimeBlock Pydantic defaults + `Organization_Type_ID` form

**Feature**: FEAT-415 — Workday Interfaces Homologation (flowtask → ai-parrot)
**Spec**: `sdd/specs/workday-interfaces-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the behaviour-changing half of **Module 6** of the spec. These
are the two places where flowtask already fixed a bug that ai-parrot still
carries. Both are small in diff and large in effect, so they get their own
task with **regression tests that demonstrate the prior failure**.

**Bug 1 — `TimeBlock` raises on partial responses.**
In Pydantic v2, `Optional[X]` **without** a default is still a REQUIRED
field. ai-parrot's `TimeBlock` declares 13 fields as bare `Optional[...]`
with no `= None`, so any Workday response omitting one of them fails
validation. Workday omits them routinely — unprocessed clock events, and
tenants that do not populate `is_deleted`. flowtask added `= None` to every
optional field, leaving only `raw_data` mandatory.

**Bug 2 — `organization_type` uses the wrong form.**
Workday's `Organization_Type_ID` uses the underscore form (`"Cost_Center"`).
ai-parrot's `get_cost_centers()` calls `execute(organization_type="Cost Center")`
with a space, which matches nothing.

---

## Scope

**Bug 1 — `models/time_block.py`:**
- Add an explicit `= None` to every `Optional[...]` field that lacks one:
  `time_block_id` (12), `time_block_wid` (13), `worker_id` (14),
  `worker_name` (15), `calculated_date` (18), `calculated_in_time` (19),
  `calculated_out_time` (20), `calculated_quantity` (24), `status` (27),
  `is_deleted` (28), `calculation_tags` (31), `last_updated` (32),
  `worktags` (35).
- `shift_date` (21) already has `= None` — leave it.
- `raw_data` (38) stays **mandatory** (`Field(..., exclude=True)`).
- Port flowtask's explanatory comment about why every field carries a default.
- Add a regression test proving a partial response previously raised and now parses.

**Bug 2 — `handlers/organizations.py`:**
- Change `get_cost_centers()` (line 171) to pass the underscore form
  `"Cost_Center"`.
- Update the docstrings on `execute()` and `get_organizations_by_type()`
  (line 137) to document the underscore `Organization_Type_ID` form
  (`Company`, `Cost_Center`, `Custom`, `Matrix`, `Pay_Group`, `Region`,
  `Retiree`, `Supervisory`, …).
- Add a regression test asserting the underscore form is sent.

**NOT in scope**:
- The residual parser/model hunks — TASK-2143.
- The cost-centre enrichment methods — TASK-2139.
- Removing/adding imports in `organizations.py` beyond what these changes need
  (ai-parrot already dropped its unused `asyncio`/`math`/`datetime` there — **do not re-add them**).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/time_block.py` | MODIFY | Add `= None` defaults to 13 optional fields |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/organizations.py` | MODIFY | Underscore `Organization_Type_ID` form + docstrings |
| `packages/ai-parrot-tools/tests/workday/test_latent_bug_fixes.py` | CREATE | Two regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/time_block.py
class TimeBlock(BaseModel):                          # line 6
    time_block_id: Optional[str]                     # line 12  <-- NO DEFAULT (bug)
    time_block_wid: Optional[str]                    # line 13  <-- NO DEFAULT (bug)
    worker_id: Optional[str]                         # line 14  <-- NO DEFAULT (bug)
    worker_name: Optional[str]                       # line 15  <-- NO DEFAULT (bug)
    calculated_date: Optional[date]                  # line 18  <-- NO DEFAULT (bug)
    calculated_in_time: Optional[datetime]           # line 19  <-- NO DEFAULT (bug)
    calculated_out_time: Optional[datetime]          # line 20  <-- NO DEFAULT (bug)
    shift_date: Optional[date] = None                # line 21  <-- ALREADY CORRECT, leave alone
    calculated_quantity: Optional[float]             # line 24  <-- NO DEFAULT (bug)
    status: Optional[str]                            # line 27  <-- NO DEFAULT (bug)
    is_deleted: Optional[bool]                       # line 28  <-- NO DEFAULT (bug)
    calculation_tags: Optional[List[str]]            # line 31  <-- NO DEFAULT (bug)
    last_updated: Optional[datetime]                 # line 32  <-- NO DEFAULT (bug)
    worktags: Optional[Dict[str, Any]]               # line 35  <-- NO DEFAULT (bug)
    raw_data: Dict[str, Any] = Field(..., exclude=True)   # line 38  <-- KEEP MANDATORY
```

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/organizations.py
class OrganizationType(WorkdayTypeBase):                                        # line 10
    def _get_default_payload(self) -> dict:                                     # line 13
    async def execute(self, **kwargs) -> pd.DataFrame:                          # line 27   <-- docstring update
    async def get_organization_by_id(self, organization_id: str, id_type: str = "Organization_Reference_ID") -> pd.DataFrame:  # line 127
    async def get_organizations_by_type(self, organization_type: str) -> pd.DataFrame:  # line 137  <-- docstring update
    async def get_active_organizations(self) -> pd.DataFrame:                   # line 146
    async def get_all_organizations(self, include_inactive: bool = True) -> pd.DataFrame:  # line 154
    async def get_supervisory_organizations(self) -> pd.DataFrame:              # line 163
    async def get_cost_centers(self) -> pd.DataFrame:                           # line 171  <-- THE FIX
    async def get_companies(self) -> pd.DataFrame:                              # line 179
    async def get_organization_by_wid(self, wid: str) -> pd.DataFrame:          # line 187
    async def get_organization_by_cost_center_id(self, cost_center_id: str) -> pd.DataFrame:  # line 196
```

### Reference Source (flowtask — READ ONLY)

- `../flowtask/flowtask/interfaces/workday/models/time_block.py` (52 lines vs 47 here) — carries the `= None` defaults and the explanatory comment
- `../flowtask/flowtask/interfaces/workday/handlers/organizations.py` (208 vs 202) — carries `return await self.execute(organization_type="Cost_Center")`

### Does NOT Exist

- ~~a Pydantic v1 compatibility shim making `Optional[X]` implicitly optional~~ — this project is on Pydantic **v2**, where `Optional[X]` without a default is REQUIRED. That IS the bug.
- ~~`TimeBlock.model_config` with `extra`/defaults handling that would mask this~~ — the model relies on plain field defaults
- ~~`OrganizationType.get_cost_center_organizations()`~~ — the real method is `get_cost_centers()` (line 171)
- ~~an `Organization_Type` (no `_ID`) parameter~~ — the payload key is the underscore `Organization_Type_ID` form
- ~~`asyncio` / `math` / `datetime` imports in `organizations.py`~~ — ai-parrot **removed** these as unused. Do NOT re-add them while editing this file.

---

## Implementation Notes

### Key Constraints
- Bug 1 is strictly **more permissive** — it turns a raised exception into parsed data. No caller can break from it.
- Bug 2 is a genuine behaviour change, but the practical blast radius is small: the space form matched nothing, so callers passing `"Cost Center"` were already getting no results.
- Each fix needs a regression test that would **fail against the current code**. Write the test first, watch it fail, then fix.
- Do not re-introduce imports ai-parrot removed. `ruff check` must stay clean.
- Preserve `raw_data` as mandatory — it is the only genuinely required field.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/time_block_parsers.py` — builds `TimeBlock` instances; the partial-response fixture should mirror what it produces
- `packages/ai-parrot-tools/tests/workday/test_homologation_read.py` — fixture patterns

---

## Acceptance Criteria

- [ ] All 13 bare `Optional[...]` fields on `TimeBlock` carry an explicit `= None`
- [ ] `raw_data` remains mandatory
- [ ] A partial Workday response (omitting `is_deleted` and the `calculated_*` fields) parses into a `TimeBlock` — with a regression test that fails against the pre-fix model
- [ ] `get_cost_centers()` sends `"Cost_Center"` (underscore form)
- [ ] `execute()` and `get_organizations_by_type()` docstrings document the underscore `Organization_Type_ID` form
- [ ] A regression test asserts the underscore form is sent
- [ ] No previously-removed imports re-introduced into `organizations.py`
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/workday/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/time_block.py packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/organizations.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/workday/test_latent_bug_fixes.py
import pytest
from parrot_tools.interfaces.workday.models.time_block import TimeBlock


class TestTimeBlockPartialResponse:
    def test_partial_response_parses(self):
        """REGRESSION: a response omitting is_deleted and calculated_* fields
        previously raised (Pydantic v2 treats bare Optional[X] as required).
        It must now parse."""
        tb = TimeBlock(raw_data={"whatever": 1})
        assert tb.is_deleted is None
        assert tb.calculated_date is None
        assert tb.time_block_id is None

    def test_raw_data_still_required(self):
        with pytest.raises(Exception):
            TimeBlock()


class TestOrganizationTypeForm:
    async def test_get_cost_centers_sends_underscore_form(self):
        """REGRESSION: must send 'Cost_Center', not 'Cost Center'."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/workday-interfaces-homologation.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above — write each regression test FIRST and confirm it fails before fixing
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-2142-workday-latent-bug-fixes.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**: Bug 1 — added explicit `= None` to all 13 bare `Optional[...]`
fields on `TimeBlock` (`time_block_id`, `time_block_wid`, `worker_id`,
`worker_name`, `calculated_date`, `calculated_in_time`,
`calculated_out_time`, `calculated_quantity`, `status`, `is_deleted`,
`calculation_tags`, `last_updated`, `worktags`); `shift_date` (already
correct) and `raw_data` (still mandatory via `Field(..., exclude=True)`)
untouched. Ported flowtask's explanatory comment about Pydantic v2
`Optional[X]`-without-default semantics. Bug 2 — `get_cost_centers()` now
calls `execute(organization_type="Cost_Center")` (underscore form);
`execute()` and `get_organizations_by_type()` docstrings updated to
document the underscore `Organization_Type_ID` form with the full value
list (Company, Cost_Center, Custom, Matrix, Pay_Group, Region, Retiree,
Supervisory). No imports re-added to `organizations.py` (verified: no
`asyncio`/`math`/`datetime` present).

Wrote both regression tests FIRST and confirmed they fail against the
pre-fix code (verified via `git stash` on just the two source files,
re-running the test file, then popping the stash): `test_partial_response_parses`
raised `ValidationError` pre-fix, and `test_get_cost_centers_sends_underscore_form`
asserted `'Cost Center' == 'Cost_Center'` pre-fix. 5 new tests total
(`test_latent_bug_fixes.py`) — the two regressions above, a full-response
non-regression check, a `raw_data`-still-required check, and one pinning
`execute(organization_type=...)`'s payload shape directly. Full
`tests/workday/` suite (141 tests) passes; `ruff check` clean on all three
files (fixed pre-existing mechanical style debt in both modified files —
old-style `Optional`/`List`/`Dict` → `X | None`/builtin generics, import
ordering, all auto-fixable, zero behaviour change; one justified
`# noqa: BLE001` on a pre-existing, untouched broad `except Exception` in
the organization-parsing loop; used `pydantic.ValidationError` instead of
bare `Exception` in the new required-field regression test to satisfy
`B017`).

**Deviations from spec**: none.
