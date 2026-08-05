---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Workday Interfaces Homologation (flowtask → ai-parrot)

**Feature ID**: FEAT-415
**Date**: 2026-08-05
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.2.0 (`ai-parrot-tools`, currently 0.1.85)

**Source brainstorm**: `sdd/proposals/workday-interfaces-homologation.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

`flowtask/interfaces/workday/` (sibling repo at `../flowtask`) and
`packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/` are two
copies of the same code lineage that have drifted apart independently.
After normalising the import prefix (`flowtask.` → `parrot_tools.`),
**48 files still differ**.

The drift is **bidirectional**, which is what makes a naive copy dangerous.

**flowtask has capabilities ai-parrot lacks:**

| Gap | Size | What it is |
|---|---|---|
| `rest.py` → `WorkdayRestClient` | 217 lines, absent | REST `/ccx/api` client. The WSDL services have **no** operation to read raw time clock events; the REST API does, echoing back the client-assigned `Time_Clock_Event_ID` and the effective `timeEntryCode`. Without it, post-punch verification is impossible. |
| `handlers/cost_centers.py` | +311 lines | Organisation-hierarchy enrichment |
| `parsers/cost_center_parsers.py` | +120 lines | Matching parser surface |
| `config.py` env selector | +71 lines | `WORKDAY_ENV` prod/sandbox switch, `WORKDAY_*_IMPL` credential set, URL alignment validator |
| `service.py` endpoint rewrite | +64 lines | `bind_service()` override + `_point_endpoint_at_configured_host()` |
| `models/clock_event.py` | +52 lines | `delete`, `location`/`cost_center` overrides, GPS, `override_rate` |
| `handlers/custom_report.py` | +81 lines | `_parse_json_to_entries` — JSON custom-report path |
| `handlers/put_time_clock_events.py` | +14 lines | Emission of the new clock-event fields |
| `parsers/job_requisition_parsers.py` | +23 lines | Parser refinements |

**ai-parrot has capabilities flowtask lacks** (must NOT be regressed):
FEAT-230 (`request_time_off`, `get_time_off_eligibility`), FEAT-232
(payroll reads), a deliberate **vendor-neutrality** refactor (flowtask
hardcodes `tenant="troc"` and `report_owner="jtorres@trocglobal.com"`;
ai-parrot made them `None` + conf-resolved), and code hygiene (unused
imports removed, `except Exception as e:` tidied).

**Two latent bugs in ai-parrot that flowtask already fixed:**

1. `models/time_block.py` — in Pydantic v2, `Optional[X]` **without** a
   default is still a REQUIRED field, so ai-parrot's model raises on the
   partial Workday responses that occur routinely (unprocessed clock
   events, tenants that do not populate `is_deleted`).
2. `handlers/organizations.py` — `organization_type` must use the
   underscore `Organization_Type_ID` form (`"Cost_Center"`); ai-parrot
   sends `"Cost Center"` with a space, which matches nothing.

**Who is affected**: agents and toolkits built on `WorkdayToolkit` /
`WorkdayService` in ai-parrot. Today they cannot target a sandbox tenant,
cannot verify a punch after writing it, cannot delete or override a clock
event, and get an exception instead of data on partial time-block responses.

**Highest-severity consequence**: the shipped WSDLs hardcode the production
SOAP endpoint. flowtask's `bind_service()` override is what repoints it.
ai-parrot has no equivalent, so **a sandbox-configured client silently
writes to production**.

### Goals

- Close every flowtask → ai-parrot capability gap listed above, so the
  ai-parrot Workday interface is functionally complete.
- Preserve, without exception, ai-parrot's exclusive features (FEAT-230,
  FEAT-232) and its vendor-neutrality and code-hygiene improvements.
- Adopt the two latent bug fixes with regression tests that demonstrate
  the prior failure.
- Keep sandbox/production targeting explicit and fail-safe: never let a
  sandbox-intended write reach the production tenant.
- Comply with project rules: `aiohttp` (never `httpx`), async-first,
  Pydantic models, Google-style docstrings, strict type hints.

### Non-Goals (explicitly out of scope)

- **Modifying the `flowtask` repository.** This is a one-way port; flowtask
  is not touched.
- **Back-porting ai-parrot's payroll / absence-management features to
  flowtask.** (Rejected in brainstorm — see `proposals/workday-interfaces-homologation.brainstorm.md`, "Direction" question.)
- **Exposing new agent-facing tools.** `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py`
  (the `WorkdayToolkit`, 1740 lines) is untouched — interface layer only.
- **Extracting a shared `workday-core` distribution consumed by both
  repos.** (Brainstorm Option C — deferred; it requires reconciling both
  copies first, which is exactly what this feature does. Tracked in §8.)
- **Byte-level parity.** Residual docstring, import-ordering and style
  differences are accepted and expected; the target is functional parity.
- **Wholesale file replacement.** (Brainstorm Option B — rejected because
  `config.py` and `service.py` are precisely where ai-parrot's divergence
  is deliberate and valuable.)

---

## 2. Architectural Design

### Overview

A **curated per-hunk port**, sliced into six capability groups plus a
packaging/tooling slice. Every difference between the two trees is judged
individually and adopted or rejected on its merits — nothing is copied
wholesale, because the files with the largest gaps (`config.py`,
`service.py`) are also the files carrying ai-parrot's most valuable
divergence.

Configuration is **additive and vendor-neutral**: every new `WorkdayConfig`
field defaults to `None` and resolves through `parrot.conf`. flowtask's
hardcoded `tenant="troc"`, `report_owner="jtorres@trocglobal.com"` and
`_PROD_WORKDAY_URL` constant are **not** carried over.

`rest.py` is **reimplemented on `aiohttp`**, not copied — flowtask's version
is `httpx`-based, and `CLAUDE.md` forbids `httpx`. Its public surface is
preserved verbatim so the port stays faithful where it matters.

Sandbox targeting is **fail-loud**: selecting `env="sandbox"` without the
`WORKDAY_*_IMPL` credentials raises at config resolution rather than
silently falling back to production credentials.

### Component Diagram

```
parrot.conf (+5 WORKDAY_* settings)
       │
       ▼
