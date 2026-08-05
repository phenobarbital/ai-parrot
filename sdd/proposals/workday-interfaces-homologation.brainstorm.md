---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Workday Interfaces Homologation (flowtask → ai-parrot)

**Date**: 2026-08-05
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`flowtask/interfaces/workday/` and
`packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/` are two
copies of the same codebase lineage that have drifted apart independently.
After normalising the import prefix (`flowtask.` → `parrot_tools.`),
**48 files still differ**.

The drift is **bidirectional**, which is the crux of the problem:

**flowtask has capabilities ai-parrot lacks**

| Gap | Size | What it is |
|---|---|---|
| `rest.py` → `WorkdayRestClient` | 217 lines, absent in ai-parrot | REST `/ccx/api` client. The WSDL services have **no** operation to read raw time clock events; the REST API does, echoing back the client-assigned `Time_Clock_Event_ID` and the effective `timeEntryCode`. Without it, post-punch verification is impossible. |
| `handlers/cost_centers.py` | +311 lines | Organisation-hierarchy enrichment: `_enrich_with_organizations`, `_fetch_org_enrichment`, `_resolve_container_orgs`, `_build_hierarchy_chain`, `_fetch_container_org_info` |
| `parsers/cost_center_parsers.py` | +120 lines | Matching parser surface for the enrichment above |
| `config.py` env selector | +71 lines | `WORKDAY_ENV` prod/sandbox switch, the `WORKDAY_*_IMPL` credential set, and a validator aligning `workday_url` to the selected environment |
| `service.py` endpoint rewrite | +64 lines | `bind_service()` override + `_point_endpoint_at_configured_host()` |
| `models/clock_event.py` | +52 lines | `delete`, `location` / `cost_center` overrides, GPS `latitude`/`longitude`, `override_rate`, plus a validator |
| `handlers/custom_report.py` | +81 lines | `_parse_json_to_entries` — the JSON custom-report path |
| `parsers/job_requisition_parsers.py` | +23 lines | Parser refinements |
| `handlers/put_time_clock_events.py` | +14 lines | Emission of the new clock-event fields |

**ai-parrot has capabilities flowtask lacks** (must NOT be regressed)

- **FEAT-230** — `request_time_off` (`handlers/time_off_request.py`),
  `get_time_off_eligibility` (`handlers/time_off_eligibility.py`,
  `models/time_off_eligibility.py`)
- **FEAT-232** — payroll reads (`handlers/payroll.py`:
  `PayrollBalancesType`, `PayrollResultsType`, `CompanyPaymentDatesType`)
- **Vendor neutrality** — flowtask hardcodes `tenant = "troc"` and
  `report_owner = "jtorres@trocglobal.com"` and a production URL constant;
  ai-parrot deliberately replaced these with `None` + conf-resolved
  computed fields (`resolved_tenant`, `resolved_report_owner`,
  `resolved_workday_url`). A naive copy would re-introduce one customer's
  identifiers into the framework core.
- **Code hygiene** — ai-parrot removed unused imports (`asyncio`, `math`,
  `datetime`, `Optional`) in several handlers and tidied
  `except Exception as e:` → `except Exception:`.

Two of flowtask's small diffs are **latent bug fixes ai-parrot is missing**:

1. `models/time_block.py` — flowtask adds `= None` to every `Optional[...]`
   field. In Pydantic v2, `Optional[X]` **without** a default is still a
   REQUIRED field, so ai-parrot's model raises on the partial Workday
   responses that occur routinely (unprocessed clock events, tenants that
   do not populate `is_deleted`).
2. `handlers/organizations.py` — flowtask uses the underscore
   `Organization_Type_ID` form (`"Cost_Center"`); ai-parrot passes
   `"Cost Center"` with a space, which the API does not match.

**Who is affected**: agents and toolkits built on `WorkdayToolkit` /
`WorkdayService` in ai-parrot — today they cannot target a sandbox tenant,
cannot verify a punch after writing it, cannot delete or override a clock
event, and get an exception instead of data on partial time-block responses.

**Why now**: the gap is only growing. Each new flowtask fix widens it, and
every ai-parrot Workday feature built on the incomplete interface inherits
the same blind spots.

## Constraints & Requirements

- **One-way port only.** ai-parrot receives what it lacks; `flowtask` is
  NOT modified in this feature. ai-parrot-exclusive features (FEAT-230,
  FEAT-232) must survive untouched.
- **No `httpx`.** `CLAUDE.md` forbids `requests`/`httpx` and mandates
  `aiohttp`. flowtask's `rest.py` is built on `httpx`, so it must be
  rewritten rather than copied. (`httpx` is only present transitively via
  `httpx-sse`; copying verbatim would make it an undeclared direct
  dependency of `ai-parrot-tools`.)
