# TASK-1756: Implement LeadIQToolkit core (leadiq/tool.py)

**Feature**: FEAT-304 — LeadIQ Toolkit for ai-parrot-tools
**Spec**: `sdd/specs/leadiqtool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 1. Ports flowtask's LeadIQ GraphQL logic
(`/home/jesuslara/proyectos/flowtask/flowtask/components/LeadIQ.py`) into an
agent-usable `LeadIQToolkit(AbstractToolkit)` inside `ai-parrot-tools`. This is
the bulk of the feature: the toolkit, its input schema, the three GraphQL query
constants, the three response transforms, and the HTTP execution path.

---

## Scope

- Create `LeadIQSearchInput(AbstractToolArgsSchema)` with `company_name: str`
  and `limit: int = 100` (ge=1, le=100).
- Create `LeadIQToolkit(AbstractToolkit)` with `tool_prefix = "leadiq"` and
  `base_url = "https://api.leadiq.com"`.
- `__init__(self, api_key: Optional[str] = None, **kwargs)`:
  `super().__init__(**kwargs)`, store `self._api_key = api_key`, and compose
  `self.http = HTTPService(base_url=self.base_url, **kwargs)`.
- Port the three GraphQL query constants **verbatim** from the source:
  `COMPANY_SEARCH_QUERY`, `EMPLOYEE_SEARCH_QUERY`, `FLAT_SEARCH_QUERY`.
- Port the three transforms **verbatim** (adapting only `self._logger`→
  `self.logger` and dropping `self._counter`): `_process_company_response`,
  `_process_employee_response`, `_process_flat_response`.
- Implement private `_build_headers()` → resolves the API key via
  `self._api_key or config.get("LEADIQ_API_KEY")`; returns
  `{"Authorization": f"Basic {key}", "Content-Type": "application/json",
  "apollo-require-preflight": "true"}`. The key is **already Base64** — inject
  verbatim, do NOT re-encode.
- Implement private `async def _execute_query(self, payload, company_name)`:
  POST via `await self.http.session(url=self.base_url + "/graphql",
  method="post", data=json.dumps(payload), headers=headers)`, unpack
  `(result, error)`, return the raw dict (or None on error).
- Implement the three public `@tool_schema(LeadIQSearchInput)` async tools:
  `search_company`, `search_employees`, `search_flat`. Each builds `variables`
  (as in the source), calls `_execute_query`, runs the matching transform, and
  returns a `ToolResult`.
- On missing API key OR transport error, return
  `ToolResult(success=False, status="error", result=None, error=...)` — never
  raise unhandled.
- On success, return `ToolResult(success=True, status="success", result=<data>,
  metadata={"search_type": ..., "count": ..., "source": "LeadIQ"})`.

**NOT in scope**: the `TOOL_REGISTRY` entry and `leadiq/__init__.py` exports
(TASK-1757); tests (TASK-1758); any change to `CompanyInfoToolkit`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/leadiq/tool.py` | CREATE | `LeadIQToolkit`, `LeadIQSearchInput`, queries, transforms, `_execute_query` |

---

## Codebase Contract (Anti-Hallucination)

> Verified by reading source on 2026-07-13. Use verbatim.

### Verified Imports
```python
import json
from typing import Any, Dict, List, Optional
from navconfig import config                              # verified: fred_api.py:6
from pydantic import Field                                # verified: fred_api.py:7
from parrot.interfaces.http import HTTPService            # verified: fred_api.py:8, http.py:126
from ..abstract import AbstractToolArgsSchema, ToolResult # verified: abstract.py:1-7 (re-export)
from ..toolkit import AbstractToolkit                     # verified: company_info/tool.py:66
from ..decorators import tool_schema                      # verified: company_info/tool.py:67
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractToolArgsSchema(BaseModel): ...              # line 75
class ToolResult(BaseModel):                              # line 88
    success: bool = Field(default=True)                   # line 90
    status: str = Field(default="success")                # line 91
    result: Any = Field(...)                              # line 92 (required)
    error: Optional[str] = Field(default=None)            # line 93
    metadata: Dict[str, Any] = Field(default_factory=dict)# line 94

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                               # line 207
    tool_prefix: Optional[str] = None                     # line 258 (set "leadiq")
    prefix_separator: str = "_"                           # line 261
    def __init__(self, **kwargs): ...                     # line 296 → sets self.logger (line 335)

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema, description=None): ...            # line 37 (sets func._args_schema)

# packages/ai-parrot/src/parrot/interfaces/http.py
class HTTPService(CredentialsInterface, PandasDataframe): # line 126
    async def session(self, url: str, method: str = "get",
        data: dict = None, headers: dict = None,
        use_json: bool = False, ...) -> tuple:            # line 258 → returns (result, error)

# Source to port (flowtask, read-only, different repo):
# /home/jesuslara/proyectos/flowtask/flowtask/components/LeadIQ.py
#   COMPANY_SEARCH_QUERY   lines 56-118
#   EMPLOYEE_SEARCH_QUERY  lines 120-223
#   FLAT_SEARCH_QUERY      lines 225-300
#   _process_company_response  lines 464-535
#   _process_employee_response lines 537-580
#   _process_flat_response     lines 582-617
#   variables for company:   {"input": {"name": company_name}}                       (line 355)
#   variables for employees: {"input": {"companyFilter": {"names": ...}, "limit":N}} (line 387)
#   variables for flat:      {"input": {"companyFilter": {"names": ...}, "limit":N}} (line 412)
```