WorkdayConfig  ──(env / resolved_is_sandbox)──┐
  │  resolved_* credential properties          │
  │  _align_workday_url_to_env validator       │
  ├──────────────────┬─────────────────────────┘
  ▼                  ▼
WorkdayService     WorkdayRestClient  (NEW — rest.py, aiohttp)
  (SOAPClient)       find_worker / get_time_clock_events
  │                  find_time_clock_event
  ├── bind_service() ──→ _point_endpoint_at_configured_host()
  │                        (rewrites Zeep endpoint host; prod = no-op)
  │
  └── _handlers dict
        ├── CostCenterType        (+5 enrichment methods)
        ├── CustomReportType      (+_parse_json_to_entries)
        ├── PutTimeClockEventsType(+delete/location/cost_center/override_rate)
        ├── OrganizationType      (Organization_Type_ID underscore fix)
        ├── RequestTimeOffType     ─┐ FEAT-230 — PRESERVE
        ├── TimeOffEligibilityType ─┘
        ├── PayrollBalancesType    ─┐
        ├── PayrollResultsType      ├ FEAT-232 — PRESERVE
        └── CompanyPaymentDatesType─┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.interfaces.soap.SOAPClient` | extends (hook) | `bind_service()` at `soap.py:231` is the exact hook the endpoint rewrite overrides — verified compatible |
| `WorkdayConfig` (`config.py:112`) | modifies | New `env` field + env-aware credential resolution; existing `resolved_*` properties keep their contract |
| `_WSDL_ROUTING` (`config.py:58`) | extends | Extended, not restructured; existing routing keys keep their targets |
| `WorkdayService._handlers` (`service.py:~245`) | modifies | FEAT-230/232 registrations at lines 250-256 **must survive** |
| `WorkdayTypeBase` / `WorkdayWriteTypeBase` (`handlers/base.py:11,178`) | uses | All ported handlers already inherit these |
| `parrot.conf` (`conf.py:637-698`) | extends | Five settings appended after the existing `WORKDAY_*` block |
| `packages/ai-parrot-tools/pyproject.toml` | modifies | New `workday` extra declaring `zeep`, `pandas`, `aiohttp` |
| `parrot_tools/workday/tool.py` | unaffected | Explicitly out of scope |
| `sdd/specs/workday-tooling-composable-interface.spec.md` | contract | Composable-delegation contract must keep holding |
| `sdd/specs/workday-composable-only-wsdl-routing.spec.md` | contract | WSDL routing keys keep their current targets |
| `flowtask` repository | unaffected | One-way port |

### Data Models

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py
class WorkdayConfig(BaseModel):
    # ... existing fields unchanged (client_id ... timeout) ...
    env: str | None = None          # NEW — None falls back to WORKDAY_ENV (default "prod")

    # NEW helpers
    @property
    def resolved_env(self) -> str: ...
    @property
    def resolved_is_sandbox(self) -> bool: ...

    # EXISTING resolved_* credential properties become environment-aware:
    # sandbox selects WORKDAY_*_IMPL, else WORKDAY_*.
    # MUST raise when sandbox is selected and the _IMPL value is unset.

    @model_validator(mode="after")
    def _align_workday_url_to_env(self) -> "WorkdayConfig": ...


# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/clock_event.py
class ClockEvent(BaseModel):
    # ... existing fields unchanged ...
    delete: bool = False                   # NEW — soft-delete via Put_Time_Clock_Events
    location: Optional[str] = None         # NEW — organisational location OVERRIDE (not geo)
    cost_center: Optional[str] = None      # NEW — cost-centre override
    override_rate: Optional[float] = Field(default=None, ge=0)   # NEW — presence-based
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)     # NEW — NEVER sent
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)  # NEW — NEVER sent

    @model_validator(mode="after")
    def _delete_requires_event_id(self) -> "ClockEvent": ...


# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/time_block.py
class TimeBlock(BaseModel):
    # BUG FIX: every Optional[...] field gains an explicit "= None".
    # Pydantic v2 treats Optional[X] WITHOUT a default as REQUIRED.
    # Only raw_data stays mandatory.
```