- **Vendor neutrality is non-negotiable.** Port the `env` selector, but do
  NOT re-introduce `tenant="troc"` / `report_owner="jtorres@trocglobal.com"`
  / the hardcoded `_PROD_WORKDAY_URL` default.
- **Per-hunk curation, not file replacement.** ai-parrot's cleanups must
  not be regressed by wholesale copies.
- **Interface layer only.** `parrot_tools/workday/tool.py` (the
  `WorkdayToolkit`, 1740 lines) is out of scope — no new agent-facing tools
  in this feature.
- **No live Workday tenant in CI.** Automated verification must be
  mock-based, following the existing pattern in
  `packages/ai-parrot-tools/tests/workday/test_homologation_read.py`.
- **Async-first, Google-style docstrings, strict type hints, Pydantic
  models, `self.logger`** — standard project rules apply to all ported code.
- **Target parity is functional, not textual.** Residual docstring / import
  ordering / style differences are acceptable and expected.

---

## Options Explored

### Option A: Curated per-hunk port, sliced by capability

Walk the normalised diff hunk by hunk and adopt each difference on its own
merits, grouped into six capability slices that map cleanly onto tasks:

1. **Environment & endpoint routing** — `WorkdayConfig.env`,
   `resolved_env` / `resolved_is_sandbox`, the `WORKDAY_*_IMPL` conf
   settings, the `workday_url` alignment validator, and the
   `bind_service()` / `_point_endpoint_at_configured_host()` override on
   `WorkdayService`. Vendor-neutral: new fields default to `None` and
   resolve through `parrot.conf`.
2. **REST client** — `WorkdayRestClient` reimplemented on `aiohttp`,
   preserving the public surface (`base_url`, `set_token`, `get_token`,
   `get`, `find_worker`, `get_time_clock_events`, `find_time_clock_event`)
   and the in-memory token cache.
3. **Cost-centre organisation enrichment** — the five private enrichment
   methods on `CostCenterType` plus their parser support.
4. **Clock-event write surface** — the new `ClockEvent` fields
   (`delete`, `location`, `cost_center`, `override_rate`, `latitude`,
   `longitude`), the `delete → time_clock_event_id` validator, and the
   corresponding emission logic in `PutTimeClockEventsType` (with GPS
   deliberately NOT sent — the Time Tracking WSDL has no geo field).
5. **Custom-report JSON path** — `_parse_json_to_entries` on
   `CustomReportType`.
6. **Model & parser fixes** — the `time_block.py` Pydantic default fix,
   the `Organization_Type_ID` underscore correction, and the residual
   small parser hunks (`job_requisition_parsers` +23,
   `worker_parsers` +7, `time_request_parsers` +3, etc.), each judged
   individually against ai-parrot's cleanups.

Plus a manual smoke script under `examples/` that the maintainer can run
against the implementation tenant on demand (never in CI).

✅ **Pros:**
- The only approach that satisfies both directions of the drift: nothing
  ai-parrot gained is lost, nothing flowtask fixed is missed.
- Vendor neutrality and code hygiene are preserved by construction.
- Slices are individually reviewable and individually testable; a problem
  in the REST rewrite does not block the cost-centre enrichment.
- The two latent bug fixes get explicit regression tests proving the
  failure existed and is gone.

❌ **Cons:**
- Slowest option — ~48 files must actually be read and judged, not copied.
- Requires human judgement per hunk; a careless executor could still
  regress a cleanup.
- The `aiohttp` rewrite of `rest.py` is the one place where behaviour could
  subtly diverge from the flowtask original that was verified against a
  real tenant (error-shape handling, timeout semantics).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | REST client transport for `WorkdayRestClient` | Already available transitively via `ai-parrot`; mandated by `CLAUDE.md` over `httpx` |
