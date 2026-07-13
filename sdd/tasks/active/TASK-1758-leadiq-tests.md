# TASK-1758: Unit tests for LeadIQToolkit

**Feature**: FEAT-304 — LeadIQ Toolkit for ai-parrot-tools
**Spec**: `sdd/specs/leadiqtool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1756, TASK-1757
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 3 and §4 Test Specification. Verifies the toolkit's
behaviour with a mocked `HTTPService.session` (no live API calls) and confirms
the registry entry resolves.

---

## Scope

- Create `packages/ai-parrot-tools/tests/test_leadiq.py`.
- Mock `HTTPService.session` to return canned GraphQL payloads (as
  `(result, error)` tuples) — no network.
- Cover all rows of Spec §4 Unit Tests (see Acceptance Criteria).

**NOT in scope**: implementation (TASK-1756/1757). Live integration test is
optional and, if added, must be `@pytest.mark`-gated and skipped without
`LEADIQ_API_KEY`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/test_leadiq.py` | CREATE | Unit tests for `LeadIQToolkit` |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-13.

### Verified Imports
```python
import json
from unittest.mock import AsyncMock, patch
import pytest
from parrot_tools.leadiq.tool import LeadIQToolkit, LeadIQSearchInput  # TASK-1756
from parrot_tools import TOOL_REGISTRY                                  # TASK-1757
from parrot.tools.abstract import ToolResult                           # verified: abstract.py:88
```

### Existing Signatures to Use
```python
# ToolResult fields (abstract.py:88-94): success, status, result, error, metadata
# HTTPService.session returns a (result, error) tuple  (http.py:258)
#   -> patch it: session returns ({"data": {...}}, None) on success,
#                (None, "some error") on failure.
# get_tools() yields tools whose .name is prefixed: "leadiq_search_company", etc.
#   (AbstractToolkit.tool_prefix="leadiq", prefix_separator="_")
```

### Canonical mocked payloads (mirror api.leadiq.com response shapes)
```python
# company:  {"data": {"searchCompany": {"totalResults": 1, "hasMore": False,
#            "results": [{"name","domain","industry","country","address",
#              "linkedinId","linkedinUrl","numberOfEmployees","employeeRange",
#              "foundedYear","locationInfo":{...},"naicsCode":{"code","description"},
#              "technologies":[{"name","category"}]}]}}}
# employees:{"data": {"groupedAdvancedSearch": {"companies":[{"company":{...},
#            "people":[{...}]}]}}}
# flat:     {"data": {"flatAdvancedSearch": {"people":[{...,"company":{...}}]}}}
```

### Does NOT Exist
- ~~a synchronous `LeadIQToolkit.run()` returning a DataFrame~~ — tools are async, return `ToolResult`.
- ~~`toolkit.session(...)`~~ — patch `parrot.interfaces.http.HTTPService.session` (composed as `toolkit.http`).

---

## Implementation Notes

### Pattern to Follow
```python
@pytest.mark.asyncio
async def test_search_company_flattens_response(company_payload):
    tk = LeadIQToolkit(api_key="Zm9vOg==")
    with patch.object(tk.http, "session", new=AsyncMock(return_value=(company_payload, None))):
        res = await tk.search_company.__wrapped__(tk, company_name="PetSmart") \
              if hasattr(tk.search_company, "__wrapped__") else await tk.search_company(company_name="PetSmart")
    assert isinstance(res, ToolResult) and res.success
    assert res.result["name"] == "PetSmart"
```
> Note: call the tool method directly on the instance. If `@tool_schema` wraps
> the callable, invoke the underlying coroutine as the toolkit exposes it;
> verify the actual call form against TASK-1756's implementation.

### Key Constraints
- No real network — always patch `session`.
- Use `pytest.mark.asyncio` (project uses `pytest-asyncio`).
- Clear/ set `LEADIQ_API_KEY` via `monkeypatch`/env for the missing-key test.

### References in Codebase
- `packages/ai-parrot-tools/tests/` — existing tool test style (e.g. `test_bingsearch.py`)

---

## Acceptance Criteria

- [ ] `test_toolkit_exposes_three_tools` — `get_tools()` names ==
  `{leadiq_search_company, leadiq_search_employees, leadiq_search_flat}`.
- [ ] `test_headers_use_basic_auth_verbatim` — header is `Basic {key}` (not re-encoded) + `apollo-require-preflight: true`.
- [ ] `test_missing_api_key_returns_error_toolresult` — `ToolResult(success=False, status="error")`.
- [ ] `test_search_company_flattens_response` — company `ToolResult.result` dict has `name`, `domain`, `industry`, `naics_code`, `technologies`.
- [ ] `test_search_employees_returns_person_rows` — `list[dict]`, one per person, company info merged.
- [ ] `test_search_flat_returns_person_rows` — `list[dict]`, one per person.
- [ ] `test_no_results_company` — empty results → `found: False`.
- [ ] `test_registry_entry_resolves` — `TOOL_REGISTRY["leadiq"]` imports `LeadIQToolkit`.
- [ ] All pass: `pytest packages/ai-parrot-tools/tests/test_leadiq.py -v`.
- [ ] `ruff check` clean.

---

## Test Specification

See Acceptance Criteria — each bullet is one test. Build fixtures for the three
payload shapes from the "Canonical mocked payloads" contract above.

---

## Agent Instructions

Standard flow: verify TASK-1756 & TASK-1757 completed → implement tests →
`pytest ... -v` green → `ruff check` → move to `sdd/tasks/completed/` → update
`sdd/tasks/index/leadiqtool.json` → fill note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