### New Public Interfaces

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/rest.py  (NEW MODULE)
class WorkdayRestClient:
    """Async client for Workday's /ccx/api REST endpoints (aiohttp-based)."""

    def __init__(
        self,
        *,
        config: WorkdayConfig | None = None,
        timeout: int = 30,
        time_tracking_version: str = "v5",
    ) -> None: ...

    @property
    def base_url(self) -> str: ...
    def set_token(self, token: str, expires_in: int = 300) -> None: ...
    async def get_token(self) -> str: ...
    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict: ...
    async def find_worker(self, search: str, *, limit: int = 20) -> list[dict]: ...
    async def get_time_clock_events(self, worker_wid: str, **criteria: Any) -> list[dict]: ...
    async def find_time_clock_event(self, worker_wid: str, reference_id: str) -> dict | None: ...
    async def close(self) -> None: ...   # explicit lifecycle — see §7 gotchas
```

---

## 3. Module Breakdown

### Module 1: Environment selector & SOAP endpoint routing
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py`,
  `.../workday/service.py`, `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**: Add `WorkdayConfig.env`, `resolved_env`,
  `resolved_is_sandbox`; make credential resolution environment-aware with
  a fail-loud check for missing `_IMPL` values; add the
  `_align_workday_url_to_env` validator; add five `WORKDAY_*` settings to
  `parrot.conf`; add the `bind_service()` override and
  `_point_endpoint_at_configured_host()` on `WorkdayService`.
  **Must not** re-introduce `tenant="troc"`, `report_owner="jtorres@trocglobal.com"`
  or a hardcoded prod-URL default. **Must not** disturb the FEAT-230/232
  handler registrations.
- **Depends on**: existing `WorkdayConfig`, `SOAPClient.bind_service()`

### Module 2: `WorkdayRestClient` on aiohttp
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/rest.py` (NEW)
- **Responsibility**: Reimplement flowtask's `WorkdayRestClient` on
  `aiohttp`, preserving the public surface. OAuth refresh-token grant with
  an in-memory token cache (no Redis). Shares `WorkdayConfig`, so the
  environment selector applies to REST too. Explicit session lifecycle.
- **Depends on**: Module 1 (needs `resolved_is_sandbox` / env-aware host)

### Module 3: Cost-centre organisation enrichment
- **Path**: `.../workday/handlers/cost_centers.py`, `.../workday/parsers/cost_center_parsers.py`
- **Responsibility**: Port the five private enrichment methods
  (`_enrich_with_organizations`, `_fetch_org_enrichment`,
  `_resolve_container_orgs`, `_build_hierarchy_chain`,
  `_fetch_container_org_info`) and their parser support, adapted to
  ai-parrot's cleaned import surface.
- **Depends on**: none (independent of Modules 1–2)

### Module 4: Clock-event write surface
- **Path**: `.../workday/models/clock_event.py`, `.../workday/handlers/put_time_clock_events.py`
- **Responsibility**: Add the new `ClockEvent` fields and the
  `delete → time_clock_event_id` validator; emit `Delete_Time_Clock_Event`,
  `Location`, `Cost_Center` and `Override_Rate` in the SOAP payload.
  **GPS `latitude`/`longitude` are validated and carried but NEVER
  serialised** — the Time Tracking WSDL has no geo field through v46.1.
- **Depends on**: none

### Module 5: Custom-report JSON path
- **Path**: `.../workday/handlers/custom_report.py`
- **Responsibility**: Port `_parse_json_to_entries` and wire it into the
  existing custom-report flow.
- **Depends on**: none

### Module 6: Model & parser fixes (behaviour changes)
- **Path**: `.../workday/models/time_block.py`, `.../workday/handlers/organizations.py`,
  `.../workday/parsers/job_requisition_parsers.py`, `.../workday/parsers/worker_parsers.py`,
  `.../workday/parsers/time_request_parsers.py`, and residual small hunks
- **Responsibility**: Apply the two latent bug fixes plus the residual
  parser refinements, judging each hunk against ai-parrot's cleanups (do
  not re-introduce removed unused imports or revert `except Exception:`).
- **Depends on**: none

### Module 7: Packaging & manual smoke script
- **Path**: `packages/ai-parrot-tools/pyproject.toml`, `examples/` (new smoke script)
- **Responsibility**: Declare a `workday` extra (`zeep`, `pandas`,
  `aiohttp`) following the existing extras pattern; add a manual smoke
  script the maintainer can run against the implementation tenant on
  demand. **The smoke script must never run in CI.**
- **Depends on**: Modules 1–5 (exercises the ported surface)

---

## 4. Test Specification