| `zeep[async]==4.3.3` | SOAP transport underpinning `SOAPClient` | Already pinned in `packages/ai-parrot/pyproject.toml:280` |
| `pydantic` v2 | All Workday models | Already in use; the `Optional[X] = None` fix is a v2 semantics issue |
| `pandas` | `fetch()` DataFrame surface | Already used by `service.py`; declared under the `analysis` extra |
| `pytest` / `pytest-asyncio` / `unittest.mock` | Mock-based verification | Matches the existing `tests/workday/` pattern |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/interfaces/soap.py:231` — `SOAPClient.bind_service()`; the flowtask override extends exactly this hook, so it is directly compatible.
- `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py:11,178` — `WorkdayTypeBase` / `WorkdayWriteTypeBase`; every ported handler already inherits these.
- `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py:58` — `_WSDL_ROUTING`; the env work extends this dict rather than replacing it.
- `packages/ai-parrot-tools/tests/workday/test_homologation_read.py` — the established toolkit-mocking fixture pattern for tests without a live tenant.
- `packages/ai-parrot/src/parrot/conf.py:637-698` — the existing `WORKDAY_*` block the new `*_IMPL` / `WORKDAY_ENV` settings slot into.

---

### Option B: Wholesale file replacement for large gaps, curation only for small ones

Overwrite the files with big gaps (`cost_centers.py`, `custom_report.py`,
`clock_event.py`, `rest.py`, `config.py`, `service.py`) directly from
flowtask, adjust imports, and hand-curate only the sub-20-line diffs.

✅ **Pros:**
- Much faster to execute; the large, high-value gaps close in a handful of
  file copies.
- Zero risk of *missing* a flowtask fix inside a big file.
- Byte-fidelity for the enrichment and REST logic that was verified against
  a real tenant.

❌ **Cons:**
- Regresses ai-parrot's cleanups inside exactly those files: unused-import
  removal and the `except Exception:` tidy-ups get reverted silently.
- `config.py` and `service.py` are precisely the files where ai-parrot's
  divergence is *deliberate and valuable* (vendor neutrality, FEAT-230/232
  handler registration). Overwriting them would drop the payroll and
  absence-management handler wiring and re-introduce the `troc` defaults.
- Still requires an `httpx` → `aiohttp` rewrite for `rest.py`, so the
  "just copy it" benefit does not apply to the single largest new file.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ruff` | Post-copy cleanup of re-introduced unused imports | Partially mitigates the regression, but cannot restore semantic decisions |
| `aiohttp` | Still needed for the `rest.py` rewrite | The copy shortcut does not apply here |

🔗 **Existing Code to Reuse:**
- Same base classes as Option A, but with a materially higher chance of
  clobbering `service.py:247` (the FEAT-230/232 handler registration block)
  and `handlers/__init__.py:24-32` (their exports).

---

### Option C: Extract a shared `workday-core` distribution consumed by both repos

Stop maintaining two copies. Promote the Workday interface into its own
distribution that both `flowtask` and `ai-parrot-tools` depend on, using the
same PEP 420 namespace-package technique already proven by
`ai-parrot-embeddings` (FEAT-201).

✅ **Pros:**
- Ends the drift permanently instead of closing it once. This is the only
  option where the problem does not recur in six months.
- Single place for future Workday fixes; both consumers get them for free.
- There is a working in-repo precedent for the packaging mechanics
  (`packages/ai-parrot-embeddings`, namespace-merged under `parrot.*`).

❌ **Cons:**
- Directly contradicts the agreed scope: the user chose FT → AP only, with
  `flowtask` untouched. This option requires changing flowtask.
- The two copies must be reconciled *first* anyway — you cannot extract a
  shared package until you have decided, hunk by hunk, which version wins.
  So this is strictly Option A **plus** a large packaging project, not an
  alternative to it.
- Cross-repo release coordination, a new distribution to version and
  publish, and a migration window where both repos must move together.
- flowtask's copy depends on `flowtask.interfaces.SOAPClient` (which has
  `__aenter__`/`__aexit__`) while ai-parrot's `SOAPClient` does not — the
  base classes would have to be reconciled too.

