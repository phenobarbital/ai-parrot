---
type: Wiki Overview
title: 'Feature Specification: Workday Composable Interface + Toolkit Homologation'
id: doc:sdd-specs-workday-tooling-composable-interface-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: A mature, SDD-built composable Workday interface already exists in a sibling
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.interfaces
  rel: mentions
- concept: mod:parrot.interfaces.http
  rel: mentions
- concept: mod:parrot.interfaces.soap
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.decorators
  rel: mentions
- concept: mod:parrot_tools.interfaces.workday
  rel: mentions
- concept: mod:parrot_tools.toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Workday Composable Interface + Toolkit Homologation

**Feature ID**: FEAT-230
**Date**: 2026-06-08
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

> Source of record: research-grounded proposal
> `sdd/proposals/workday-tooling-composable-interface.proposal.md`
> (overall confidence: high). Research audit: `sdd/state/FEAT-230/`.

---

## 1. Motivation & Business Requirements

### Problem Statement

A mature, SDD-built composable Workday interface already exists in a sibling
project at `flowtask/interfaces/workday/` (60 files, ~16.6k LOC:
`WorkdayService(SOAPClient)` + `handlers/` + `models/` + `parsers/` +
`config.py`). Meanwhile AI-Parrot's `WorkdayToolkit`
(`parrot_tools/workday/tool.py`, 1775 LOC) builds Workday SOAP envelopes
**in-line, per method** via its own `WorkdaySOAPClient`. This duplicates SOAP
plumbing, drifts from the battle-tested composable, and makes adding new
operations expensive.

This feature (a) **vendors** the composable into ai-parrot-tools, (b)
**rebases** `WorkdayToolkit` so its tools delegate to the composable instead of
hand-built SOAP, and (c) **homologates** an 11-method agent-facing surface so
each method is callable as a tool.

### Goals

- G1 — Vendor the flowtask Workday composable into a new
  `parrot_tools/interfaces/workday/` package, rebased onto the core
  `parrot.interfaces.soap.SOAPClient` and reading config from `parrot.conf`.
- G2 — Refactor `WorkdayToolkit` so each `wd_*` tool delegates to the
  composable (`fetch()` / `fetch_models()` / `call_operation()`), retiring the
  in-line `WorkdaySOAPClient` SOAP construction.
- G3 — Homologate the 11 agent-facing methods so each is an executable tool
  with a JSON-serializable return and a clear LLM-facing docstring.
- G4 — Preserve the existing public toolkit behavior/credentials (no breaking
  change for current `wd_*` callers).

### Non-Goals (explicitly out of scope)

- Session-derived current-user identity. Identity is an **explicit `worker_id`
  parameter** on every `current_user`/`my_` method (resolved in proposal §5).
- Placing the interface under core `parrot.interfaces` — the composable is
  vendored into `parrot_tools/interfaces/workday` per proposal §5, even though
  shared interfaces conventionally live in core.
- Recruiting / Staffing / Financial-Management placeholder methods in
  `METHOD_TO_SERVICE_MAP` (not in the homologation list).
- Pushing any change back to the upstream flowtask repository (read-only source).

---

## 2. Architectural Design

### Overview

A new vendored package `parrot_tools/interfaces/workday/` holds the composable
`WorkdayService`, rebased so it inherits `parrot.interfaces.soap.SOAPClient`
(the toolkit already imports this base) and reads credentials from
`parrot.conf` `WORKDAY_*`. `WorkdayToolkit` keeps its multi-WSDL routing and
lazy client cache but its per-method bodies change from "build SOAP envelope →
`run()` → parse" to "delegate to `WorkdayService.fetch()/call_operation()` →
convert to JSON". The 11 homologated methods become public async methods on the
toolkit (each auto-registered as a tool by `AbstractToolkit.get_tools()`).

**Return-shape decision (resolves proposal §5 open item):** every homologated
tool returns a JSON-serializable `dict`/`list[dict]`. Where the composable has
a model mapping, use `fetch_models()` + `model.model_dump()`; otherwise use
`fetch()` + `DataFrame.to_dict(orient="records")` (mirroring the existing
`WorkdayToolkit._flatten_entries` pattern). Raw `pandas.DataFrame` must never
cross the tool boundary.

