---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: LeadIQ Toolkit for ai-parrot-tools

**Feature ID**: FEAT-304
**Date**: 2026-07-13
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

> **Prior exploration**: [`sdd/proposals/leadiqtool.proposal.md`](../proposals/leadiqtool.proposal.md)
> (research-grounded, `overall_confidence: high`, all open questions resolved).
> Research audit: [`sdd/state/FEAT-304/`](../state/FEAT-304/).

---

## 1. Motivation & Business Requirements

### Problem Statement

flowtask ships a `LeadIQ` ETL component
(`/home/jesuslara/proyectos/flowtask/flowtask/components/LeadIQ.py`) that
queries the **LeadIQ GraphQL API** for company and employee data. AI-Parrot
agents have no first-class way to pull authenticated, structured company
information from LeadIQ — the only existing path,
`CompanyInfoToolkit.scrape_leadiq`, is Google-CSE + Selenium HTML **scraping**
of the public leadiq.com page (brittle, no API key, unstructured). We want an
agent tool in `ai-parrot-tools` that calls the official LeadIQ API and returns
structured results the LLM can consume directly.

### Goals

- Port flowtask's LeadIQ GraphQL logic into `ai-parrot-tools` as an
  agent-usable toolkit.
- Support the three LeadIQ search types: `company`, `employees`, `flat`.
- Return structured `ToolResult` payloads (no pandas DataFrame).
- Reuse the in-repo async `HTTPService` (internally `httpx.AsyncClient`-based)
  — no direct `requests`/`httpx` imports in the new module.
- Register the toolkit in `TOOL_REGISTRY` for lazy discovery.

### Non-Goals (explicitly out of scope)

- Do **not** modify or remove `CompanyInfoToolkit.scrape_leadiq` — the
  scraping variant remains as a complementary capability.
- No pandas DataFrame return and no flowtask `FlowComponent` coupling
  (`self.previous`, `self.input`, DataFrame-column batch input are dropped).
- No batch DataFrame-column input plumbing — one `company_name` per call; the
  agent loops if it needs several.
- A single-`AbstractTool`-with-`search_type`-arg design was considered and
  **rejected** in the proposal (U1) in favour of a toolkit with three
  discrete, individually-described tools.

---

## 2. Architectural Design

### Overview

Create a new module `parrot_tools/leadiq/` exposing a
`LeadIQToolkit(AbstractToolkit)` with `tool_prefix = "leadiq"`. It exposes
three `@tool_schema`-decorated async methods — one per LeadIQ search type —
each of which:

1. Resolves `LEADIQ_API_KEY` via `navconfig` `config.get("LEADIQ_API_KEY")`.
   The key is **already Base64-encoded** (U3) and is injected verbatim as
   `Authorization: Basic {LEADIQ_API_KEY}`, together with
   `Content-Type: application/json` and `apollo-require-preflight: true`.
2. Builds the GraphQL payload from the ported query constant + `variables`.
3. POSTs to `https://api.leadiq.com/graphql` via a composed `HTTPService`
   member (`await self.http.session(url=..., method="post",
   data=json.dumps(payload), headers=...)`, unpacking `(result, error)`).
4. Flattens the response using the ported `_process_*_response` transforms.
5. Returns a `ToolResult` (`success`, `status`, `result`, `error`, `metadata`).

The three GraphQL query strings and the three `_process_*_response`
transforms are ported **verbatim** from the flowtask source; only the
transport, config, and return envelope change.

### Component Diagram
```
Agent ──→ LeadIQToolkit.search_company ─┐
          LeadIQToolkit.search_employees ├─→ HTTPService.session (POST graphql) ──→ api.leadiq.com
          LeadIQToolkit.search_flat ─────┘            │
                                                       └─→ _process_*_response ──→ ToolResult
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` (`parrot.tools.toolkit`) | extends | base class; public async methods → tools |
| `tool_schema` (`parrot.tools.decorators`) | uses | attaches per-method input schema |
| `HTTPService` (`parrot.interfaces.http`) | composes | async GraphQL POST transport |
| `ToolResult` (`parrot.tools.abstract`) | returns | structured result envelope |
| `config` (`navconfig`) | uses | reads `LEADIQ_API_KEY` |
| `TOOL_REGISTRY` (`parrot_tools.__init__`) | registers | `"leadiq"` → dotted path |
| `ToolCache` (`parrot_tools.cache`) | uses *(optional)* | response caching, FRED pattern |