📊 **Effort:** High (substantially higher than A)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `hatchling` / PEP 420 namespace packages | Shared-distribution packaging | Pattern proven by `packages/ai-parrot-embeddings` |
| `uv` | Workspace / editable installs across both repos | Project-mandated package manager |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-embeddings/` — the entire namespace-merge layout and
  its `pyproject.toml` as the template.
- `docs/migration/feat-201-ai-parrot-embeddings.md` — the written migration
  playbook for exactly this manoeuvre.

---

### Option D: Drift-harness first — codify the comparison, then port under its guidance

Before porting anything, commit the normalisation-and-diff tooling itself
(strip the package prefix from both trees, diff, classify each file as
identical / ai-parrot-ahead / flowtask-ahead) as a small script under
`scripts/`. Port using its output as the worklist, and keep the script as a
repeatable parity report that can be re-run whenever either repo moves.

✅ **Pros:**
- The unusual move: it makes the *comparison* a durable artifact rather
  than a one-off analysis that must be redone from scratch next time.
- Turns "are we still behind?" from an afternoon of investigation into one
  command.
- The worklist is generated rather than hand-transcribed, so no gap can be
  forgotten.
- Cheap — the normalisation is a `sed` prefix rewrite plus `diff -rq`.

❌ **Cons:**
- The script depends on a sibling checkout of `flowtask` at a relative
  path, so it cannot run in CI and would silently no-op (or fail) for any
  other contributor.
- Solves the *detection* problem, not the *decision* problem — every hunk
  still needs human judgement, so it does not reduce the core effort of
  Option A at all.
- The user explicitly chose plain functional parity over "parity plus a
  residual inventory", which is most of what this option's output would be.

📊 **Effort:** Low (as an add-on) / High (the port it guides is still Option A)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `diff` / `rsync` / `sed` | Tree normalisation and comparison | POSIX shell only, no new dependency |

🔗 **Existing Code to Reuse:**
- `scripts/sdd/` — the established home for repo-maintenance scripts
  (`reserve_ids.py`, `check_id_collisions.py`) and the conventions they set.

---

## Recommendation

**Option A** is recommended.

The research made the decision for us. Option B is disqualified not because
it is sloppy in the abstract, but because of *which specific files* it would
overwrite: `config.py` and `service.py` are the two files where ai-parrot's
divergence is deliberate and valuable. Copying them from flowtask would drop
the FEAT-230/232 handler registrations and re-introduce one customer's
tenant identifiers into framework core — trading a maintenance shortcut for
a functional regression and a vendor-neutrality regression at once.

Option C is the right long-term answer to the *recurring* problem, and it is
worth revisiting later. But it is not an alternative to A — it is A plus a
cross-repo packaging project, because the two copies must be reconciled
before a shared package can be extracted at all. It also requires modifying
`flowtask`, which is out of the agreed scope.

Option D is genuinely cheap and its detection value is real, but it cannot
run in CI (it needs a sibling flowtask checkout) and it does not reduce the
judgement work that dominates this feature.

**What we are trading off:** Option A is the slowest path. ~48 files must be
read and judged rather than copied, and the `aiohttp` rewrite of `rest.py`
gives up byte-fidelity with a client that was verified against a live
tenant. We accept that cost because the alternative is a port that silently
regresses vendor neutrality and drops two shipped features — and because the
`httpx` prohibition forces a rewrite of the largest new file regardless, so
the "just copy it" saving was never available where it would have mattered
most.

---

## Feature Description

### User-Facing Behavior

For a developer building a Workday agent or toolkit on ai-parrot:

- **Sandbox targeting works.** `WorkdayConfig(env="sandbox")` resolves the
  `WORKDAY_*_IMPL` credential set and points SOAP traffic at the
  implementation host. Today this silently hits production, because the
  shipped WSDLs hardcode the production endpoint and nothing rewrites it.
- **Punches can be verified after writing.** `WorkdayRestClient` exposes
  `find_worker`, `get_time_clock_events` and `find_time_clock_event`,
  reading back the client-assigned `Time_Clock_Event_ID` and the effective
  `timeEntryCode` — data no WSDL operation returns.
- **Clock events can be deleted and overridden.** `ClockEvent` gains
  `delete` (soft-delete via the same `Put_Time_Clock_Events` operation),
  `location` and `cost_center` overrides, and `override_rate`. GPS
  `latitude`/`longitude` are accepted and carried on the model for the
  caller to persist, but are never sent to Workday.
- **Cost centres come back enriched.** `CostCenterType` results carry the
  resolved organisation hierarchy chain instead of bare container ids.
- **Partial time-block responses stop raising.** Routine partial responses
  parse into `TimeBlock` instead of failing validation.
- **Organisation-type filtering actually matches.** `"Cost_Center"` is sent
  in the underscore `Organization_Type_ID` form the API expects.

Configuration is additive: every new `WorkdayConfig` field defaults to
`None` and falls back through `parrot.conf`, so existing callers are
unaffected and no customer-specific default is introduced.

### Internal Behavior

- **Config layer** — `WorkdayConfig` gains an `env` field plus
  `resolved_env` / `resolved_is_sandbox` helpers. Each existing
  `resolved_*` credential property becomes environment-aware, selecting the
  `WORKDAY_*_IMPL` setting when sandbox is active. A model validator aligns
  `workday_url` with the selected environment. Five new settings are added
  to `parrot/conf.py` alongside the existing `WORKDAY_*` block.
- **Service layer** — `WorkdayService` overrides `bind_service()`, calls
  `super().bind_service()`, then rewrites the bound Zeep endpoint's scheme
  and host to match `workday_url`, preserving the WSDL path verbatim so both
  the standard and `customreport2` URL forms keep working. The rewrite is a
  no-op when the host already matches, and any failure is logged as a
  warning rather than breaking binding.
- **REST layer** — a new `rest.py` module holds `WorkdayRestClient`, built
  on an `aiohttp.ClientSession`. It performs the same OAuth refresh-token
  grant as `SOAPClient` and caches the bearer token in memory until shortly
  before expiry (no Redis dependency). It shares `WorkdayConfig`, so the
  environment selector applies to REST as well as SOAP.
- **Handler layer** — `CostCenterType` gains its five private enrichment
  methods; `CustomReportType` gains `_parse_json_to_entries`;
  `PutTimeClockEventsType` emits the new clock-event fields. New handlers
  register through the existing `_handlers` dict in `WorkdayService` and the
  `handlers/__init__.py` `__all__` export list.
- **Model layer** — `ClockEvent` gains its new fields and the
  `delete → time_clock_event_id` validator; `TimeBlock` gains explicit
  `= None` defaults on every optional field.

### Edge Cases & Error Handling

- **`delete=True` without `time_clock_event_id`** — rejected by a Pydantic
  validator with an explicit message; you cannot delete an event you cannot
  identify.
- **GPS coordinates** — validated for range (`lat` ∈ [-90, 90],
  `lon` ∈ [-180, 180]) but never serialised into the SOAP payload. The Time
  Tracking WSDL has no geo field in any version through v46.1.
- **Endpoint rewrite failure** — malformed or empty `workday_url`, or a
  missing `_binding_options`, must leave the original endpoint intact and
  log a warning. An endpoint rewrite must never break service binding.
- **Sandbox selected but `*_IMPL` credentials unset** — must fail loudly at
  config resolution rather than silently falling back to production
  credentials, which would send sandbox-intended writes to the live tenant.
- **REST `worker` parameter** — requires a Workday WID; Employee_ID values
  are rejected by the API with `400 "not found"`. The client should surface
  this as an actionable error rather than an opaque HTTP failure.
- **REST token expiry mid-flight** — the in-memory cache refreshes shortly
  before expiry; a 401 despite a cached token should trigger exactly one
  re-authentication, not an unbounded retry loop.
- **Partial Workday responses** — every `Optional[...]` field on `TimeBlock`
  must tolerate absence; only `raw_data` stays mandatory.
- **`aiohttp` session lifecycle** — the REST client must not leak sessions;
  it needs explicit close semantics consistent with `SOAPClient.close()`.

---

## Capabilities

### New Capabilities

- `workday-env-endpoint-routing`: prod/sandbox environment selector on
  `WorkdayConfig` plus the SOAP endpoint host rewrite on `WorkdayService`,
  without re-introducing tenant-specific defaults.
- `workday-rest-client`: `WorkdayRestClient` over `aiohttp` for the
  `/ccx/api` surface — worker lookup and raw time-clock-event reads.
- `workday-cost-center-enrichment`: organisation-hierarchy enrichment for
  cost-centre results.
- `workday-clock-event-write-surface`: delete, location / cost-centre
  override, override rate, and carried-not-sent GPS on `ClockEvent`.
- `workday-custom-report-json`: the JSON parsing path for custom reports.

### Modified Capabilities

- `workday-tooling-composable-interface` (`sdd/specs/workday-tooling-composable-interface.spec.md`)
  — the interface this feature extends; its handler-registration and
  composable-delegation contract must keep holding.
- `workday-composable-only-wsdl-routing` (`sdd/specs/workday-composable-only-wsdl-routing.spec.md`)
  — `_WSDL_ROUTING` is extended, not restructured; existing routing keys
  keep their current targets.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py` | modifies | `env` field, `resolved_env` / `resolved_is_sandbox`, env-aware credential resolution, URL alignment validator, `_WSDL_ROUTING` untouched |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py` | modifies | `bind_service()` override + `_point_endpoint_at_configured_host()`; FEAT-230/232 handler registrations must survive |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/rest.py` | creates | New `WorkdayRestClient` on `aiohttp` |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/cost_centers.py` | extends | Five private enrichment methods |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/custom_report.py` | extends | `_parse_json_to_entries` |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/put_time_clock_events.py` | modifies | Emission of new clock-event fields; GPS deliberately excluded |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/organizations.py` | modifies | `Organization_Type_ID` underscore form — behaviour change |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/clock_event.py` | modifies | New fields + validator |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/time_block.py` | modifies | Pydantic v2 optional-default fix — behaviour change |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/cost_center_parsers.py` | extends | Enrichment parser support |
| `packages/ai-parrot/src/parrot/conf.py` | extends | Five new settings after the existing `WORKDAY_*` block (line ~688) |
| `packages/ai-parrot-tools/pyproject.toml` | modifies | Consider declaring a `workday` extra — none exists today, and `zeep`/`pandas` are relied on only transitively |
| `packages/ai-parrot-tools/tests/workday/` | extends | New mock-based tests, including two regression tests |
| `examples/` | creates | Manual smoke script against the implementation tenant (never run in CI) |
| `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | unaffected | Explicitly out of scope — no new agent-facing tools |
| `flowtask` repository | unaffected | One-way port; flowtask is not modified |