### Does NOT Exist
- ~~`self.session(...)` on the toolkit~~ — the toolkit does NOT inherit
  `HTTPService`. Use the composed member `self.http.session(...)`.
- ~~`self._logger`, `self._counter`, `self.previous`, `self.input`,
  `self.add_metric`~~ — flowtask `FlowComponent` attributes; not present.
  Use `self.logger` (set by `AbstractToolkit.__init__`).
- ~~returning a `pandas.DataFrame` / `self._result`~~ — tools return `ToolResult`.
- ~~`parrot_tools.leadiq`~~ — created by this task; nothing pre-exists.

---

## Implementation Notes

### Pattern to Follow
```python
# Composition + config + ToolResult — mirror parrot_tools/fred_api.py:57-98
class LeadIQToolkit(AbstractToolkit):
    tool_prefix: str = "leadiq"
    base_url: str = "https://api.leadiq.com"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self._api_key = api_key
        self.http = HTTPService(base_url=self.base_url, **kwargs)

    @tool_schema(LeadIQSearchInput)
    async def search_company(self, company_name: str, **kwargs) -> ToolResult:
        """Search LeadIQ for a company and return structured company information."""
        ...
```
For method structure (one `@tool_schema` async method per capability) follow
`packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py:428+`.

### Key Constraints
- Async throughout; no `requests`/`httpx`.
- Key is already Base64 — inject verbatim into `Basic {key}` (Spec §5 AC-3, §7).
- `session()` returns `(result, error)` — branch on `error` first.
- `use_json=False` + `data=json.dumps(payload)` sends the pre-serialized body.
- Docstrings become the LLM tool descriptions — write them clearly.
- `self.logger` for logging.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/fred_api.py` — HTTP composition, config, ToolResult
- `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py` — toolkit + `@tool_schema` methods

---

## Acceptance Criteria

- [ ] `leadiq/tool.py` created with `LeadIQToolkit` (`tool_prefix="leadiq"`) and `LeadIQSearchInput`.
- [ ] Three tools present: `search_company`, `search_employees`, `search_flat` (each `@tool_schema`).
- [ ] Every tool returns a `ToolResult` (no DataFrame).
- [ ] Auth header is `Basic {LEADIQ_API_KEY}` (verbatim) + `apollo-require-preflight: true`.
- [ ] Missing key → `ToolResult(success=False, status="error", ...)`, no exception.
- [ ] GraphQL POST via `HTTPService.session(...)`; no `requests`/`httpx` imports.
- [ ] `CompanyInfoToolkit.scrape_leadiq` untouched.
- [ ] `ruff check` clean on the new file.

---

## Test Specification

> Full tests are TASK-1758. This task must at minimum import cleanly and
> expose three tools.

```python
from parrot_tools.leadiq.tool import LeadIQToolkit, LeadIQSearchInput

def test_three_tools():
    tk = LeadIQToolkit(api_key="Zm9vOg==")
    names = {t.name for t in tk.get_tools()}
    assert names == {"leadiq_search_company", "leadiq_search_employees", "leadiq_search_flat"}
```

---

## Agent Instructions

Standard flow: verify contract → implement → run `ruff` → move to
`sdd/tasks/completed/` → update `sdd/tasks/index/leadiqtool.json` status → fill
Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet 5)
**Date**: 2026-07-13
**Notes**: Implemented `LeadIQToolkit` and `LeadIQSearchInput` in
`packages/ai-parrot-tools/src/parrot_tools/leadiq/tool.py`, porting the three
GraphQL query constants and the three `_process_*_response` transforms
verbatim from `flowtask/components/LeadIQ.py`, adapting only
`self._logger` → `self.logger` and dropping `self._counter`. Composed
`self.http = HTTPService(base_url=self.base_url, **kwargs)` (no
`HTTPService` inheritance). `_build_headers()` injects `LEADIQ_API_KEY`
verbatim (no re-encoding) with `apollo-require-preflight: true`.
`_execute_query` unpacks `(result, error)` from `self.http.session(...)`.
Each of the three tools checks for a missing API key up front and wraps
`_execute_query`/processing in `try/except` so no unhandled exception can
escape a tool call — every path returns a `ToolResult`. Verified via
`ruff check` (clean) and a manual import/`get_tools()` smoke test
confirming exactly `leadiq_search_company`, `leadiq_search_employees`,
`leadiq_search_flat` are exposed. Full pytest suite deferred to TASK-1758.
**Deviations from spec**: none. One implementation judgment call not
fully specified by the spec: when `_process_employee_response` /
`_process_flat_response` return `None` (flowtask's ported logic conflates
"no companies/people found" with "unexpected response structure" — both
log a warning and return `None`), this toolkit maps that case to
`ToolResult(success=True, result=[], metadata={"count": 0, ...})` rather
than an error, treating it as "no results" rather than failure. This is
not contradicted by any acceptance criterion but is worth flagging for
review.
