---
type: Wiki Overview
title: 'Feature Specification: Workday Composable-Only WSDL Routing (retire legacy
  SOAP path)'
id: doc:sdd-specs-workday-composable-only-wsdl-routing-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'After FEAT-230, `WorkdayToolkit` carries **two coexisting WSDL-routing systems**:'
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Workday Composable-Only WSDL Routing (retire legacy SOAP path)

**Feature ID**: FEAT-233
**Date**: 2026-06-09
**Author**: Juan (raised by Jesus Lara)
**Status**: approved
**Target version**: TBD

> Focused follow-up to **FEAT-230** (Workday Composable Interface + Toolkit
> Homologation). FEAT-230 reduced the in-line `WorkdaySOAPClient` to a "thin shim"
> but did **not** fully retire it: 22 toolkit methods now delegate to the composable
> (which self-routes its WSDL), while **3 payroll methods still use the legacy
> routing**. This spec finishes the migration so the composable is the single
> WSDL-routing source of truth.

---

## 1. Motivation & Business Requirements

### Problem Statement

After FEAT-230, `WorkdayToolkit` carries **two coexisting WSDL-routing systems**:

- **Composable (new)** — 22 methods call `self._get_composable(operation_type)`
  (`tool.py:656`), a lazy per-`operation_type` client cache. The composable
  `WorkdayService` **resolves its own WSDL** from `operation_type` via
  `get_wsdl_path()` (`config.py:86` → `_WSDL_ROUTING` `config.py:57`) and
  authenticates in `start()`.
- **Legacy (old)** — `self.wsdl_paths` (a `{WorkdayService enum → wsdl}` map built
  in `__init__`), `self._clients`, `self.soap_client`, the `WorkdayService(str,
  Enum)`, `METHOD_TO_SERVICE_MAP`, the `WorkdaySOAPClient` class, and
  `_get_client_for_service` / `_get_client_for_method`. This path survives **only
  for 3 payroll methods**: `wd_get_payroll_balances`, `wd_get_payroll_results`,
  `wd_get_company_payment_dates`.

As Jesus observed: now that each composable defines its own WSDL, the toolkit-level
`self.wsdl_paths` no longer makes sense — it is vestigial duplication kept alive
only because the composable has **no payroll handlers yet**.

### Goals

- G1 — Build **3 net-new payroll handlers** in the vendored composable
  (`get_payroll_balances`, `get_payroll_results`, `get_company_payment_dates`)
  against the Workday **Payroll WSDL**, mirroring FEAT-230's read-handler pattern.
- G2 — **Migrate** the 3 payroll toolkit methods to delegate via
  `_get_composable(...)`, returning JSON-serializable `dict`/`list[dict]`, keeping
  their public signatures and input schemas backward-compatible.
- G3 — **Delete the entire legacy routing block** from `tool.py` once nothing uses
  it, leaving the composable as the single WSDL-routing source of truth.
- G4 — No breaking change to the public `wd_*` API (the 3 payroll method
  names/signatures are preserved).

### Non-Goals (explicitly out of scope)

- Adding new payroll *capabilities* beyond the 3 existing methods.
- Changing the 22 already-migrated methods (they work; untouched except for any
  shared `wd_start`/`wd_close` reconciliation).
- Session-derived identity / authorization (that is the Workday-knowledge-agent
  program, not this cleanup).
- Removing the payroll methods entirely (rejected scope option — full migration was
  chosen over dropping payroll).

---

## 2. Architectural Design

### Overview

Finish FEAT-230's migration: give the composable payroll handlers so the 3 payroll
methods can delegate like the other 22, then remove the now-unused legacy routing.
End-state: **every** `wd_*` method goes through `_get_composable(operation_type)`;
WSDL selection lives **only** in the composable's `get_wsdl_path()` /
`_WSDL_ROUTING`; `self.wsdl_paths`, `self._clients`, the `WorkdayService` enum,
`METHOD_TO_SERVICE_MAP`, and `WorkdaySOAPClient` cease to exist.