**Operation coverage (verified against the source — see §6 "Does NOT Exist"):**
9 of the 11 methods map to **existing read operations** in the composable
(`Get_Workers`, `Get_Time_Off_Plan_Balances`, `Get_Time_Requests`).
`get_today_date_and_day_of_week` is trivial (no SOAP).
**`request_my_time_off` (write) and `get_my_time_off_eligibility` have NO
backing operation in the vendored source** and require net-new handlers built
from the Workday Absence Management WSDL.

### Component Diagram
```
Agent ──calls tool──▶ WorkdayToolkit (parrot_tools/workday/tool.py)
                          │  delegates (no in-line SOAP)
                          ▼
              WorkdayService (parrot_tools/interfaces/workday/service.py)
                          │  fetch / fetch_models / call_operation
                          ├──▶ handlers/* (WorkdayTypeBase.execute)
                          │        └──▶ parsers/*  ──▶ models/* (Pydantic)
                          ▼
              SOAPClient (parrot.interfaces.soap)  ──▶ zeep AsyncClient ──▶ Workday WSDL
              HTTPService (parrot.interfaces.http) ──▶ REST custom reports (Basic auth)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.interfaces.soap.SOAPClient` | rebase target (extends) | `WorkdayService` inherits this instead of `flowtask.interfaces.SOAPClient` |
| `parrot.interfaces.http.HTTPService` | uses | REST custom-report path (Basic auth) |
| `parrot.conf` `WORKDAY_*` | reads | single credential source; vendored `config.py` reads these |
| `parrot_tools.toolkit.AbstractToolkit` | extends (unchanged) | `get_tools()` auto-registers public async methods |
| `parrot_tools.decorators.tool_schema` | decorates | input-schema binding for tool methods |
| `WorkdayToolkit` `METHOD_TO_SERVICE_MAP` | reused | WSDL routing per method (extend for new methods) |

### Data Models
```python
# Reuse vendored Pydantic models (parrot_tools/interfaces/workday/models/*):
#   Worker, TimeOffBalance, TimeRequest, Organization, WorkdayReference, ...
# New input schema for the write op (parrot_tools/workday/tool.py):
class RequestTimeOffInput(BaseModel):
    worker_id: str = Field(..., description="Worker/Employee ID the request is for")
    start_date: str = Field(..., description="Time-off start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Time-off end date (YYYY-MM-DD)")
    time_off_type: str = Field(..., description="Time Off Type reference ID")
    daily_quantity: float = Field(default=8.0, description="Hours per day requested")
    comment: Optional[str] = Field(default=None, description="Optional request comment")
```

### New Public Interfaces
```python
# parrot_tools/workday/tool.py — homologated agent-facing tools (names verbatim).
# Each returns JSON-serializable dict / list[dict]; identity via explicit worker_id.
class WorkdayToolkit(AbstractToolkit):
    async def find_employee_id_by_name(self, name: str) -> list[dict]: ...
    async def get_current_user_info(self, worker_id: str) -> dict: ...
    async def get_current_user_time_off_balance(self, worker_id: str) -> list[dict]: ...
    async def get_current_user_time_off_history(self, worker_id: str) -> list[dict]: ...
    async def get_time_off_balance(self, worker_id: str) -> list[dict]: ...
    async def get_direct_reports(self, worker_id: str) -> list[dict]: ...
    async def get_more_employee_data(self, worker_id: str) -> dict: ...
    async def get_my_time_off_eligibility(self, worker_id: str) -> list[dict]: ...   # NEW op
    async def get_personal_information(self, worker_id: str) -> dict: ...
    async def get_today_date_and_day_of_week(self) -> dict: ...                       # no SOAP
    async def request_my_time_off(self, worker_id: str, start_date: str,
                                  end_date: str, time_off_type: str,
                                  daily_quantity: float = 8.0,
                                  comment: str | None = None) -> dict: ...            # NEW write op
```

---

## 3. Module Breakdown