### Data Models
```python
# parrot_tools/leadiq/tool.py
class LeadIQSearchInput(AbstractToolArgsSchema):
    company_name: str = Field(..., description="Company name to search for on LeadIQ")
    limit: int = Field(100, ge=1, le=100, description="Max people to return (employees/flat searches)")

# Result shapes returned inside ToolResult.result:
#  - search_company    -> dict   (flattened single company; see _process_company_response)
#  - search_employees  -> list[dict]  (one row per person, company info merged)
#  - search_flat       -> list[dict]  (one row per person, company info merged)
```

### New Public Interfaces
```python
# parrot_tools/leadiq/tool.py
class LeadIQToolkit(AbstractToolkit):
    tool_prefix: str = "leadiq"
    base_url: str = "https://api.leadiq.com"

    def __init__(self, api_key: Optional[str] = None, **kwargs): ...

    @tool_schema(LeadIQSearchInput)
    async def search_company(self, company_name: str, **kwargs) -> ToolResult:
        """Search LeadIQ for a company and return structured company information."""

    @tool_schema(LeadIQSearchInput)
    async def search_employees(self, company_name: str, limit: int = 100, **kwargs) -> ToolResult:
        """Search LeadIQ for employees grouped under a company."""

    @tool_schema(LeadIQSearchInput)
    async def search_flat(self, company_name: str, limit: int = 100, **kwargs) -> ToolResult:
        """Flat search LeadIQ for people at a company (one record per person)."""
```

---

## 3. Module Breakdown

### Module 1: LeadIQ toolkit core
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/leadiq/tool.py`
- **Responsibility**: `LeadIQToolkit`, `LeadIQSearchInput`, the three GraphQL
  query constants (ported verbatim), the three `_process_*_response`
  transforms (ported verbatim), a private `_execute_query` that POSTs via
  `HTTPService` and returns the raw dict, and API-key/header resolution.
- **Depends on**: `AbstractToolkit`, `tool_schema`, `HTTPService`,
  `ToolResult`, `AbstractToolArgsSchema`, `navconfig.config`.

### Module 2: Package wiring
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/leadiq/__init__.py`
  and `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
- **Responsibility**: `leadiq/__init__.py` exports `LeadIQToolkit`
  (+ `LeadIQSearchInput`); add manual `TOOL_REGISTRY` entry
  `"leadiq": "parrot_tools.leadiq.tool.LeadIQToolkit"` (generator preserves
  manual entries — F002).
- **Depends on**: Module 1.

### Module 3: Tests
- **Path**: `packages/ai-parrot-tools/tests/test_leadiq.py`
- **Responsibility**: unit tests with a mocked `HTTPService.session` covering
  each search type, header/auth construction, missing-key error, and the
  registry entry resolving.
- **Depends on**: Modules 1 & 2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_toolkit_exposes_three_tools` | 1 | `get_tools()` yields `leadiq_search_company`, `leadiq_search_employees`, `leadiq_search_flat` |
| `test_headers_use_basic_auth_verbatim` | 1 | Auth header is `Basic {LEADIQ_API_KEY}` (key injected verbatim, not re-encoded) + `apollo-require-preflight: true` |
| `test_missing_api_key_returns_error_toolresult` | 1 | No `LEADIQ_API_KEY` → `ToolResult(success=False, status="error", ...)`, no exception |
| `test_search_company_flattens_response` | 1 | mocked `session` company payload → `ToolResult.result` dict with `name`, `domain`, `industry`, `naics_code`, `technologies` |
| `test_search_employees_returns_person_rows` | 1 | mocked grouped payload → `list[dict]`, one per person, company info merged |
| `test_search_flat_returns_person_rows` | 1 | mocked flat payload → `list[dict]`, one per person |
| `test_no_results_company` | 1 | empty `results` → `ToolResult` with `found: False` |
| `test_registry_entry_resolves` | 2 | `TOOL_REGISTRY["leadiq"]` imports `LeadIQToolkit` |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_company_search` | *(optional, marked; skipped without live `LEADIQ_API_KEY`)* real company search returns a populated `ToolResult` |

### Test Data / Fixtures
```python
@pytest.fixture
def company_payload():
    """Minimal SearchCompany GraphQL response mirroring api.leadiq.com."""
    return {"data": {"searchCompany": {"totalResults": 1, "hasMore": False,
        "results": [{"name": "PetSmart", "domain": "petsmart.com", "industry": "Retail",
                     "country": "US", "address": "...", "linkedinId": "...", "linkedinUrl": "...",
                     "numberOfEmployees": 50000, "employeeRange": "10001+", "foundedYear": 1986,
                     "locationInfo": {...}, "naicsCode": {"code": "453910", "description": "Pet Stores"},
                     "technologies": [...]}]}}}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `LeadIQToolkit(AbstractToolkit)` exists at
  `packages/ai-parrot-tools/src/parrot_tools/leadiq/tool.py` with
  `tool_prefix = "leadiq"` and exposes exactly three tools:
  `leadiq_search_company`, `leadiq_search_employees`, `leadiq_search_flat`.