### Component Diagram
```
BEFORE (post-FEAT-230):
  22 methods ──▶ _get_composable(op) ──▶ WorkdayComposable (self-routes WSDL)   ✅
   3 payroll ──▶ _get_client_for_method ──▶ wsdl_paths[enum] ──▶ WorkdaySOAPClient  ⛔ legacy

AFTER (FEAT-233):
  ALL methods ──▶ _get_composable(op) ──▶ WorkdayComposable.get_wsdl_path(op)
                                            ├─ get_payroll_balances ─┐
                                            ├─ get_payroll_results   ├─▶ WORKDAY_WSDL_PAYROLL
                                            └─ get_company_payment_dates ┘
  (wsdl_paths / _clients / WorkdayService enum / METHOD_TO_SERVICE_MAP / WorkdaySOAPClient: DELETED)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `WorkdayService` composable (`interfaces/workday/service.py`) | extends | register 3 payroll handlers in `_type_handlers` (+ `_OPERATION_MODEL_MAP` if modeled) |
| `WorkdayTypeBase` (`handlers/base.py`) | extends | base for the 3 new read handlers |
| `interfaces/workday/config.py` `_WSDL_ROUTING` | modifies | add `get_payroll_*` → `WORKDAY_WSDL_PAYROLL` |
| `parrot.conf` `WORKDAY_WSDL_PAYROLL` | reads | WSDL path already configured (`conf.py:623`, `WORKDAY_WSDL_PATHS["payroll"]` `conf.py:655`) |
| `WorkdayToolkit` (`workday/tool.py`) | modifies | migrate 3 methods; delete legacy block |

### Data Models
```python
# Reuse / add Pydantic models under interfaces/workday/models/ for payroll results
# (e.g. PayrollBalance, PayrollResult, CompanyPaymentDate) IF a typed return is used;
# otherwise fetch() + DataFrame.to_dict(orient="records") at the tool boundary.
# Existing toolkit input schemas are preserved (see §6):
#   GetPayrollBalancesInput (tool.py:303), GetPayrollResultsInput (tool.py:323),
#   GetCompanyPaymentDatesInput (tool.py:343)
```

### New Public Interfaces
```python
# No NEW public toolkit methods. The 3 payroll methods keep their signatures:
async def wd_get_payroll_balances(self, worker_id: str,
                                  start_date: Optional[str] = None, ...) -> ...   # tool.py:1342
async def wd_get_payroll_results(self, worker_id: str,
                                 start_date: Optional[str] = None, ...) -> ...    # tool.py:1390
async def wd_get_company_payment_dates(self, start_date: str,
                                       end_date: str, ...) -> ...                 # tool.py:1444
# New composable-internal handlers (not agent-facing):
#   handlers/payroll_balances.py / payroll_results.py / company_payment_dates.py
```

---

## 3. Module Breakdown

### Module 1: Payroll handlers in the composable
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/`
  (new: `payroll_balances.py`, `payroll_results.py`, `company_payment_dates.py`)
  + `service.py` + `config.py`
- **Responsibility**: Implement 3 read handlers subclassing `WorkdayTypeBase`
  (reference: existing `time_off_balances.py` / `time_requests.py`), issuing the
  Workday Payroll operations via `self.service.call_operation(...)`. Register them
  in `WorkdayService._type_handlers` (`service.py:218`); add `_WSDL_ROUTING` entries
  (`config.py:57`) `get_payroll_balances`/`get_payroll_results`/
  `get_company_payment_dates` → `WORKDAY_WSDL_PAYROLL`; add `_OPERATION_MODEL_MAP`
  entries (`service.py:90`) if returning typed models.
- **Depends on**: FEAT-230 (merged).