All automated tests are **mock-based** — there is no live Workday tenant in
CI. Follow the existing fixture pattern in
`packages/ai-parrot-tools/tests/workday/test_homologation_read.py`.

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_config_env_defaults_to_prod` | 1 | `env=None` resolves to `"prod"`; non-sandbox credentials selected |
| `test_config_sandbox_selects_impl_credentials` | 1 | `env="sandbox"` resolves `WORKDAY_*_IMPL` values |
| `test_config_sandbox_missing_impl_raises` | 1 | Sandbox selected with unset `_IMPL` credentials **raises** — never falls back to production |
| `test_config_no_vendor_defaults` | 1 | `WorkdayConfig()` does not produce `"troc"` or `jtorres@trocglobal.com`; tenant/report_owner/workday_url resolve via conf |
| `test_bind_service_rewrites_host_for_sandbox` | 1 | Zeep endpoint host swapped to the configured host; WSDL path preserved verbatim |
| `test_bind_service_noop_for_production` | 1 | Matching host → endpoint untouched |
| `test_bind_service_survives_malformed_url` | 1 | Bad/empty `workday_url` or missing `_binding_options` → original endpoint intact, warning logged, no raise |
| `test_feat_230_232_handlers_still_registered` | 1 | `request_time_off`, `get_time_off_eligibility`, `get_payroll_balances`, `get_payroll_results`, `get_company_payment_dates` all present in `_handlers` after the port |
| `test_rest_client_token_cached_until_expiry` | 2 | `get_token` reuses the cached bearer; refreshes shortly before expiry |
| `test_rest_client_uses_aiohttp_not_httpx` | 2 | Module imports `aiohttp`; asserts `httpx` is not imported |
| `test_rest_find_worker_returns_wid_rows` | 2 | Parses `id` / `descriptor` rows |
| `test_rest_time_clock_events_requires_wid` | 2 | Employee_ID input surfaces an actionable error, not an opaque 400 |
| `test_rest_client_closes_session` | 2 | No leaked `aiohttp` session after `close()` |
| `test_cost_center_enrichment_builds_hierarchy_chain` | 3 | Container orgs resolved into a hierarchy chain |
| `test_cost_center_enrichment_handles_missing_parent` | 3 | Broken/absent parent link does not raise |
| `test_clock_event_delete_requires_event_id` | 4 | `delete=True` without `time_clock_event_id` raises with an explicit message |
| `test_clock_event_gps_never_serialised` | 4 | `latitude`/`longitude` set → absent from the SOAP payload |
| `test_clock_event_overrides_emitted` | 4 | `location`, `cost_center`, `override_rate` present in payload when set; omitted when `None` |
| `test_clock_event_override_rate_zero_is_sent` | 4 | Presence-based: `0` is emitted, `None` is omitted |
| `test_custom_report_parses_json_entries` | 5 | `_parse_json_to_entries` returns entries from a JSON body |
| `test_time_block_accepts_partial_response` | 6 | **Regression** — a partial Workday response that previously raised now parses (Pydantic v2 optional-default fix) |
| `test_organization_type_uses_underscore_form` | 6 | **Regression** — `"Cost_Center"` sent, not `"Cost Center"` |

### Integration Tests

| Test | Description |
|---|---|
| `test_service_end_to_end_mocked_sandbox` | Config → env resolution → endpoint rewrite → handler dispatch, fully mocked, asserting the sandbox host is used |
| `test_no_import_regressions` | The whole `parrot_tools.interfaces.workday` package imports cleanly after the port |
| `test_existing_workday_suite_still_passes` | The pre-existing 1106-line `tests/workday/` suite passes unchanged |

### Test Data / Fixtures

```python
# Reuse the established pattern from tests/workday/test_homologation_read.py
@pytest.fixture()
def toolkit():
    from parrot_tools.workday.tool import WorkdayToolkit
    tk = WorkdayToolkit.__new__(WorkdayToolkit)
    tk.credentials = {...}
    ...
    return tk

# New fixtures required by this feature
@pytest.fixture()
def sandbox_config():
    """WorkdayConfig(env="sandbox") with WORKDAY_*_IMPL settings patched in."""

@pytest.fixture()
def partial_time_block_payload():
    """A Workday response omitting is_deleted and the calculated_* fields —
    the shape that currently raises on TimeBlock validation."""