**Breaking-ish changes** (behaviour changes for existing ai-parrot callers,
both intentional and both required to be correct):

1. `TimeBlock` optional fields gain defaults — strictly more permissive,
   turning a raised exception into parsed data.
2. `organization_type` now expects/sends the underscore form. Callers
   currently passing `"Cost Center"` with a space were matching nothing, so
   the practical blast radius is small, but it must be called out in the
   spec.

---

## Code Context

### User-Provided Code

The user provided no code snippets — only the pointer to the source tree:

```
# Source: user-provided (path relative to the ai-parrot repo root)
../flowtask/flowtask/interfaces/workday/__init__.py
```

The referenced `__init__.py` is a deliberately lightweight package docstring
(15 lines, no heavy imports); the substance lives in its sibling modules.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/interfaces/soap.py:50
class SOAPClient(ABC):
    def __init__(...)                                    # line 88
    def _resolve_wsdl_path(self, wsdl: Union[str, Path]) -> str:   # line 143
    async def start(self) -> None:                       # line 149
    async def _get_bearer_token(self) -> str:            # line 171
    def get_transport(self) -> NoProxyAsyncTransport:    # line 202
    def get_settings(self) -> Settings:                  # line 215
    def get_client(self) -> ZeepAsyncClient:             # line 221
    def bind_service(self) -> Any:                       # line 231  <-- the hook the port overrides
        """Return the bound service proxy from Zeep."""
        return self._client.service
    async def run(self, operation: str, **kwargs) -> Any:  # line 237
    async def close(self) -> None:                       # line 250