### Module 1: Vendor composable package
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/` (new:
  `__init__.py`, `service.py`, `config.py`, `handlers/`, `models/`, `parsers/`,
  `utils/`)
- **Responsibility**: Copy the flowtask composable verbatim, then rebase:
  (a) `WorkdayService(SOAPClient)` inherits `parrot.interfaces.soap.SOAPClient`;
  (b) `config.py` reads `parrot.conf` `WORKDAY_*` instead of `flowtask.conf`;
  (c) update all intra-package imports `flowtask.interfaces.workday.*` →
  `parrot_tools.interfaces.workday.*` and drop `flowtask.interfaces.SOAPClient`.
- **Depends on**: `parrot.interfaces.soap.SOAPClient`, `parrot.conf`, `zeep`, `pandas`.

### Module 2: Refactor WorkdayToolkit to delegate
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py`
- **Responsibility**: Replace each `wd_*` method's in-line SOAP body with a
  delegation to the **vendored composable** `WorkdayService` instance (built per
  service/WSDL via the existing routing). Retire `WorkdaySOAPClient`'s
  SOAP-building helpers (or reduce to a thin shim). Add a JSON-conversion
  boundary (`fetch_models` + `model_dump`, else `to_dict`). Keep
  constructor/credentials/`wd_start` behavior backward-compatible.
- **⚠️ NAME COLLISION (blocking).** `tool.py` already defines its own
  `class WorkdayService(str, Enum)` (verified at `tool.py:99` — a WSDL-category
  enum: `HUMAN_RESOURCES`/`ABSENCE_MANAGEMENT`, consumed by
  `METHOD_TO_SERVICE_MAP` at `tool.py:113`). The vendored composable class is
  ALSO named `WorkdayService(SOAPClient)`. Importing it into `tool.py` shadows
  the enum and silently breaks `METHOD_TO_SERVICE_MAP`. **Resolution: import the
  composable under an alias** —
  `from ..interfaces.workday import WorkdayService as WorkdayComposable` — and
  leave the existing enum and `METHOD_TO_SERVICE_MAP` untouched. (Renaming the
  enum is the higher-churn alternative; prefer the alias.)
- **Depends on**: Module 1.

### Module 3: Read-path homologation methods (9 methods)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py`
- **Responsibility**: Add the read/utility methods listed in §2 as public async
  tools, each delegating to existing composable operations:
  `find_employee_id_by_name`/`get_current_user_info`/`get_more_employee_data`/
  `get_personal_information`/`get_direct_reports` → `Get_Workers`;
  `get_time_off_balance`/`get_current_user_time_off_balance` →
  `Get_Time_Off_Plan_Balances`; `get_current_user_time_off_history` →
  `Get_Time_Requests`; `get_today_date_and_day_of_week` → local datetime (no SOAP).
  Add `@tool_schema` input models and `METHOD_TO_SERVICE_MAP` entries.
- **Depends on**: Module 2.

### Module 4: `request_my_time_off` write handler (NEW operation)
- **Path**: `parrot_tools/interfaces/workday/handlers/time_off_request.py` (new) +
  `parrot_tools/workday/tool.py`
- **Responsibility**: Implement a new write handler issuing the Workday Absence
  Management write op (e.g. `Request_Time_Off` / `Enter_Time_Off`) plus the
  toolkit `request_my_time_off` tool and `RequestTimeOffInput`. Guard with a
  dry-run/confirm flag; target the implementation tenant first.
- **Subclass the existing write base — do NOT hand-roll.** The composable
  already ships `WorkdayWriteTypeBase` (verified at `handlers/base.py:178`),
  whose `execute()` template drives a retry loop and delegates to three abstract
  hooks the new handler MUST implement: `_operation_name()`, `build_request()`,
  `parse_ack()`. Use the **FEAT-027 write handlers as reference**:
  `handlers/put_time_clock_events.py`, `handlers/import_time_clock_events.py`,
  `handlers/import_reported_time_blocks.py` (all single-call write ops via
  `self.service.call_operation(operation=...)`).