@pytest.fixture()
def mock_aiohttp_session():
    """aiohttp session double for WorkdayRestClient tests (no network)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

**Functional parity**
- [ ] `parrot_tools/interfaces/workday/rest.py` exists and exposes `WorkdayRestClient` with the full public surface listed in §2.
- [ ] `WorkdayConfig` supports `env`, `resolved_env` and `resolved_is_sandbox`.
- [ ] `WorkdayService.bind_service()` rewrites the SOAP endpoint host to match `workday_url`, preserving the WSDL path.
- [ ] `CostCenterType` carries all five organisation-enrichment methods.
- [ ] `ClockEvent` carries `delete`, `location`, `cost_center`, `override_rate`, `latitude`, `longitude` and the delete validator.
- [ ] `CustomReportType._parse_json_to_entries` exists and is wired in.
- [ ] Every flowtask → ai-parrot gap in §1 is closed or explicitly recorded as intentionally skipped.

**No regressions (the core risk of this feature)**
- [ ] FEAT-230 handlers (`request_time_off`, `get_time_off_eligibility`) remain registered and tested.
- [ ] FEAT-232 payroll handlers (`get_payroll_balances`, `get_payroll_results`, `get_company_payment_dates`) remain registered and tested.
- [ ] No occurrence of `"troc"` or `jtorres@trocglobal.com` anywhere in `parrot_tools/interfaces/workday/`.
- [ ] No hardcoded production-URL default re-introduced into `WorkdayConfig`.
- [ ] Unused imports removed by ai-parrot (`asyncio`, `math`, `datetime`, `Optional` where dropped) are NOT re-introduced.
- [ ] `except Exception:` cleanups are NOT reverted to `except Exception as e:`.
- [ ] The pre-existing `tests/workday/` suite passes unchanged.

**Bug fixes**
- [ ] `TimeBlock` parses a partial Workday response that previously raised, with a regression test demonstrating the prior failure.
- [ ] `organization_type` sends the underscore `Organization_Type_ID` form, with a regression test.

**Project rules**
- [ ] `httpx` is not imported anywhere in `parrot_tools/interfaces/workday/`; `rest.py` uses `aiohttp`.
- [ ] Selecting `env="sandbox"` without `WORKDAY_*_IMPL` credentials raises at config resolution — it never falls back to production credentials.
- [ ] All new/modified functions carry Google-style docstrings and strict type hints.
- [ ] All new I/O is async; no blocking calls in async contexts.
- [ ] Logging uses the module logger, never `print`.

**Packaging & verification**
- [ ] `packages/ai-parrot-tools/pyproject.toml` declares a `workday` extra with `zeep`, `pandas`, `aiohttp`.
- [ ] A manual smoke script exists under `examples/`, documented as maintainer-run-only and never wired into CI.
- [ ] `pytest packages/ai-parrot-tools/tests/workday/ -v` passes.
- [ ] `ruff check` passes on all changed files.
- [ ] `flowtask` repository is unmodified (`git -C ../flowtask status --porcelain` empty of our changes).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All line numbers below were re-verified on 2026-08-05 against `dev`
> at commit `9366774ef`. Verify before use if the tree has moved.

### Verified Imports

```python
from parrot.interfaces.soap import SOAPClient        # verified: packages/ai-parrot/src/parrot/interfaces/soap.py:50
from parrot_tools.interfaces.workday.config import WorkdayConfig, get_wsdl_path
from parrot_tools.interfaces.workday.handlers import (   # verified: handlers/__init__.py:1-62
    CostCenterType,          # line 6
    OrganizationType,        # line 5
    CustomReportType,        # line 14
    PutTimeClockEventsType,  # line 20
    RequestTimeOffType,      # line 24  (FEAT-230 — ai-parrot ONLY)
    TimeOffEligibilityType,  # line 25  (FEAT-230 — ai-parrot ONLY)
    PayrollBalancesType,     # line 27  (FEAT-232 — ai-parrot ONLY)
    PayrollResultsType,      # line 27  (FEAT-232 — ai-parrot ONLY)
    CompanyPaymentDatesType, # line 27  (FEAT-232 — ai-parrot ONLY)
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/interfaces/soap.py
class SOAPClient(ABC):                                       # line 50
    def __init__(...)                                        # line 88
    def _resolve_wsdl_path(self, wsdl: Union[str, Path]) -> str:   # line 143
    async def start(self) -> None:                           # line 149
    async def _get_bearer_token(self) -> str:                # line 171
    def get_transport(self) -> NoProxyAsyncTransport:        # line 202
    def get_settings(self) -> Settings:                      # line 215
    def get_client(self) -> ZeepAsyncClient:                 # line 221
    def bind_service(self) -> Any:                           # line 231  <-- THE HOOK TO OVERRIDE
        """Return the bound service proxy from Zeep."""
        return self._client.service
    async def run(self, operation: str, **kwargs) -> Any:    # line 237
    async def close(self) -> None:                           # line 250
```

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py
_WSDL_ROUTING: dict[str, Any] = { ... }   # line 58 — EXTEND, do not restructure

class WorkdayConfig(BaseModel):                              # line 112
    client_id: str | None = None                             # line 129
    client_secret: str | None = None                         # line 130
    token_url: str | None = None                             # line 131
    refresh_token: str | None = None                         # line 132
    report_username: str | None = None                       # line 133
    report_password: str | None = None                       # line 134
    tenant: str | None = None                                # line 135  <-- VENDOR-NEUTRAL, keep None
    report_owner: str | None = None                          # line 136  <-- VENDOR-NEUTRAL, keep None
    workday_url: str | None = None                           # line 137  <-- VENDOR-NEUTRAL, keep None
    timeout: int = 300                                       # line 138

    # @computed_field @property — explicit value wins, parrot.conf fallback
    def resolved_client_id(self) -> str | None:              # line 146
    def resolved_client_secret(self) -> str | None:          # line 152
    def resolved_token_url(self) -> str | None:              # line 158
    def resolved_refresh_token(self) -> str | None:          # line 164
    def resolved_report_username(self) -> str | None:        # line 170
    def resolved_report_password(self) -> str | None:        # line 176
    def resolved_tenant(self) -> str | None:                 # line 182
    def resolved_report_owner(self) -> str | None:           # line 188
    def resolved_workday_url(self) -> str | None:            # line 194
```

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py
class WorkdayService(SOAPClient):                            # line 118
    def __init__(...)                                        # line 134
    # _handlers registration dict ~line 245 — THESE ENTRIES MUST SURVIVE:
    #   line 250-252  "get_payroll_balances" / "get_payroll_results" /
    #                 "get_company_payment_dates"          (FEAT-232)
    #   line 254-256  "request_time_off" /
    #                 "get_time_off_eligibility"           (FEAT-230)
    async def call_operation(self, operation: str, **kwargs: Any) -> Any:       # line 265
    async def fetch(self, operation_type: str, **params: Any) -> pd.DataFrame:  # line 280
    async def fetch_models(self, operation_type: str, **params: Any) -> list:   # line 305
    async def get_custom_report(...)                         # line 344
    async def put_time_clock_events(...)                     # line 378
    async def import_time_clock_events(...)                  # line 407
    async def import_reported_time_blocks(...)               # line 429
    async def get_calculated_time_blocks(self, **criteria: Any) -> pd.DataFrame:  # line 445
    async def start(self, **_kwargs: Any) -> None:           # line 465
    async def close(self) -> None:                           # line 469
    def serialize_object(self, obj: Any) -> Any:             # line 477
    def split_parts(self, task_list: list, num_parts: int = 5) -> list:  # line 507
    def add_metric(self, key: str, value: Any) -> None:      # line 529
```

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py
class WorkdayTypeBase(ABC):                                  # line 11
    def __init__(...)                                        # line 21
    def _get_default_payload(self) -> Dict[str, Any]:        # line 42
    async def execute(self, **kwargs) -> Any:                # line 53
    async def _paginate_soap_operation(...)                  # line 60

class WorkdayWriteTypeBase(WorkdayTypeBase):                 # line 178
    def _get_default_payload(self) -> Dict[str, Any]:        # line 198
    def _operation_name(self) -> str:                        # line 202
    def build_request(self, **kwargs) -> Dict[str, Any]:     # line 212
    def parse_ack(self, raw: Any) -> Any:                    # line 227
    async def execute(self, **kwargs) -> Any:                # line 243
```

```python
# ../flowtask/flowtask/interfaces/workday/rest.py — THE SOURCE TO PORT
# (httpx-based; MUST be reimplemented on aiohttp preserving this surface)
class WorkdayRestClient:                                                       # line 41
    def __init__(self, *, config=None, timeout=30, time_tracking_version="v5") # line 58
    def base_url(self) -> str:                                                 # line 77
    def set_token(self, token: str, expires_in: int = 300) -> None:            # line 81
    async def get_token(self) -> str:                                          # line 91
    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict:  # line 129
    async def find_worker(self, search: str, *, limit: int = 20) -> list[dict]:     # line 157
    async def get_time_clock_events(...)                                       # line 174
    async def find_time_clock_event(...)                                       # line 199
```

### Key Configuration References

| Setting | Type | Verified At | Status |
|---|---|---|---|
| `WORKDAY_DEFAULT_TENANT` | `str`, fallback `'nav'` | `packages/ai-parrot/src/parrot/conf.py:637` | exists |
| `WORKDAY_URL` | `str`, fallback `https://services1.wd501.myworkday.com` | `conf.py:688` | exists |
| `WORKDAY_REPORT_OWNER` | `str \| None` | `conf.py:687` | exists |
| `WORKDAY_WSDL_PAYROLL` | `str` | `conf.py:665` | exists |
| `WORKDAY_WSDL_PATHS` | `dict[str, str]` | `conf.py:690` | exists |
| `WORKDAY_REPORT_PASSWORD_BASE64` | decoded into `WORKDAY_REPORT_PASSWORD` | `conf.py:684-686` | exists |
| `WORKDAY_ENV` | `str` | — | **TO ADD** |
| `WORKDAY_CLIENT_ID_IMPL` | `str \| None` | — | **TO ADD** |
| `WORKDAY_CLIENT_SECRET_IMPL` | `str \| None` | — | **TO ADD** |
| `WORKDAY_REFRESH_TOKEN_IMPL` | `str \| None` | — | **TO ADD** |
| `WORKDAY_TOKEN_URL_IMPL` | `str \| None` | — | **TO ADD** |

The existing `WORKDAY_*` block spans `conf.py:637-698`; new settings append there.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `WorkdayService.bind_service()` override | `SOAPClient.bind_service()` | `super()` call then endpoint rewrite | `packages/ai-parrot/src/parrot/interfaces/soap.py:231` |
| `WorkdayRestClient` | `WorkdayConfig` | shared config object (`resolved_*`) | `config.py:112` |
| Enrichment methods | `CostCenterType` | private methods on the existing handler | `handlers/__init__.py:6` |
| New clock-event fields | `PutTimeClockEventsType` | payload construction in `build_request` | `handlers/base.py:212` |
| `workday` extra | `pyproject.toml` | `[project.optional-dependencies]` | `packages/ai-parrot-tools/pyproject.toml` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools/interfaces/workday/rest.py`~~ — the entire module is absent; **create**, do not edit.
- ~~`parrot.conf.WORKDAY_ENV`~~ — verified absent.
- ~~`parrot.conf.WORKDAY_CLIENT_ID_IMPL`~~ — verified absent.
- ~~`parrot.conf.WORKDAY_CLIENT_SECRET_IMPL`~~ — verified absent.
- ~~`parrot.conf.WORKDAY_REFRESH_TOKEN_IMPL`~~ — verified absent.
- ~~`parrot.conf.WORKDAY_TOKEN_URL_IMPL`~~ — verified absent. (All five must be added.)
- ~~`WorkdayConfig.env`~~, ~~`.resolved_env`~~, ~~`.resolved_is_sandbox`~~ — do not exist.
- ~~`WorkdayService.bind_service()` override~~, ~~`._point_endpoint_at_configured_host()`~~ — ai-parrot inherits the plain hook with no rewrite.
- ~~`ClockEvent.delete`~~, ~~`.location`~~, ~~`.cost_center`~~, ~~`.latitude`~~, ~~`.longitude`~~, ~~`.override_rate`~~ — none exist.
- ~~`CostCenterType._enrich_with_organizations`~~, ~~`._fetch_org_enrichment`~~, ~~`._resolve_container_orgs`~~, ~~`._build_hierarchy_chain`~~, ~~`._fetch_container_org_info`~~ — absent.
- ~~`CustomReportType._parse_json_to_entries`~~ — absent.
- ~~`SOAPClient.__aenter__` / `SOAPClient.__aexit__`~~ — flowtask's `SOAPClient` defines them (`SOAPClient.py:347,351`); **ai-parrot's does not**. Any ported `async with WorkdayService(...)` will fail. Verified: the only such usage in flowtask is a **docstring example** at `service.py:123` — adapt the docstring to explicit `start()`/`close()`; do NOT add the protocol to core in this feature.
- ~~a `workday` extra in `packages/ai-parrot-tools/pyproject.toml`~~ — does not exist yet (Module 7 adds it). Declared deps today are only `ai-parrot`, `PyGithub`, `ddgs`.
- ~~`httpx` as a direct dependency of `ai-parrot-tools`~~ — not declared; present only transitively via `httpx-sse`. This is why `rest.py` must be rewritten, not copied.
- ~~`flowtask` payroll / absence-management handlers~~ — flowtask has NO `payroll.py`, `time_off_request.py` or `time_off_eligibility.py`. These are ai-parrot-only; do not expect to find or "restore" them from flowtask.
- ~~`_PROD_WORKDAY_URL` in ai-parrot's `config.py`~~ — a flowtask-only constant. Do NOT port it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Curated per-hunk merge — never wholesale copy.** For each file, diff the
  normalised trees and judge each hunk. Reproduce the normalisation with:
  ```bash
  rsync -a --exclude __pycache__ ../flowtask/flowtask/interfaces/workday/ /tmp/ft/
  rsync -a --exclude __pycache__ packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/ /tmp/ap/
  find /tmp/ft -name '*.py' -exec sed -i 's/\bflowtask\b/PKG/g' {} +
  find /tmp/ap -name '*.py' -exec sed -i 's/\bparrot_tools\b/PKG/g' {} +
  diff -ru /tmp/ft /tmp/ap
  ```
- `aiohttp` for all HTTP — `requests` and `httpx` are forbidden by `CLAUDE.md`.
- Async-first: no blocking I/O in async contexts.
- Pydantic v2 models for all structured data; remember `Optional[X]` needs an explicit `= None` to be optional.
- Google-style docstrings and strict type hints on every new/modified function.
- Module logger (`self._logger` / `logging.getLogger(__name__)`), never `print`.
- Extend `_WSDL_ROUTING` and `_handlers` — do not restructure them.
- Follow the existing handler inheritance (`WorkdayTypeBase` / `WorkdayWriteTypeBase`).

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| **Dropping FEAT-230/232 registrations.** The highest-cost failure mode: `service.py` and `handlers/__init__.py` are the files with big flowtask gaps AND the ai-parrot-only handler wiring. A careless overwrite silently removes five handlers. | Dedicated acceptance criterion + `test_feat_230_232_handlers_still_registered`. Never overwrite these two files; edit them surgically. |
| **Re-introducing vendor lock-in.** flowtask hardcodes `tenant="troc"`, `report_owner="jtorres@trocglobal.com"`, `_PROD_WORKDAY_URL`. | Acceptance criterion greps for both strings; keep all three fields `None` + conf-resolved. |
| **Silent production writes.** Sandbox selected but endpoint not rewritten, or `_IMPL` credentials missing and silently falling back. | `bind_service()` rewrite + fail-loud on missing `_IMPL` credentials, both with tests. |
| **`aiohttp` rewrite diverging from the verified httpx original.** flowtask's `rest.py` was validated against a real tenant; the rewrite is not. | Preserve the public surface verbatim; cover token caching, WID-required errors and session lifecycle with tests; provide the manual smoke script for on-demand real-tenant verification. |
| **`aiohttp` session leaks.** `httpx` used `async with` per request; a naive port can leak sessions. | Explicit `close()` with lifecycle semantics consistent with `SOAPClient.close()`; `test_rest_client_closes_session`. |
| **REST token expiry mid-flight.** | Refresh shortly before expiry; a 401 despite a cached token triggers exactly ONE re-authentication, never an unbounded retry loop. |
| **GPS leaking into the SOAP payload.** The Time Tracking WSDL has no geo field through v46.1; sending it would break the call. | `latitude`/`longitude` validated and carried on the model but never serialised; `test_clock_event_gps_never_serialised`. |
| **`organization_type` behaviour change.** Callers passing `"Cost Center"` with a space change behaviour. | Practical blast radius is small — the space form matched nothing — but it is called out here and in §5 as a behaviour change. |
| **Regressing ai-parrot's cleanups.** Copying flowtask hunks re-introduces removed imports and `except Exception as e:`. | Explicit acceptance criteria; `ruff check` on all changed files. |
| **`async with WorkdayService(...)` in ported docstrings.** ai-parrot's `SOAPClient` has no `__aenter__`/`__aexit__`. | Adapt the docstring to explicit `start()`/`close()`; adding the protocol to core is deferred (§8). |
| **`parrot/conf.py` is a shared edit point.** Other features append there too. | Append only; do not restructure the `WORKDAY_*` block. |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | (via `ai-parrot`) | REST transport for `WorkdayRestClient`; mandated over `httpx` by `CLAUDE.md`. To be declared explicitly in the new `workday` extra. |
| `zeep[async]` | `==4.3.3` | SOAP transport underpinning `SOAPClient`; already pinned at `packages/ai-parrot/pyproject.toml:280`. To be declared in the `workday` extra. |
| `pydantic` | v2 | All Workday models; the `Optional[X] = None` fix is a v2 semantics issue. |
| `pandas` | `>=2.0` | `WorkdayService.fetch()` DataFrame surface. To be declared in the `workday` extra. |
| `pytest` / `pytest-asyncio` | existing | Mock-based verification. |

**No new third-party packages are introduced** — the `workday` extra makes
existing transitive dependencies explicit.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: The six capability slices touch mostly disjoint files
  (`cost_centers.py`, `custom_report.py`, `clock_event.py`, `rest.py` never
  overlap), so parallelism looks attractive. But Modules 1, 2 and 4 all
  converge on `config.py`, `service.py` and `handlers/__init__.py` for
  registration. Those are narrow, high-traffic merge points — and a bad
  merge there is exactly the failure that silently drops the FEAT-230/232
  registrations, the most expensive mistake available in this feature.
  Sequential tasks also let each hunk decision build on the previous one,
  which matters because the whole feature is judgement rather than
  mechanical transformation.
- **Cross-feature dependencies**: none. No in-flight spec currently touches
  `parrot_tools/interfaces/workday/`. Two completed specs define contracts
  this feature must not break: `workday-tooling-composable-interface` and
  `workday-composable-only-wsdl-routing`.
- **Shared file outside the Workday tree**: `packages/ai-parrot/src/parrot/conf.py`
  is a common edit point for other features — append only.
- **Suggested worktree**:
  ```bash
  git worktree add -b feat-415-workday-interfaces-homologation \
    .claude/worktrees/feat-415-workday-interfaces-homologation HEAD
  ```

---

## 8. Open Questions

**Resolved in brainstorm** (carried forward — do not re-open):

- [x] Direction of the homologation — *Resolved in brainstorm*: One-way, flowtask → ai-parrot only. `flowtask` is not modified. FEAT-230 and FEAT-232 preserved intact.
- [x] How to handle `rest.py`'s `httpx` dependency — *Resolved in brainstorm*: Rewrite on `aiohttp` to comply with `CLAUDE.md`. Accepted risk: subtle behavioural differences from the httpx original that was verified against a live tenant.
- [x] Whether to port flowtask's hardcoded tenant defaults with the `env` selector — *Resolved in brainstorm*: Port `WORKDAY_ENV`, the `*_IMPL` credentials and the SOAP endpoint rewrite, but keep vendor neutrality — no `tenant="troc"`, no `jtorres@trocglobal.com`, no hardcoded prod-URL default. Requires five new settings in `parrot/conf.py`.
- [x] Whether to expose the new capabilities as `WorkdayToolkit` tools — *Resolved in brainstorm*: Interface layer only; `parrot_tools/workday/tool.py` untouched.
- [x] Merge granularity — *Resolved in brainstorm*: Curated per-hunk, so ai-parrot's cleanups are not regressed and flowtask's fixes are not missed.
- [x] Treatment of the two behaviour-changing bug fixes — *Resolved in brainstorm*: Both in scope, each with a regression test demonstrating the prior failure. Documented as behaviour changes.
- [x] Verification strategy without a live tenant — *Resolved in brainstorm*: Mock-based tests in CI following the `test_homologation_read.py` pattern, plus an optional manual smoke script under `examples/`.
- [x] Parity target — *Resolved in brainstorm*: Functional parity. Residual docstring, import-ordering and style differences accepted as intentional.

**Resolved during spec research**:

- [x] Should `ai-parrot-tools` declare a `workday` extra? — *Resolved 2026-08-05*: Yes. Add `[project.optional-dependencies] workday = [zeep, pandas, aiohttp]` following the existing extras pattern (`jira`, `slack`, `aws`), making an already-real dependency explicit. Module 7.
- [x] `SOAPClient.__aenter__`/`__aexit__` mismatch — *Resolved 2026-08-05*: The only `async with WorkdayService(...)` usage in flowtask is a **docstring example** (`flowtask/interfaces/workday/service.py:123`), not executable code. Adapt the docstring to explicit `start()`/`close()`; do NOT modify `parrot.interfaces.soap.SOAPClient` in this feature.
- [x] Sandbox selected but `*_IMPL` credentials unset — *Resolved 2026-08-05*: **Fail loudly** — raise at config resolution. A silent fallback would send sandbox-intended writes to the production tenant, the worst failure this feature can produce.
- [x] Target version — *Resolved 2026-08-05*: `0.2.0` (minor) for `ai-parrot-tools`, currently `0.1.85` — the feature adds new public capabilities and changes behaviour in two places.

**Still open**:

- [ ] Should adding `__aenter__`/`__aexit__` to `parrot.interfaces.soap.SOAPClient` be scheduled as a separate DX improvement? Not needed by this feature (docstring-only usage), but flowtask's base class has it and the asymmetry will surprise people. — *Owner: Jesus Lara*
- [ ] Is brainstorm Option C — extracting a shared `workday-core` distribution consumed by both repos, per the `ai-parrot-embeddings` FEAT-201 namespace-package pattern — worth scheduling once this port lands, to stop the drift recurring? — *Owner: Jesus Lara*
- [ ] After this port, should a scheduled parity check (brainstorm Option D: normalise prefixes + diff both trees) run periodically to detect renewed drift? It cannot run in CI, since it needs a sibling `flowtask` checkout. — *Owner: Jesus Lara*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-05 | Jesus Lara | Initial draft from `workday-interfaces-homologation.brainstorm.md` (Option A) |