```

```python
# From packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py:112
class WorkdayConfig(BaseModel):
    client_id: str | None = None          # line 129
    client_secret: str | None = None      # line 130
    token_url: str | None = None          # line 131
    refresh_token: str | None = None      # line 132
    report_username: str | None = None    # line 133
    report_password: str | None = None    # line 134
    tenant: str | None = None             # line 135  (vendor-neutral; flowtask hardcodes "troc")
    report_owner: str | None = None       # line 136  (vendor-neutral)
    workday_url: str | None = None        # line 137  (vendor-neutral)
    timeout: int = 300                    # line 138

    # computed_field properties — explicit value wins, parrot.conf fallback
    def resolved_client_id(self) -> str | None:        # line 146
    def resolved_client_secret(self) -> str | None:    # line 152
    def resolved_token_url(self) -> str | None:        # line 158
    def resolved_refresh_token(self) -> str | None:    # line 164
    def resolved_report_username(self) -> str | None:  # line 170
    def resolved_report_password(self) -> str | None:  # line 176
    def resolved_tenant(self) -> str | None:           # line 182
    def resolved_report_owner(self) -> str | None:     # line 188
    def resolved_workday_url(self) -> str | None:      # line 194

_WSDL_ROUTING: dict[str, Any] = { ... }   # line 58 — extended, not restructured
```

```python
# From packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py:118
class WorkdayService(SOAPClient):
    def __init__(...)                                                  # line 134
    async def call_operation(self, operation: str, **kwargs: Any) -> Any:      # line 265
    async def fetch(self, operation_type: str, **params: Any) -> pd.DataFrame: # line 280
    async def fetch_models(self, operation_type: str, **params: Any) -> list:  # line 305
    async def get_custom_report(...)                                   # line 344
    async def put_time_clock_events(...)                               # line 378
    async def import_time_clock_events(...)                            # line 407
    async def import_reported_time_blocks(...)                         # line 429
    async def get_calculated_time_blocks(self, **criteria: Any) -> pd.DataFrame:  # line 445
    async def start(self, **_kwargs: Any) -> None:                     # line 465
    async def close(self) -> None:                                     # line 469
    def serialize_object(self, obj: Any) -> Any:                       # line 477
    def split_parts(self, task_list: list, num_parts: int = 5) -> list:  # line 507
    def add_metric(self, key: str, value: Any) -> None:                # line 529
    # NOTE: the _handlers registration dict (~line 247) carries the FEAT-230/232
    # entries that MUST survive this port:
    #   "get_payroll_balances", "get_payroll_results", "get_company_payment_dates",
    #   "request_time_off", "get_time_off_eligibility"
```

```python
# From packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py:11
class WorkdayTypeBase(ABC):
    def __init__(...)                              # line 21
    def _get_default_payload(self) -> Dict[str, Any]:   # line 42
    async def execute(self, **kwargs) -> Any:      # line 53
    async def _paginate_soap_operation(...)        # line 60

# From packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py:178
class WorkdayWriteTypeBase(WorkdayTypeBase):
    def _get_default_payload(self) -> Dict[str, Any]:   # line 198
    def _operation_name(self) -> str:              # line 202
    def build_request(self, **kwargs) -> Dict[str, Any]:  # line 212
    def parse_ack(self, raw: Any) -> Any:          # line 227
    async def execute(self, **kwargs) -> Any:      # line 243
```

```python
# From ../flowtask/flowtask/interfaces/workday/rest.py:41 — THE SOURCE TO PORT
# (currently httpx-based; to be reimplemented on aiohttp preserving this surface)
class WorkdayRestClient:
    def __init__(self, *, config=None, timeout=30, time_tracking_version="v5")  # line 58
    def base_url(self) -> str:                                          # line 77
    def set_token(self, token: str, expires_in: int = 300) -> None:     # line 81
    async def get_token(self) -> str:                                   # line 91
    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict:  # line 129
    async def find_worker(self, search: str, *, limit: int = 20) -> list[dict]:    # line 157
    async def get_time_clock_events(...)                                # line 174
    async def find_time_clock_event(...)                                # line 199
