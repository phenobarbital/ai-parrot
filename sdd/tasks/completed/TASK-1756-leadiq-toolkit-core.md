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

**Post-review fix (2026-07-14)**: `code-reviewer` found a blocking bug —
the composed `self.http = HTTPService(base_url=self.base_url, **kwargs)`
never set `accept="application/json"`. `HTTPService.session()` branches
on `self.accept` (not the response's actual `Content-Type`) to decide
whether to parse JSON or return raw text, so every real (non-mocked)
LeadIQ API call would come back as a string and `_process_*_response`
would raise `TypeError` on `result["data"]` — invisible to the unit
suite because it mocks `toolkit.http.session` directly, bypassing that
branch. Fixed by adding `accept="application/json"` to the composed
`HTTPService` constructor call, moved the `_process_*_response` call
inside the existing `try/except` around `_execute_query` in all three
tool methods for consistent tool-scoped error messages, and added a
regression test (`test_composed_http_service_accepts_json` in
`test_leadiq.py`) asserting `toolkit.http.accept == "application/json"`.
See commit `102af3fa0`.

**Post-review cleanup (2026-07-14, commit `26ec43ab7`)**: addressed the
review's non-blocking findings too:
- Added a `_resolve_api_key()` helper so `self._api_key or
  config.get("LEADIQ_API_KEY")` is looked up in exactly one place instead
  of being duplicated across `_build_headers()` and all three `search_*`
  methods.
- The `None` vs `[]` ambiguity flagged above is now surfaced instead of
  silently hidden: `search_employees`/`search_flat` set
  `metadata["ambiguous_empty"] = True` when the ported transform returns
  `None` (structure/no-match ambiguity), while a normal non-empty result
  omits the key entirely. The ported `_process_employee_response`/
  `_process_flat_response` functions themselves were left untouched
  (still verbatim) — only the wrapper's handling of their `None` return
  changed.
- Corrected `sdd/specs/leadiqtool.spec.md` (§1 Goals, §5 AC) — it said
  `HTTPService` was aiohttp-based; it's actually `httpx.AsyncClient`-based
  internally (`parrot/interfaces/http.py:359`). The AC's real intent (no
  direct `requests`/`httpx` import in the new module) is unchanged and
  still satisfied.
- Added 3 more tests (13 total) covering the `ambiguous_empty` flag.