- [ ] Every tool returns a `ToolResult` (never a pandas DataFrame). *(U2)*
- [ ] The `Authorization` header is `Basic {LEADIQ_API_KEY}` with the env value
  injected **verbatim** (already Base64-encoded — the tool does NOT re-encode),
  plus `Content-Type: application/json` and `apollo-require-preflight: true`. *(U3)*
- [ ] `LEADIQ_API_KEY` is read via `navconfig` `config.get("LEADIQ_API_KEY")`;
  a missing key yields `ToolResult(success=False, status="error", ...)` — not
  an unhandled exception.
- [ ] GraphQL calls go through `HTTPService.session(...)` (internally
  `httpx.AsyncClient`-based — verified in `parrot/interfaces/http.py:359`,
  not aiohttp); the new `leadiq/tool.py` module itself has no direct
  `requests`/`httpx` imports.
- [ ] The three GraphQL query constants and the three `_process_*_response`
  transforms match the flowtask source semantics.
- [ ] `TOOL_REGISTRY` contains `"leadiq":
  "parrot_tools.leadiq.tool.LeadIQToolkit"`, and it imports without error.
- [ ] `CompanyInfoToolkit.scrape_leadiq` is unchanged.
- [ ] All unit tests pass: `pytest packages/ai-parrot-tools/tests/test_leadiq.py -v`.
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All references below verified by
> reading source on 2026-07-13.

### Verified Imports
```python
# In parrot_tools/leadiq/tool.py — mirror parrot_tools/fred_api.py:1-10 (verified)
import json
from typing import Any, Dict, List, Optional, Type
from navconfig import config                              # verified: fred_api.py:6
from pydantic import Field                                # verified: fred_api.py:7
from parrot.interfaces.http import HTTPService            # verified: fred_api.py:8, http.py:126
from ..abstract import AbstractTool, AbstractToolArgsSchema, ToolResult  # verified: abstract.py:1-7 re-export
from ..toolkit import AbstractToolkit                     # verified: company_info/tool.py:66
from ..decorators import tool_schema                      # verified: company_info/tool.py:67
# optional caching:
from ..cache import ToolCache, DEFAULT_TOOL_CACHE_TTL     # verified: fred_api.py:10
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractToolArgsSchema(BaseModel): ...              # line 75
class ToolResult(BaseModel):                              # line 88
    success: bool = Field(default=True)                   # line 90
    status: str = Field(default="success")                # line 91
    result: Any = Field(...)                              # line 92
    error: Optional[str] = Field(default=None)            # line 93
    metadata: Dict[str, Any] = Field(default_factory=dict)# line 94

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                               # line 207
    tool_prefix: Optional[str] = None                     # line 258
    prefix_separator: str = "_"                           # line 261
    def __init__(self, **kwargs): ...                     # line 296
    #   sets self.logger = logging.getLogger(self.__class__.__name__)  # line 335
    def get_tools(self, ...): ...                         # line 406

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):  # line 37
    #   sets func._args_schema = schema

# packages/ai-parrot/src/parrot/interfaces/http.py
class HTTPService(CredentialsInterface, PandasDataframe):  # line 126
    async def session(                                     # line 258
        self, url: str, method: str = "get", data: dict = None,
        headers: dict = None, use_json: bool = False, ...,
    ) -> tuple:   # returns (result, error)

# packages/ai-parrot-tools/src/parrot_tools/fred_api.py  (composition template)
class FredAPITool(AbstractTool):                           # line 40
    def __init__(self, cache_ttl=..., **kwargs):           # line 57
        self.http_service = HTTPService(base_url=self.BASE_URL, **kwargs)  # line 59
    async def _execute(...) -> ToolResult:                 # line 62
        api_key = api_key or config.get("FRED_API_KEY")    # line 88
```