```

#### Verified Imports

```python
# These imports have been confirmed to resolve in ai-parrot today:
from parrot.interfaces.soap import SOAPClient          # packages/ai-parrot/src/parrot/interfaces/soap.py:50
from parrot_tools.interfaces.workday.config import WorkdayConfig, get_wsdl_path
from parrot_tools.interfaces.workday.handlers import (  # handlers/__init__.py:1-32
    CostCenterType,          # line 6
    OrganizationType,        # line 5
    CustomReportType,        # line 14
    PutTimeClockEventsType,  # line 20
    RequestTimeOffType,      # line 24  (FEAT-230 — ai-parrot only)
    TimeOffEligibilityType,  # line 25  (FEAT-230 — ai-parrot only)
    PayrollBalancesType,     # line 27  (FEAT-232 — ai-parrot only)
    PayrollResultsType,      # line 27  (FEAT-232 — ai-parrot only)
    CompanyPaymentDatesType, # line 27  (FEAT-232 — ai-parrot only)
)
```

#### Key Attributes & Constants

- `parrot.conf.WORKDAY_DEFAULT_TENANT` → `str`, fallback `'nav'` (`packages/ai-parrot/src/parrot/conf.py:637`)
- `parrot.conf.WORKDAY_URL` → `str`, fallback `"https://services1.wd501.myworkday.com"` (`conf.py:688`)
- `parrot.conf.WORKDAY_REPORT_OWNER` → `str | None` (`conf.py:687`)
- `parrot.conf.WORKDAY_WSDL_PAYROLL` → `str` (`conf.py:665`)
- `parrot.conf.WORKDAY_WSDL_PATHS` → `dict[str, str]` (`conf.py:690`)
- `parrot.conf.WORKDAY_REPORT_PASSWORD_BASE64` → decoded into `WORKDAY_REPORT_PASSWORD` when set (`conf.py:684-686`)
- `zeep[async]==4.3.3` pinned at `packages/ai-parrot/pyproject.toml:280`
- Existing `WORKDAY_*` conf block spans `packages/ai-parrot/src/parrot/conf.py:637-698` — new settings append here

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools/interfaces/workday/rest.py`~~ — the entire module is absent from ai-parrot; it must be created, not edited.
- ~~`parrot.conf.WORKDAY_ENV`~~ — verified absent.
- ~~`parrot.conf.WORKDAY_CLIENT_ID_IMPL`~~ — verified absent.
- ~~`parrot.conf.WORKDAY_CLIENT_SECRET_IMPL`~~ — verified absent.
- ~~`parrot.conf.WORKDAY_REFRESH_TOKEN_IMPL`~~ — verified absent.
- ~~`parrot.conf.WORKDAY_TOKEN_URL_IMPL`~~ — verified absent. (All five must be added.)
- ~~`WorkdayConfig.env`~~, ~~`WorkdayConfig.resolved_env`~~, ~~`WorkdayConfig.resolved_is_sandbox`~~ — do not exist in ai-parrot's config.
- ~~`WorkdayService.bind_service()` override~~ and ~~`WorkdayService._point_endpoint_at_configured_host()`~~ — ai-parrot inherits the plain `SOAPClient.bind_service()` with no host rewrite.
- ~~`ClockEvent.delete`~~, ~~`.location`~~, ~~`.cost_center`~~, ~~`.latitude`~~, ~~`.longitude`~~, ~~`.override_rate`~~ — none exist on ai-parrot's model.
- ~~`CostCenterType._enrich_with_organizations`~~, ~~`._fetch_org_enrichment`~~, ~~`._resolve_container_orgs`~~, ~~`._build_hierarchy_chain`~~, ~~`._fetch_container_org_info`~~ — absent from ai-parrot's handler.
- ~~`CustomReportType._parse_json_to_entries`~~ — absent from ai-parrot's handler.
- ~~`SOAPClient.__aenter__` / `SOAPClient.__aexit__`~~ — flowtask's `SOAPClient` defines them (`SOAPClient.py:347,351`); **ai-parrot's does not**. Any ported code using `async with WorkdayService(...)` will fail.
- ~~a `workday` extra in `packages/ai-parrot-tools/pyproject.toml`~~ — does not exist. Declared deps are only `ai-parrot`, `PyGithub`, `ddgs`; `zeep` and `pandas` are relied on transitively.
- ~~`httpx` as a direct dependency of `ai-parrot-tools`~~ — not declared; present only transitively via `httpx-sse`. This is why `rest.py` must be rewritten on `aiohttp` rather than copied.
- ~~`flowtask` payroll / absence-management handlers~~ — flowtask has NO `payroll.py`, `time_off_request.py`, `time_off_eligibility.py`. These are ai-parrot-only; do not expect to find or "restore" them from flowtask.