- **Register the handler (REQUIRED — else `fetch()` can't reach it).** Add the
  new operation key to the eager `_type_handlers` registry in
  `WorkdayService.__init__` (verified at `service.py:218`, mirroring the FEAT-027
  entries at `service.py:240-242`). Optionally expose a public service wrapper
  (mirroring `put_time_clock_events` at `service.py:364`) and call it from the
  tool. If the write returns a typed ack model, register it in
  `_OPERATION_MODEL_MAP` (`service.py:90`).
- **WSDL routing.** The op lives on the Absence Management WSDL; add its
  `operation_type` → `WORKDAY_WSDL_ABSENCE_MANAGEMENT` entry to `_WSDL_MAP`
  (verified at `config.py:54`, alongside `get_time_off_balances` at
  `config.py:69`).
- **Depends on**: Module 1, Module 2.

### Module 5: `get_my_time_off_eligibility` handler (NEW operation)
- **Path**: `parrot_tools/interfaces/workday/handlers/time_off_eligibility.py` (new) +
  `parrot_tools/workday/tool.py`
- **Responsibility**: Implement an eligibility handler (Workday op returning the
  time-off plans/types the worker may request) since the source has no
  eligibility operation, plus the `get_my_time_off_eligibility` tool. This is a
  **read** op, so subclass the paginated `WorkdayTypeBase`
  (`handlers/base.py:11`) and follow a read handler such as
  `handlers/time_off_balances.py` as reference.
- **Register the handler (REQUIRED).** Same as Module 4: add the new
  `operation_type` to `_type_handlers` (`service.py:218`), add its
  `_WSDL_MAP` entry (`config.py:54`, Absence Management WSDL), and — since it
  returns typed rows — register a model in `_OPERATION_MODEL_MAP`
  (`service.py:90`) so `fetch_models()` does not silently return `[]`.
- **Depends on**: Module 1, Module 2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_workdayservice_rebased_soapclient` | M1 | `WorkdayService` is a `parrot.interfaces.soap.SOAPClient` subclass; no `flowtask` import resolves |
| `test_config_reads_parrot_conf` | M1 | vendored config resolves `WORKDAY_*` from `parrot.conf` |
| `test_toolkit_delegates_to_service` | M2 | a `wd_*` method calls `WorkdayService.fetch/call_operation` (mocked) — no in-line envelope build |
| `test_tool_returns_json_serializable` | M2/M3 | every homologated tool returns dict/list[dict] (`json.dumps` succeeds); never a DataFrame |
| `test_get_tools_exposes_11_methods` | M3 | `get_tools()` includes all 11 method names |
| `test_find_employee_id_by_name` | M3 | name → worker id list (mocked `Get_Workers`) |
| `test_get_today_date_and_day_of_week` | M3 | returns date + weekday, no SOAP call |
| `test_request_my_time_off_builds_write_payload` | M4 | builds the write op payload; honors dry-run guard (no real submit) |
| `test_get_my_time_off_eligibility` | M5 | returns eligible time-off types (mocked) |

### Integration Tests
| Test | Description |
|---|---|
| `test_homologation_all_methods_callable` | Instantiate `WorkdayToolkit`, `wd_start()`, assert each of the 11 tools is invocable (mocked SOAP/zeep) end-to-end |
| `test_existing_wd_methods_unbroken` | Existing `wd_get_worker` / `wd_get_time_off_balance` still return expected shapes after refactor |

### Test Data / Fixtures
```python
@pytest.fixture
def mock_workday_service(monkeypatch):
    """Patch WorkdayService.call_operation/fetch with canned zeep-shaped responses."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `parrot_tools/interfaces/workday/` exists; `WorkdayService` imports and
      subclasses `parrot.interfaces.soap.SOAPClient`; **no** `flowtask.*` import
      remains (`grep -r "flowtask" parrot_tools/interfaces/workday` is empty).
- [ ] Vendored `config.py` resolves credentials from `parrot.conf` `WORKDAY_*`.
- [ ] `WorkdayToolkit` `wd_*` methods delegate to `WorkdayService`; the in-line
      `WorkdaySOAPClient` SOAP-building helpers are removed or reduced to a shim.
- [ ] No raw `pandas.DataFrame` is returned by any tool; all returns are
      JSON-serializable (`json.dumps(result)` succeeds).
- [ ] All 11 homologated methods are present, are public async methods, and
      appear in `WorkdayToolkit().get_tools()` with non-empty docstrings.
- [ ] `request_my_time_off` issues a Workday write op (verified via mocked
      `call_operation`) and is guarded by a dry-run/confirm flag.
- [ ] `get_my_time_off_eligibility` returns eligible time-off types.
- [ ] Existing `wd_*` public API is unchanged (no breaking signature changes).
- [ ] All unit tests pass: `pytest packages/ai-parrot-tools/tests/workday -v`.
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified by reading the actual
> source on 2026-06-08. Implementation agents MUST use these verbatim.

### Verified Imports
```python
# Core SOAP/HTTP bases (live in the CORE ai-parrot package):
from parrot.interfaces.soap import SOAPClient          # verified: packages/ai-parrot/src/parrot/interfaces/soap.py:50
from parrot.interfaces.http import HTTPService         # verified: packages/ai-parrot/src/parrot/interfaces/http.py:126

# Toolkit base + decorator (parrot_tools re-exports from core):
from parrot_tools.toolkit import AbstractToolkit       # re-export: parrot_tools/toolkit.py:2 -> parrot.tools.toolkit
from parrot_tools.decorators import tool_schema        # re-export: parrot_tools/decorators.py:2 -> parrot.tools.decorators
# (within parrot_tools/workday/tool.py the relative forms are: from ..toolkit import AbstractToolkit; from ..decorators import tool_schema)

# Config (already present in CORE conf):
from parrot.conf import (                              # verified: packages/ai-parrot/src/parrot/conf.py:595-608
    WORKDAY_DEFAULT_TENANT, WORKDAY_CLIENT_ID, WORKDAY_CLIENT_SECRET,
    WORKDAY_TOKEN_URL, WORKDAY_WSDL_PATH, WORKDAY_REFRESH_TOKEN,
    WORKDAY_WSDL_PATHS, WORKDAY_REPORT_USERNAME, WORKDAY_REPORT_PASSWORD,
    WORKDAY_REPORT_OWNER, WORKDAY_URL,
)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/interfaces/soap.py
class SOAPClient(ABC):                                                  # line 50
    def __init__(self, *, credentials: dict, httpx_client=None,        # line 88
                 redis_url=None, redis_key="soap:access_token",
                 timeout: int = 30, **kwargs): ...                     # validates client_id/client_secret/token_url/wsdl_path/refresh_token
    async def start(self) -> None: ...                                 # line 149
    async def _get_bearer_token(self) -> str: ...                      # line 171
    def get_client(self) -> ZeepAsyncClient: ...                       # line 221
    def bind_service(self) -> Any: ...                                 # line 231
    async def run(self, operation: str, **kwargs) -> Any: ...          # line 237
    async def close(self) -> None: ...                                 # line 250

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                            # line 191
    def get_tools(self, ...) -> list: ...                              # line 337  (iterates dir(self), skips '_', keeps coroutine fns)
    def get_tools_sync(self, ...): ...                                 # line 447

# packages/ai-parrot-tools/src/parrot_tools/workday/tool.py  (TO BE REFACTORED)
class WorkdaySOAPClient(SOAPClient):                                   # line 350  (in-line SOAP builders — retire)
    def _build_worker_reference(self, worker_id, id_type="Employee_ID"): ...   # line 368
    def _build_request_criteria(self, **filters): ...                  # line 388
    def _parse_worker_response(self, response): ...                    # line 413
class WorkdayToolkit(AbstractToolkit):                                 # line 472
    def __init__(self, tenant_name=None, credentials=None,             # line 492
                 wsdl_paths=None, redis_url=None,
                 redis_key="workday:access_token", timeout=30, **kwargs): ...
    async def wd_start(self) -> str: ...                               # line 600
    async def wd_get_worker(self, ...): ...                            # line 708  @tool_schema(GetWorkerInput)
    async def wd_search_workers_by_name(self, ...): ...                # line 1294
    async def wd_get_workers_by_manager(self, ...): ...                # line 1343  (analog for get_direct_reports)
    async def wd_get_time_off_balance(self, ...): ...                  # line 1034  @tool_schema(GetTimeOffBalanceInput) (analog for get_time_off_balance)
    METHOD_TO_SERVICE_MAP: dict                                        # line 111   (extend with new method names)

# SOURCE composable to vendor (flowtask/interfaces/workday/service.py)
class WorkdayService(SOAPClient):                                      # line 111  (rebase base -> parrot.interfaces.soap.SOAPClient)
    async def call_operation(self, operation: str, **kwargs) -> Any: ...   # line 251
    async def fetch(self, operation_type: str, **params) -> pd.DataFrame: ... # line 266
    async def fetch_models(self, operation_type: str, **params) -> list: ...  # line 291
    async def get_custom_report(self, ...): ...                        # line 330
    async def start(self, **_kwargs) -> None: ...                      # line 451
    async def close(self) -> None: ...                                 # line 455
# handler bases: handlers/base.py
class WorkdayTypeBase(ABC):                                            # line 11  (read; paginated execute)
    async def execute(self, **kwargs) -> Any: ...                     # line 53  (uses self.service.call_operation)
class WorkdayWriteTypeBase(WorkdayTypeBase):                          # line 178 (single-call write base)
    def _operation_name(self) -> str: ...                             # line 202 (override: SOAP op name)
    def build_request(self, **kwargs) -> dict: ...                    # line 212 (override: payload)
    def parse_ack(self, raw) -> Any: ...                              # line 227 (override: ack -> rows)
    async def execute(self, **kwargs) -> Any: ...                     # line 243 (template: build->call->parse, with retry)

# service registry + routing (extend for new ops)
_OPERATION_MODEL_MAP: dict[str, type]   # service.py:90  (operation_type -> Pydantic model; fetch_models returns [] if absent)
WorkdayService._type_handlers: dict     # service.py:218 (operation_type -> handler instance; FEAT-027 writes at 240-242)
_WSDL_MAP: dict                         # config.py:54   (operation_type -> WSDL; WORKDAY_WSDL_ABSENCE_MANAGEMENT at config.py:69)

# EXISTING write handlers to use as reference (FEAT-027 — single-call writes):
#   handlers/put_time_clock_events.py  ("Put_Time_Clock_Events")
#   handlers/import_time_clock_events.py  ("Import_Time_Clock_Events")
#   handlers/import_reported_time_blocks.py  ("Import_Reported_Time_Blocks")
# plus public service wrappers: service.put_time_clock_events (service.py:364), import_* (393/415)
```

### Naming collision (Anti-Hallucination)
- `parrot_tools/workday/tool.py:99` defines `class WorkdayService(str, Enum)`
  (WSDL category enum, used by `METHOD_TO_SERVICE_MAP` at `tool.py:113`). The
  **vendored composable** `WorkdayService(SOAPClient)` shares this name. In
  `tool.py`, import the composable as
  `from ..interfaces.workday import WorkdayService as WorkdayComposable`; do NOT
  rename the existing enum.

### Operation → method mapping (verified in source handlers)
| Homologated tool | Composable operation | Source handler | Status |
|---|---|---|---|
| `find_employee_id_by_name` | `Get_Workers` (name criteria) | handlers/workers.py | exists |
| `get_current_user_info` | `Get_Workers` | handlers/workers.py | exists |
| `get_more_employee_data` | `Get_Workers` (extended response groups) | handlers/workers.py | exists |
| `get_personal_information` | `Get_Workers` (`Include_Personal_Information: True`, workers.py:74) | handlers/workers.py | exists |
| `get_direct_reports` | `Get_Workers` (manager filter) | handlers/workers.py | exists |
| `get_time_off_balance` | `Get_Time_Off_Plan_Balances` | handlers/time_off_balances.py:13 | exists |
| `get_current_user_time_off_balance` | `Get_Time_Off_Plan_Balances` | handlers/time_off_balances.py:13 | exists |
| `get_current_user_time_off_history` | `Get_Time_Requests` | handlers/time_requests.py:12 | exists |
| `get_today_date_and_day_of_week` | — (local `datetime`) | — | trivial |
| `get_my_time_off_eligibility` | **NONE** | — | **must build (Module 5)** |

…(truncated)…