### Source to Port (flowtask — different repo, read-only reference)
```python
# /home/jesuslara/proyectos/flowtask/flowtask/components/LeadIQ.py  (verified)
COMPANY_SEARCH_QUERY   # lines 56-118   query SearchCompany($input: SearchCompanyInput!)
EMPLOYEE_SEARCH_QUERY  # lines 120-223  query GroupedAdvancedSearch($input: GroupedSearchInput!)
FLAT_SEARCH_QUERY      # lines 225-300  query FlatAdvancedSearch($input: FlatSearchInput!)
_process_company_response   # lines 464-535  -> single flattened dict
_process_employee_response  # lines 537-580  -> list[dict] (person rows)
_process_flat_response      # lines 582-617  -> list[dict] (person rows)
# headers: Authorization: Basic {LEADIQ_API_KEY}, apollo-require-preflight: true  # lines 333-337
# endpoint: POST https://api.leadiq.com/graphql                                   # lines 52, 438
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `LeadIQToolkit.__init__` | `AbstractToolkit.__init__` | `super().__init__(**kwargs)` | `toolkit.py:296` |
| `LeadIQToolkit._execute_query` | `HTTPService.session()` | `await self.http.session(...)` → `(result, error)` | `http.py:258` |
| `search_*` methods | `tool_schema(LeadIQSearchInput)` | decorator | `decorators.py:37` |
| `search_*` returns | `ToolResult(...)` | constructor | `abstract.py:88` |
| registry | `parrot_tools/__init__.py::TOOL_REGISTRY` | manual dict entry | `__init__.py:12-25` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_tools.leadiq`~~ — being created by this feature; nothing exists yet.
- ~~an existing LeadIQ **API** client in ai-parrot-tools~~ — only
  `CompanyInfoToolkit.scrape_leadiq` (scraping) exists (F006, verified via
  `grep -rn "leadiq" src/`).
- ~~`self.session(...)` on the toolkit~~ — the toolkit does NOT inherit
  `HTTPService` (unlike the flowtask component); use a **composed**
  `self.http = HTTPService(...)` member (FRED pattern).
- ~~pandas / `self._result` DataFrame return~~ — not used by tools.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Composition over inheritance for HTTP**: hold `self.http =
  HTTPService(base_url=self.base_url, **kwargs)` (FRED `fred_api.py:59`),
  do **not** subclass `HTTPService`.
- One `@tool_schema(LeadIQSearchInput)` async method per search type;
  docstrings become the LLM-facing tool descriptions (`company_info/tool.py`).
- `ToolResult` for every return; put `search_type`, `count`, and
  `source="LeadIQ"` in `metadata`.
- Port the GraphQL query strings and `_process_*_response` bodies verbatim;
  replace only `self.session`/`self._logger`/`self._counter` plumbing.
- Async-first; `self.logger` (set by `AbstractToolkit.__init__`) for logging.

### Known Risks / Gotchas
- **Auth encoding**: `LEADIQ_API_KEY` is **already Base64** — inject verbatim.
  Re-encoding it would break auth. *(U3 resolved)*
- **Large employee/flat payloads**: `employees`/`flat` can return many person
  rows; honour `limit` (default 100, matching source) and consider trimming
  fields to keep the `ToolResult` within LLM context.
- **`session` returns `(result, error)`**: always unpack and branch on `error`
  before processing, mapping errors to `ToolResult(success=False, ...)`.
- **`use_json=False` + `data=json.dumps(payload)`**: send the pre-serialized
  JSON string as the body (matches flowtask), with explicit
  `Content-Type: application/json`.
- **Registry regeneration**: if `scripts/generate_tool_registry.py` is re-run,
  confirm the manual `"leadiq"` entry survives (it should — F002).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| *(none new)* | — | Uses in-repo `HTTPService`; no new third-party dependency or `pyproject` extra required. |

---

## 8. Open Questions

> All questions from the proposal were resolved before this spec.

### Resolved (carried forward from proposal)
- [x] **Tool shape: toolkit vs single tool?** — *Resolved in proposal (U1)*:
  **Toolkit** — `LeadIQToolkit` with three `@tool_schema` tools. Reflected in
  §2 Overview, §3 Module 1, §5 AC-1.
- [x] **Return contract?** — *Resolved in proposal (U2)*: **structured
  `ToolResult`**, no DataFrame. Reflected in §2 Data Models, §5 AC-2, §7.
- [x] **Auth encoding of `LEADIQ_API_KEY`?** — *Resolved in proposal (U3)*:
  value is **already Base64**; inject verbatim as `Basic {LEADIQ_API_KEY}`.
  Reflected in §2 Overview, §5 AC-3, §7 Known Risks.

### Unresolved (defer to implementation)
- [ ] Whether to enable `ToolCache` (FRED-style) for LeadIQ responses, and at
  what TTL — *Owner: implementer*. Non-blocking; may be added without design change.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (sequential tasks in one worktree).
- Modules are small and linearly dependent (Module 1 → Module 2 → Module 3);
  no parallelism benefit. Run tasks sequentially via `/sdd-start`.
- **Cross-feature dependencies**: none. Base branch `dev`.

Suggested worktree after task decomposition:
```bash
git worktree add -b feat-304-leadiqtool \
  .claude/worktrees/feat-304-leadiqtool HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-13 | Jesus Lara | Initial draft from `leadiqtool.proposal.md` (FEAT-304, all open questions resolved) |