### Module 2: Migrate the 3 payroll toolkit methods
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py`
- **Responsibility**: Replace each payroll method's
  `_get_client_for_method(...)` body with `svc = await
  self._get_composable("get_payroll_...")` → `fetch_models`/`fetch` →
  JSON-serializable return. Preserve signatures + input schemas (`GetPayrollBalancesInput`,
  `GetPayrollResultsInput`, `GetCompanyPaymentDatesInput`).
- **Depends on**: Module 1.

### Module 3: Delete the legacy routing block
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py`
- **Responsibility**: Remove `WorkdaySOAPClient` (`tool.py:413`), `self.wsdl_paths`
  (build `tool.py:517-543`, read `tool.py:609/618`), `self._clients`
  (`tool.py:546`), `self.soap_client` (`tool.py:551`), `_get_client_for_service`
  (`tool.py:585`), `_get_client_for_method` (`tool.py:635`), `WorkdayService(str,
  Enum)` (`tool.py:98`), `METHOD_TO_SERVICE_MAP` (`tool.py:110`). Reconcile
  `wd_start` (`tool.py:565` — drop legacy-client creation) and `wd_close`
  (`tool.py:684` — drop `_clients` teardown, keep `_composables`).
- **Depends on**: Module 2 (nothing may reference the legacy block before deletion).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_payroll_balances_handler` | M1 | handler builds the Payroll op payload + parses ack (mocked `call_operation`) |
| `test_payroll_results_handler` | M1 | idem for results |
| `test_company_payment_dates_handler` | M1 | idem for payment dates |
| `test_payroll_ops_routed_to_payroll_wsdl` | M1 | `get_wsdl_path("get_payroll_*")` → `WORKDAY_WSDL_PAYROLL` |
| `test_payroll_methods_delegate_to_composable` | M2 | each `wd_get_payroll_*` calls `_get_composable`, no legacy client |
| `test_payroll_returns_json_serializable` | M2 | returns dict/list[dict] (`json.dumps` ok); never a DataFrame |
| `test_payroll_signatures_unchanged` | M2 | public signatures + input schemas preserved |
| `test_legacy_symbols_removed` | M3 | `WorkdaySOAPClient`/`WorkdayService` enum/`METHOD_TO_SERVICE_MAP`/`wsdl_paths`/`_clients` no longer exist on the module/instance |

### Integration Tests
| Test | Description |
|---|---|
| `test_all_wd_methods_use_composable` | Instantiate `WorkdayToolkit`, `wd_start()`; assert all `wd_*` (incl. payroll) resolve via composables (mocked zeep) |
| `test_existing_methods_unbroken` | the 22 already-migrated methods still return expected shapes after the legacy block is removed |

### Test Data / Fixtures
```python
@pytest.fixture
def mock_payroll_service(monkeypatch):
    """Patch WorkdayService.call_operation with canned payroll-shaped responses."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] 3 payroll handlers exist in the composable, subclass `WorkdayTypeBase`, and are
      registered in `_type_handlers`.
- [ ] `get_payroll_balances`/`get_payroll_results`/`get_company_payment_dates` route
      to `WORKDAY_WSDL_PAYROLL` via `_WSDL_ROUTING` / `get_wsdl_path`.
- [ ] The 3 `wd_get_payroll_*` methods delegate via `_get_composable` and return
      JSON-serializable dict/list[dict] (no `DataFrame`).
- [ ] The 3 payroll method public signatures + input schemas are unchanged.
- [ ] `WorkdaySOAPClient`, `self.wsdl_paths`, `self._clients`, `self.soap_client`,
      the `WorkdayService(str, Enum)`, `METHOD_TO_SERVICE_MAP`,
      `_get_client_for_service`, `_get_client_for_method` are **removed**
      (`grep` for them in `tool.py` is empty).
- [ ] `wd_start` / `wd_close` operate only on `_composables` (no legacy clients).
- [ ] No other `wd_*` method regressed; existing FEAT-230 tests still pass.
- [ ] All unit tests pass: `pytest packages/ai-parrot-tools/tests/workday -v`.
- [ ] No breaking changes to the existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against the merged `dev`
> source on 2026-06-09.

### Verified Imports
```python
from ..interfaces.workday.service import WorkdayService as WorkdayComposable  # tool.py:75
from ..interfaces.workday.config import WorkdayConfig                          # used in _get_composable
from .base import WorkdayTypeBase           # handlers/base.py:11 (read base for new handlers)
from parrot.conf import WORKDAY_WSDL_PAYROLL # verified: packages/ai-parrot/src/parrot/conf.py:623
# WORKDAY_WSDL_PATHS["payroll"] = WORKDAY_WSDL_PAYROLL  # conf.py:655
```

### Existing Class Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/workday/tool.py  (TO MODIFY/DELETE)
class WorkdayService(str, Enum):                       # line 98   (DELETE — incl. PAYROLL/HUMAN_RESOURCES/ABSENCE_MANAGEMENT)
METHOD_TO_SERVICE_MAP = { ... }                        # line 110  (DELETE)
class GetPayrollBalancesInput(BaseModel): ...          # line 303  (KEEP)
class GetPayrollResultsInput(BaseModel): ...           # line 323  (KEEP)
class GetCompanyPaymentDatesInput(BaseModel): ...      # line 343  (KEEP)
class WorkdaySOAPClient(SOAPClient): ...               # line 413  (DELETE)
class WorkdayToolkit(AbstractToolkit):
    self.wsdl_paths: Dict[WorkdayService, str]         # line 517  (DELETE; read at 609/618)
    self._clients: Dict[WorkdayService, WorkdaySOAPClient]  # line 546  (DELETE)
    self.soap_client: Optional[WorkdaySOAPClient]      # line 551  (DELETE)
    async def wd_start(self) -> str: ...               # line 565  (RECONCILE — drop legacy client at 576)
    async def _get_client_for_service(self, service, ...) -> WorkdaySOAPClient: ...  # line 585  (DELETE)
    async def _get_client_for_method(self, method_name: str) -> WorkdaySOAPClient: ...  # line 635  (DELETE)
    async def _get_composable(self, operation_type: str) -> WorkdayComposable: ...  # line 656  (KEEP — the only path)
    async def wd_close(self) -> None: ...              # line 684  (RECONCILE — drop _clients teardown)
    async def wd_get_payroll_balances(self, worker_id, start_date=None, ...): ...   # line 1342 (MIGRATE)
    async def wd_get_payroll_results(self, worker_id, start_date=None, ...): ...     # line 1390 (MIGRATE)
    async def wd_get_company_payment_dates(self, start_date, end_date, ...): ...     # line 1444 (MIGRATE)

# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py
class WorkdayService(SOAPClient):                      # the composable (note: same name as the tool enum — that enum is being deleted)
    self._type_handlers: dict                          # line 218  (register payroll handlers here)
    _OPERATION_MODEL_MAP: dict[str, type]              # line 90   (add payroll model entries if typed)
    async def call_operation(self, operation, **kwargs) # used by handlers
    async def fetch(self, operation_type, **params)     # line 266
    async def fetch_models(self, operation_type, **params)  # line 291

# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py
_WSDL_ROUTING: dict[str, Any]                          # line 57  (add get_payroll_* -> WORKDAY_WSDL_PAYROLL)
def get_wsdl_path(operation_type) -> Any: ...          # line 86  (returns _WSDL_ROUTING.get(op, WORKDAY_WSDL_PATH))

# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py
class WorkdayTypeBase(ABC):                            # line 11  (read base; reference handler: time_off_balances.py)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PayrollBalancesType` handler | `WorkdayService._type_handlers` | dict registration | `service.py:218` |
| payroll op keys | `WORKDAY_WSDL_PAYROLL` | `_WSDL_ROUTING` entry | `config.py:57` / `conf.py:623` |
| `wd_get_payroll_*` | `WorkdayComposable.fetch_models/fetch` | `self._get_composable(...)` | `tool.py:656` |

### Does NOT Exist (Anti-Hallucination)
- ~~payroll handlers/operations in the composable~~ — **none today** (only `Worker` model has payroll *fields*); must be built (Module 1).
- ~~a `get_payroll_*` entry in `_WSDL_ROUTING`~~ — not present; must be added.
- ~~the composable seeds/routes payroll already~~ — no; `WORKDAY_WSDL_PAYROLL` exists at the conf level but no composable wiring uses it yet.
- ~~deleting `self.wsdl_paths` is safe before migrating payroll~~ — FALSE; the 3 payroll methods read it (`tool.py:609/618`) until Module 2 lands.
- ~~the tool-level `WorkdayService(str, Enum)` is the composable~~ — it is a *different* symbol (a WSDL-category enum, `tool.py:98`) being deleted; the composable is `WorkdayService(SOAPClient)` imported as `WorkdayComposable`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- New handlers subclass `WorkdayTypeBase` (`handlers/base.py:11`) and mirror an
  existing read handler (`handlers/time_off_balances.py`): `async def execute(**kwargs)`
  calling `self.service.call_operation(operation="...", **payload)`.
- DataFrame→JSON at the toolkit boundary: `fetch_models()` + `model.model_dump()`
  preferred, else `fetch()` + `df.to_dict(orient="records")` (reuse
  `WorkdayToolkit._flatten_entries`).
- Order strictly M1 → M2 → M3 (cannot delete legacy until payroll is migrated).

### Known Risks / Gotchas
- **Payroll WSDL operation names/payloads** — confirm exact Workday Payroll
  operation names (e.g. `Get_Payroll_Result_Detail` / payment-date ops) against
  `payroll_v45_2.wsdl` before coding the handlers.
- **`wd_start` coupling** — `wd_start` currently eagerly builds a legacy client
  (`tool.py:576`); ensure removing it doesn't break the documented start behavior
  (it should now only need composables, which are lazy per-op).
- **Name overlap** — the *deleted* `WorkdayService` enum and the *kept* composable
  `WorkdayService` share a name; ensure imports stay aliased (`WorkdayComposable`)
  and the enum's removal doesn't orphan references (`METHOD_TO_SERVICE_MAP` goes too).
- **Backward compat** — keep the 3 payroll method signatures + input schemas exact.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `zeep` | (existing) | SOAP/WSDL async client |
| `pandas` | (existing) | composable `fetch()` DataFrame, converted at boundary |

---

## 8. Open Questions

- [x] Scope of FEAT-233 — *Resolved with Jesus*: full retirement — build payroll
  handlers in the composable, migrate the 3 methods, delete the entire legacy block.
- [x] Is the Payroll WSDL available? — *Resolved*: yes, `WORKDAY_WSDL_PAYROLL`
  (`conf.py:623`, `payroll_v45_2.wsdl`); `WORKDAY_WSDL_PATHS["payroll"]` (`conf.py:655`).
- [ ] Exact Workday Payroll operation names + payload shapes for balances / results /
  company payment dates — *Owner: implementer* — verify against `payroll_v45_2.wsdl`.
- [ ] Typed models vs. DataFrame→dict for payroll returns (add `PayrollBalance`/
  `PayrollResult`/`CompanyPaymentDate` models, or `to_dict`?) — *Owner: implementer*.

---

## Worktree Strategy

- **Default isolation unit: per-spec.** Modules are tightly coupled and ordered
  (M2 depends on M1; M3 depends on M2) and all live in the same two files/packages —
  sequential execution in one worktree avoids merge churn.
- Order: M1 (payroll handlers) → M2 (migrate methods) → M3 (delete legacy).
- Cross-feature dependencies: depends on FEAT-230 (merged). Shares
  `workday/tool.py` + `interfaces/workday/` with any other Workday work — coordinate.
- Worktree branch: `feat-233-workday-composable-only-wsdl-routing`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-09 | Juan | Initial draft — retire legacy SOAP routing, migrate payroll to composable (FEAT-230 follow-up) |