---

## Parallelism Assessment

- **Internal parallelism**: Partially available but not advisable. The six
  capability slices touch mostly disjoint files — `cost_centers.py`,
  `custom_report.py`, `clock_event.py` and `rest.py` never overlap. However,
  slices 1 and 2 both modify `config.py`, and slices 1, 2 and 4 all converge
  on `service.py` and `handlers/__init__.py` for registration. Those three
  files are narrow, high-traffic merge points where concurrent worktrees
  would conflict on nearly every task.
- **Cross-feature independence**: No in-flight spec currently touches
  `parrot_tools/interfaces/workday/`. Two completed specs define the
  contract this feature must not break —
  `workday-tooling-composable-interface` and
  `workday-composable-only-wsdl-routing`. The only file shared outside the
  Workday tree is `packages/ai-parrot/src/parrot/conf.py`, which is appended
  to (not restructured) and is a common edit point for other features.
- **Recommended isolation**: `per-spec`
- **Rationale**: The parallelism that exists is not worth its cost here.
  Every slice ultimately registers through `service.py:_handlers` and
  `handlers/__init__.py:__all__`, so parallel worktrees would spend their
  savings resolving conflicts on exactly the two files where a bad merge
  silently drops the FEAT-230/232 registrations — the single most expensive
  failure mode in this feature. Sequential tasks in one worktree also let
  each hunk decision build on the previous one, which matters because the
  whole feature is an exercise in judgement rather than mechanical
  transformation.

---

## Open Questions

- [x] Direction of the homologation — *Owner: Jesus Lara*: One-way, flowtask → ai-parrot only. `flowtask` is not modified. ai-parrot-exclusive features (FEAT-230 absence management, FEAT-232 payroll) are preserved intact.
- [x] How to handle `rest.py`'s `httpx` dependency — *Owner: Jesus Lara*: Rewrite on `aiohttp` to comply with `CLAUDE.md`. Accepted risk: subtle behavioural differences from the httpx original that was verified against a live tenant.
- [x] Whether to port flowtask's hardcoded tenant defaults along with the `env` selector — *Owner: Jesus Lara*: Port `WORKDAY_ENV`, the `*_IMPL` credentials and the SOAP endpoint rewrite, but keep vendor neutrality — do NOT re-introduce `tenant="troc"`, `report_owner="jtorres@trocglobal.com"` or the hardcoded prod URL default. Requires five new settings in `parrot/conf.py`.
- [x] Whether to expose the new capabilities as `WorkdayToolkit` tools — *Owner: Jesus Lara*: Interface layer only. `parrot_tools/workday/tool.py` is untouched in this feature.
- [x] Merge granularity — *Owner: Jesus Lara*: Curated per-hunk. Each difference is judged individually so ai-parrot's cleanups are not regressed and flowtask's fixes are not missed.
- [x] Treatment of the two behaviour-changing bug fixes — *Owner: Jesus Lara*: Both included in this feature, each with a regression test demonstrating the prior failure (partial Workday response for `TimeBlock`; organisation-type filtering for `Organization_Type_ID`). Documented as breaking-ish in the spec.
- [x] Verification strategy without a live tenant — *Owner: Jesus Lara*: Mock-based tests in CI following the `test_homologation_read.py` pattern, plus an optional manual smoke script under `examples/` to run against the implementation tenant on demand.
- [x] Parity target — *Owner: Jesus Lara*: Functional parity. Residual docstring, import-ordering and style differences are accepted and documented as intentional.
- [ ] Should `ai-parrot-tools` declare a `workday` extra? The Workday interface relies on `zeep` and `pandas`, but `pyproject.toml` declares neither directly — they arrive transitively through `ai-parrot`. Adding `aiohttp` usage in `rest.py` makes the implicit dependency surface slightly wider. — *Owner: Jesus Lara*
- [ ] `flowtask`'s `SOAPClient` defines `__aenter__`/`__aexit__`; ai-parrot's does not. If any ported code uses `async with`, do we add the context-manager protocol to `parrot.interfaces.soap.SOAPClient` (touching core, outside `parrot_tools`) or rewrite the call sites to explicit `start()`/`close()`? — *Owner: Jesus Lara*
- [ ] Should sandbox-selected-but-`*_IMPL`-unset raise at config resolution, or warn and fall back? Raising is safer (a silent fallback sends sandbox-intended writes to production) but is a harder failure for anyone with a partial `.env`. — *Owner: Jesus Lara*
- [ ] Is Option C (extracting a shared `workday-core` distribution consumed by both repos, per the `ai-parrot-embeddings` FEAT-201 pattern) worth scheduling as a follow-up once this port lands, to stop the drift recurring? — *Owner: Jesus Lara*
