# TASK-2139: Cost-centre organisation-hierarchy enrichment

**Feature**: FEAT-415 — Workday Interfaces Homologation (flowtask → ai-parrot)
**Spec**: `sdd/specs/workday-interfaces-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec. flowtask's `CostCenterType` is 608
lines; ai-parrot's is 305 — a **+311 line** gap made up of five private
methods that resolve a cost centre's container organisations into a full
hierarchy chain, plus **+120 lines** of matching parser support
(`cost_center_parsers.py`: 405 in flowtask vs 307 here).

Without them, ai-parrot returns bare container ids where flowtask returns a
resolved organisational hierarchy.

---

## Scope

- Port the five private enrichment methods onto `CostCenterType`:
  - `_enrich_with_organizations(...)`
  - `_fetch_org_enrichment(self, include_inactive: bool = True) -> pd.DataFrame`
  - `_resolve_container_orgs(self, container_ids: Set[str]) -> Dict[str, dict]`
  - `_build_hierarchy_chain(self, parent_id: str, cache: dict) -> list`
  - `_fetch_container_org_info(self, organization_id: str) -> dict`
- Port the corresponding parser additions in `cost_center_parsers.py`.
- Wire enrichment into the existing `execute()` flow the way flowtask does.
- Write unit tests covering chain building and the missing-parent path.

**NOT in scope**:
- `handlers/organizations.py` — the `Organization_Type_ID` fix is TASK-2142.
- `models/cost_center.py` beyond what enrichment strictly requires (the
  +12-line model gap is TASK-2143).
- Exposing enrichment as an agent-facing tool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/cost_centers.py` | MODIFY | Add the five enrichment methods; wire into `execute()` |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/cost_center_parsers.py` | MODIFY | Port the +120 lines of parser support |
| `packages/ai-parrot-tools/tests/workday/test_cost_center_enrichment.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/cost_centers.py
import asyncio                                          # line 1 — ALREADY PRESENT, keep
import math                                             # line 2 — ALREADY PRESENT, keep
from typing import List                                 # line 3 — extend with Set/Dict as needed
import pandas as pd                                     # line 4
from .base import WorkdayTypeBase                       # line 6
from ..models.cost_center import CostCenter             # line 7
from ..parsers.cost_center_parsers import parse_cost_center_data  # line 8
```

> **Note**: unlike `locations.py` and `organizations.py`, this file's
> `asyncio` / `math` imports are still in use here. Do NOT remove them, and
> do NOT assume the "ai-parrot removed unused imports" cleanup applies to
> this file — it does not.

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/cost_centers.py
class CostCenterType(WorkdayTypeBase):                                  # line 11
    def _get_default_payload(self) -> dict:                             # line 14
    async def execute(self, **kwargs) -> pd.DataFrame:                  # line 27
    async def _fetch_cost_center_page(self, page_num: int, base_payload: dict) -> List[dict]:  # line 260
```

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py
class WorkdayTypeBase(ABC):                              # line 11
    def __init__(...)                                    # line 21
    def _get_default_payload(self) -> Dict[str, Any]:    # line 42
    async def execute(self, **kwargs) -> Any:            # line 53
    async def _paginate_soap_operation(...)              # line 60   <-- reuse for org fetches
```

### Reference Source (flowtask — READ ONLY)

`../flowtask/flowtask/interfaces/workday/handlers/cost_centers.py` (608 lines)
and `../flowtask/flowtask/interfaces/workday/parsers/cost_center_parsers.py`
(405 lines) hold the originals. Only the import prefix differs
(`flowtask.` → `parrot_tools.`).

### Does NOT Exist

- ~~`CostCenterType._enrich_with_organizations`~~ — to be added by this task
- ~~`CostCenterType._fetch_org_enrichment`~~ — to be added by this task
- ~~`CostCenterType._resolve_container_orgs`~~ — to be added by this task
- ~~`CostCenterType._build_hierarchy_chain`~~ — to be added by this task
- ~~`CostCenterType._fetch_container_org_info`~~ — to be added by this task
- ~~`OrganizationType.get_organization_hierarchy()`~~ — no such method; the closest real ones are `get_organization_by_id` (`organizations.py:127`) and `get_organization_by_wid` (`organizations.py:187`)

---

## Implementation Notes

### Key Constraints
- Async throughout; use `_paginate_soap_operation` (`base.py:60`) rather than hand-rolling pagination.
- The hierarchy walk must terminate on a missing/absent parent link — never recurse unbounded. Use the `cache` dict both to memoise and to detect cycles.
- Do not remove `asyncio`/`math` from this file — they are in use here.
- Google-style docstrings + strict type hints; module logger, never `print`.
- Keep the existing `execute()` return contract (`pd.DataFrame`).

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/organizations.py:127,187` — the org lookups enrichment leans on
- `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py:60` — pagination helper

---

## Acceptance Criteria

- [ ] All five enrichment methods exist on `CostCenterType`
- [ ] Enrichment is wired into `execute()` and the result carries the resolved hierarchy chain
- [ ] A broken/absent parent link does not raise and does not loop forever
- [ ] Parser support ported into `cost_center_parsers.py`
- [ ] `asyncio` and `math` imports remain in `cost_centers.py` (still used)
- [ ] `execute()` still returns a `pd.DataFrame`
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/workday/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/cost_centers.py packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/cost_center_parsers.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/workday/test_cost_center_enrichment.py
import pytest


class TestHierarchyChain:
    async def test_builds_chain_from_container_orgs(self):
        """Container ids resolve into an ordered hierarchy chain."""

    async def test_handles_missing_parent(self):
        """An absent parent link terminates the walk without raising."""

    async def test_cycle_does_not_loop_forever(self):
        """A self-referential/cyclic parent chain terminates."""

    async def test_cache_avoids_refetching_same_org(self):
        """A repeated organization_id is served from cache, not refetched."""


class TestEnrichmentIntegration:
    async def test_execute_returns_dataframe_with_hierarchy(self):
        """execute() still returns a DataFrame, now carrying hierarchy columns."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/workday-interfaces-homologation.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-2139-workday-cost-center-enrichment.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
