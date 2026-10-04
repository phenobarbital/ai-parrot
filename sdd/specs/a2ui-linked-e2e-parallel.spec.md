---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-server, admin-ui, docs]
tags: [a2ui, linked-surfaces, querysource, e2e-example, pbac, multiquery]
e2e:
  policy: optional
  scenario_ids: [s1-server-lane, s2-join-dsl-filterbar, s3-multiquery, s5-tenant-route, s4-admin-chat]
---

# Feature Specification: A2UI Linked Surfaces E2E — parallel track (Epson, staging, querysource 5.1.2)

**Feature ID**: FEAT-611
**Date**: 2026-09-28
**Author**: Javier León
**Status**: approved
**Target version**: next dev minor
**Proposal**: `sdd/proposals/a2ui-linked-e2e-parallel.proposal.md` (accepted) · research `sdd/state/FEAT-611/`
**Sibling**: FEAT-610 `a2ui-linked-e2e-test` (Jesús Lara), which covers the browser lane over `polestar_graduates_directory`

---

## 1. Motivation & Business Requirements

### Problem Statement
FEAT-598 (A2UI Linked Surfaces) is merged into `dev`, but nobody has tested it end to end against real services. FEAT-610 covers one path: a static browser renderer that refreshes each widget with `POST /api/v3/queries/{slug}` over public slugs. It leaves the rest of FEAT-598 untested (proposal §1, F010, F013):

- the server lane: persistence, `/refresh` with params, share tokens, and the PBAC guard;
- linked sources: join/union and the `transform.ops` DSL;
- `FilterBar` with `parrot_param`;
- multiquery slugs and declared/locked params;
- the tenant route.

The proposal research also found that the Svelte linked lane **cannot be reached from a real agent chat**. There are five chained blockers (F014), and there is silent drift between the TS and Python lanes (F015). The one existing E2E test fakes every external dependency, and the vitest suites have never run. On top of that, the venv had querysource 4.5.11; the user asked for this to be validated on the **latest querysource, 5.1.2**.

### Goals
- G1: Runnable, asserting E2E scenarios S1, S2, S3 and S5 over the Epson slugs, run against **staging** with **querysource 5.1.2**.
- G2: S4. A real BotManager agent emits a linked surface that renders and refreshes in the admin UI's `A2UISurface` (Svelte), with the FilterBar active.
- G3: Python↔TS parity. For the same descriptor and params, `execute_sources` and `LinkedLane` produce identical conditions and identical rows.
- G4: Fix the minimal set of core defects that block G1–G3 (§3 M3–M7), with regression tests.
- G5: Pin the workspace to `querysource>=5.1.2` and regenerate `uv.lock`, so CI and the venv agree.

### Non-Goals (explicitly out of scope)
- Anything in FEAT-610's scope: the echarts + grid.js renderer, `polestar_graduates_directory`, grid paging, the pie-slice fix, the wire doc §3.
- `transform.ref` (its publisher has no wiring, F015). Interval refresh beyond one smoke assertion.
- Persisting the `/refresh` params into the stored envelope (the current behaviour is recorded as a gotcha in §7).
- Any write to the **production** database. Every seed and policy targets `env/staging`.
- An admin page that lists persisted surfaces.

---

## 2. Architectural Design

### Overview
The work has two halves.

**(a) Example and harness.** This lives under `examples/agents/a2ui/linked_e2e/`, which the `.gitignore:31` whitelist already covers.
- An aiohttp app mounts QuerySource, AuthHandler, BotManager and the dataplane guard, following the `app.py` mount order.
- An Epson agent uses `QuerysourceToolkit` plus an example TOOL, `build_epson_activity_dashboard`. That TOOL composes a multi-widget, multi-source surface through `builders.build_linked_surface`, which is the only composer able to emit a FilterBar and a join (F011).
- An idempotent staging seed creates the multiquery slug and a demo PBAC policy in an **example-local** policy directory.
- An asserting HTTP runner, `run_e2e.py`, executes S1/S2/S3/S5 and exits non-zero on the first failed assertion.
- The same scenarios run as pytest integration tests marked `staging`, skipped unless `ENV=staging`, plus an offline tier that reuses the FakeQS pattern from `test_linked_surfaces_e2e.py`.

**(b) Core fixes.** These are small and localized:
1. lift the linked-surface envelope from dict tool results into `response.a2ui_envelope`, normalized to the v1.0 wrapper;
2. let the canvas open a tab for linked widget and Column roots, and pass `persistedSurfaceId`;
3. fix the TS drift (`limit`, `_offset:0`, undeclared params in `setParam`, the discarded `serverRefresh` response, `snapshotAt`);
4. validate FilterBar `param.source` and `param.name`;
5. give `PublishSurfaceTool` a guard-backed `LinkedSurfaceService` when one is available;
6. bump the querysource pin and the lock;
7. fix the stale guard-call count in the existing E2E test (3 calls since `ff066c3ae`).

**Dataset** (resolved in proposal §5):
- `epson_field_activity`: columns `day, visits, program, store_id`, placeholders `{firstdate}` and `{lastdate}`.
- `epson_program_targets`: columns `program, target`.
- A seeded multiquery slug, `epson_activity_vs_targets_mq`.

The columns are inferred (F001), so M2 verifies them first.

**Scenarios**

| ID | Name | Flow and assertions |
|---|---|---|
| S1 | Server lane + share + PBAC | Agent → `qs_build_linked_surface` → `publish_surface` → `GET` JSON and `?format=html` (no execution) → `POST /refresh {params:{firstdate,lastdate}}` → mint a share → refresh as the bearer (runs under the owner's pctx) |
| S2 | Join + DSL + FilterBar | The dashboard TOOL emits KPIs (total visits, stores visited, % attainment), a bar of visits by day, and a table of `activity ⋈ targets` on `program` with `transform.ops`. It also emits a date-range FilterBar (`parrot_param`) and a local program FilterBar. Python↔TS parity is checked on the same fixture. |
| S3 | Multiquery | The linked DataTable over `epson_activity_vs_targets_mq` (`is_multiquery`) is checked three ways: with `multi_output`, with the `result` fallback, and with an ambiguous frame. |
| S5 | Tenant route | The same Chart descriptor with `tenant="public"` goes through `/api/v1/{tenant}/queries/{slug}` (browser lane) and through `/refresh` (server lane). The rows must match S1. |
| S4 | Admin chat (manual and automated) | `output_mode=a2ui` renders the linked surface in `A2UISurface`; the FilterBar re-queries, and Refresh uses the server lane. |

S1 negative cases:
- no policy → 403;
- no guard → 403;
- a baked non-recipe surface → 409;
- a concurrent refresh → 409 `stale refresh`;
- an undeclared or locked param → `X-Parrot-Refresh-Warnings`.

S5 exists because querysource 5.1.2 fixed the v1 tenant routes; FEAT-610's F042 verified this live.

### Component Diagram
```
run_e2e.py / pytest -m staging ──HTTP──▶ examples/agents/a2ui/linked_e2e/server.py
   │                                     ├─ QuerySource(5.1.2).setup(app)  → /api/v3, /api/v1/{tenant}/queries
   │                                     ├─ AuthHandler(BasicAuth)         → /api/v1/login
   │                                     ├─ setup_dataplane_guard(policy_dir=example/policies)
   │                                     └─ BotManager + EpsonLinkedAgent(QuerysourceToolkit, build_epson_activity_dashboard)
   │                                            └─ builders.build_linked_surface ─▶ CreateSurface (TOOL origin)
   │                                                  └─ bots/base.py lift (M5) ─▶ response.a2ui_envelope {version, createSurface}
   ├──▶ /api/v1/ui/surfaces (publish, GET json|html, /refresh, /share) ─▶ LinkedSurfaceService ─▶ execute_sources ─▶ QS/MultiQS
   └──▶ admin UI AgentChat ─▶ infographic-tab-builder (M6) ─▶ A2UISurface(persistedSurfaceId) ─▶ LinkedLane (M3)
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `builders.build_linked_surface` | uses | The multi-component composer for S2 (§6) |
| `QuerysourceToolkit` | uses (unchanged API) | `build_linked_surface`, `save_multiquery(allow_write=True)` for the S3 seed |
| `LinkedSurfaceService` / `UISurfacesHandler` | uses | S1 server lane; behaviour unchanged |
| `AbstractBot.ask` tool-result lifting | modifies | M5, a third lift branch |
| `finalize_a2ui_response` | modifies | M5, normalizes the inner CreateSurface into the v1.0 wrapper |
| `_validate_linked_sources` | modifies | M4, FilterBar param validation |
| `PublishSurfaceTool` | modifies | M7, guard-backed service resolution |
| `LinkedLane` / `conditions.ts` / `A2UISurface.svelte` | modifies | M3 drift fixes |
| `infographic-tab-builder.ts` / `InfographicCanvas.svelte` / `types/agent.ts` | modifies | M6 |
| `setup_dataplane_guard` | uses | The policy dir is example-local |

### Data Models
No new core models. The example TOOL's input model:
```python
class EpsonDashboardArgs(BaseModel):
    firstdate: str = "FDOM"      # QS UDF keyword or ISO date
    lastdate: str = "TODAY"
    programs: list[str] | None = None   # initial local FilterBar options; None = derive from rows
    snapshot: bool = True
```

### New Public Interfaces
```python
# examples/agents/a2ui/linked_e2e/dashboard_tool.py  (example-only, not a core API)
async def build_epson_activity_dashboard(firstdate: str = "FDOM", lastdate: str = "TODAY",
                                         programs: list[str] | None = None, snapshot: bool = True) -> dict:
    """Compose the S2 linked dashboard; returns {"a2ui_envelope": <inner CreateSurface>, "artifacts": [{"type": "a2ui_linked_surface", ...}]}."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 querysource pin + lock | yes | Two pyproject edits and `uv lock --upgrade-package querysource` | — |
| M2 staging verification + seed | no | — | Needs staging credentials and human confirmation before any write |
| M3 TS drift fixes | yes | Anchors in §6; mirror `derive_conditions` exactly | — |
| M4 FilterBar param validation + E2E test fix | yes | New issue code `FILTER_PARAM_UNKNOWN_SOURCE` / `FILTER_PARAM_UNDECLARED` | — |
| M5 envelope lifting | no | — | Precedence against the interactive/infographic lifts is a design call (§7) |
| M6 canvas wiring | no | — | Choosing the persisted-id carrier touches message types |
| M7 PublishSurfaceTool guard | yes | Resolution order fixed in the skeleton | — |
| M8 dashboard TOOL + golden + parity | no | — | Composition and parity harness design |
| M9 example server/agent/runner + staging tests | no | — | Integration heavy |
| M10 docs + manual S4 | yes | README sections fixed in §7 | — |

### Module 1: querysource 5.1.2 pin + lock
- **Path**: `packages/ai-parrot/pyproject.toml`, `packages/ai-parrot-tools/pyproject.toml`, `uv.lock`
- **Responsibility**: Raise the pins to `querysource>=5.1.2` in `ai-parrot[db]`, `ai-parrot[integrations]` and `ai-parrot-tools[db]`. Regenerate the lock (querysource 5.1.2; navigator-auth ends at ≥0.28.2 if the resolver wants it). Refresh the stale version docstrings in `parrot_tools/querysource/_qs.py` (it says "4.5.11").
- **Depends on**: —
- **Coordination**: FEAT-610 makes the same pin change. Whichever merges second drops its duplicate hunk.
- **Interface Skeleton**: none (config only).

### Module 2: Staging verification and idempotent seed
- **Path**: `examples/agents/a2ui/linked_e2e/seed_staging.py` (new), `examples/agents/a2ui/linked_e2e/policies/source-epson.yaml` (new), `sdd/state/FEAT-611/findings/F020-staging-slug-definitions.md` (new, evidence)
- **Responsibility**:
  1. With `ENV=staging`, read-only, call `qs_describe_slug` for `epson_field_activity` and `epson_program_targets` and record their SQL, columns and placeholders.
  2. Seed `epson_activity_vs_targets_mq`, a multiquery that joins the two slugs on `program` and has two output frames, `result` and `targets`. It goes through `QuerysourceToolkit(allow_write=True).save_multiquery(..., overwrite=True)`.
  3. Write the demo PBAC policy, then **prove it**. With the policy, `guard.authorize_source` for `query_slug:public:epson_field_activity` / `source:read` must allow; without it, it must deny. Log the evaluated resource and action strings, so that "policy absent" can be told apart from "guard missing" (§9 S5).

  The script refuses to run unless `ENV == "staging"` and the DB name contains `staging`.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # examples/agents/a2ui/linked_e2e/seed_staging.py (new)
  MQ_SLUG = "epson_activity_vs_targets_mq"
  def assert_staging() -> None:
      """Raise SystemExit unless ENV=staging and the configured DBNAME contains 'staging'."""
  async def describe_slugs(slugs: list[str]) -> dict[str, dict]:
      """Read-only qs_describe_slug for each slug; returns {slug: SlugDetail.model_dump()}."""
  async def seed_multiquery(*, overwrite: bool = True) -> dict:
      """Upsert MQ_SLUG via QuerysourceToolkit.save_multiquery (verified: toolkit.py:605); idempotent."""
  ```
  ```yaml
  # policies/source-epson.yaml — resource string inferred (no ResourceType.SOURCE; fallback raw string, NA resources.py:97-110)
  version: "1.0"
  policies:
    - name: demo_allow_epson_linked_sources
      effect: allow
      resources: ["source:query_slug:public:epson_*"]
      actions: ["source:read"]
      subjects: { groups: ["*"] }
      priority: 10
  ```

### Module 3: TS linked-lane drift fixes
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/{conditions.ts,index.ts,fetch.ts}`, `…/canvas/a2ui/A2UISurface.svelte` and the matching `*.test.ts`
- **Responsibility**:
  - `deriveConditions` stops emitting `limit` and emits `_offset` only when it is truthy, as `conditions.py:17-37` does.
  - `setParam` ignores names that are not in `src.params` (it already ignores locked ones).
  - `onUpdate` falls back to the descriptor's `snapshot_at` when there is no live timestamp.
  - `serverRefresh` sends the current param overrides and applies the returned envelope's `dataModel` to `baseDataModel`.
  - Correct the comment at `fetch.ts:48`.
  - `selectFrame` matches Python's `_select_multi_frame` (`query_slug.py:238`). A declared `multi_output` that is missing, or several frames with no selector, throws `FrameSelectionError`. The lane then emits `status:'error'` and keeps the previous snapshot, instead of `ready` with `[]` or silently falling back to `result` (§9 S7).
  - `serverRefresh` surfaces the `X-Parrot-Refresh-Warnings` header in the notices (§9 S3).
  - Establish a real vitest baseline first. This needs Node ≥24 and `pnpm install --frozen-lockfile`.
- **Depends on**: —
- **Interface Skeleton**:
  ```ts
  // linked/conditions.ts (modifies :49-54)
  export function deriveConditions(request: SourceRequest, locked: Record<string, unknown>): Record<string, unknown>;
  /** Mirrors parrot.outputs.a2ui.linked.conditions.derive_conditions: never emits `limit`; `_offset` only when truthy. */
  // linked/index.ts (modifies :220, :167/:171/:197/:207)
  export interface LinkedLane { start(): void; stop(): void; setParam(source: string, name: string, value: unknown): Promise<void>; refreshAll(): Promise<void>; }
  /** setParam: no-op (and console.warn) when `name` ∉ src.params or ∈ src.locked. */
  export function currentParams(lane: LinkedLane): Record<string, Record<string, unknown>>;  // new: overrides for serverRefresh
  // A2UISurface.svelte (modifies serverRefresh :146-153)
  async function serverRefresh(): Promise<void>;  // POST {params: currentParams(lane)}; apply response.envelope.createSurface.dataModel
  ```
  If `LinkedLane` gains a member, the proxy at `A2UISurface.svelte:101-106` must forward it.

### Module 4: FilterBar param validation + stale E2E expectation
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py`, `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py:356`
- **Responsibility**:
  - In `_validate_linked_sources`, walk every `FilterBar` component's `filters[].param`. Emit `FILTER_PARAM_UNKNOWN_SOURCE` when `param.source` is not a declared source, and `FILTER_PARAM_UNDECLARED` when `param.name` is not in that source's `params` or is locked.
  - Fix the E2E assertion to `* 3`: validate, then ensure_snapshot (since `ff066c3ae`), then refresh.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # catalog/__init__.py (modifies _validate_linked_sources, verified :517)
  def _validate_filter_params(envelope: CreateSurface, sources: "LinkedSources", issues: list[dict]) -> None:
      """Append FILTER_PARAM_UNKNOWN_SOURCE / FILTER_PARAM_UNDECLARED issues for FilterBar filters[].param."""
  ```

### Module 5: Linked-envelope lifting + v1.0 normalization
- **Path**: `packages/ai-parrot/src/parrot/bots/base.py`, `packages/ai-parrot/src/parrot/outputs/a2ui/emission.py`
- **Responsibility**:
  - Add `_extract_last_linked_surface_result(tool_calls)`. It returns the envelope from the last successful tool call whose `result` is a dict with `a2ui_envelope` and an artifact of type `a2ui_linked_surface`.
  - In `ask()`, after the interactive and infographic lifts, set `response.a2ui_envelope` when neither of them produced one. **Precedence: interactive > infographic > linked.**
  - `finalize_a2ui_response` wraps a bare inner CreateSurface dict (it has `surfaceId` and `components`, and no `version`) into `{"version":"v1.0","createSurface":…}`.
  - Also set `response.metadata["a2ui_surface_id"]` when the last `publish_surface` call returned a `surface_id`.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # bots/base.py (new method near _extract_last_infographic_result, verified :921)
  def _extract_last_linked_surface_result(self, tool_calls: list | None) -> dict | None:
      """Return the v1.0-wrapped envelope of the last successful linked-surface tool result, else None."""
  # emission.py (modifies finalize_a2ui_response, verified :18)
  def _wrap_create_surface(envelope: dict) -> dict:
      """Wrap a bare CreateSurface dump as {"version": "v1.0", "createSurface": envelope}; idempotent on wrapped input."""
  ```

### Module 6: Admin canvas wiring
- **Path**: `…/canvas/infographic-tab-builder.ts`, `…/canvas/a2ui/a2ui-kind.ts`, `…/canvas/InfographicCanvas.svelte`, `packages/ai-parrot-server/ui/src/lib/types/agent.ts`, `…/canvas/infographic/infographic-types.ts`
- **Responsibility**:
  - `buildInfographicTabData` opens a tab for `output_mode==='a2ui'` when the root is Infographic-like **or** the envelope carries `metadata.extensions.parrot_data_sources`.
  - The message type gains an optional `a2ui_surface_id`. The tab data carries it, and `InfographicCanvas` passes it as `persistedSurfaceId`.
- **Depends on**: M5 (the envelope and surface id reach the client), M3 (serverRefresh behaviour)
- **Interface Skeleton**:
  ```ts
  // a2ui-kind.ts (new export next to hasInfographicRoot, verified :42)
  export function isLinkedSurface(envelope: A2UIEnvelope | undefined): boolean;
  // agent.ts:51 — add: a2ui_surface_id?: string;
  // infographic-types.ts:246/263 — add: persistedSurfaceId?: string;
  ```

### Module 7: PublishSurfaceTool guard resolution
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py`
- **Responsibility**: In the standalone lane, resolve the service in this order:
  1. `self._linked_service`;
  2. `LinkedSurfaceService(guard=self._guard)` when a `guard` kwarg was given;
  3. `LinkedSurfaceService(guard=getattr(self._bot, "_dataplane_guard", None))`;
  4. the current fail-closed default.

  Behaviour with no guard anywhere is unchanged (403).
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # parrot_tools/ui_surfaces.py (modifies __init__ verified :83-91 and :217)
  def __init__(self, bot: Any = None, surface_store: Any = None, agent_id: str | None = None, user_id: str | None = None,
               session_id: str | None = None, linked_service: Any = None, guard: Any = None, **kwargs) -> None: ...
  def _resolve_linked_service(self) -> "LinkedSurfaceService":
      """linked_service > LinkedSurfaceService(guard) > bot._dataplane_guard > LinkedSurfaceService(guard=None)."""
  ```

### Module 8: Epson dashboard TOOL, golden and parity harness
- **Path**: `examples/agents/a2ui/linked_e2e/dashboard_tool.py` (new), `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_epson_dashboard.json` (new golden), `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/parity/epson_dashboard_params.json` (new), `packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py` (new), `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/parity.test.ts` (new) + `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py` (new wrapper)
- **Responsibility**:
  - Compose S2 with `build_linked_surface`. Sources: `activity` (epson_field_activity, params firstdate/lastdate) and `targets` (epson_program_targets). A derived `attainment` source joins `targets` and applies `group_by program → derive attainment=visits/target → sort`.
  - Emit the golden envelope.
  - The TOOL runs `execute_sources(..., pctx=<caller pctx>, guard=<bot._dataplane_guard>)`, so no rows are returned before authorization (§9 S4). A negative test proves an unauthorized source is blocked during the initial build.
  - The TOOL stays thin and example-scoped. It composes descriptors, calls the executor and the builder, and adds no second general-purpose API (§9 S10).
  - Parity: a shared fixture of (descriptor, params, input frames). The Python test asserts `derive_conditions` output and `apply_transform` rows; `parity.test.ts` asserts `deriveConditions` and the TS DSL on the same fixture. The expected values are the same file for both.
- **Depends on**: M3 (the TS conditions fix), M4 (validation must accept the FilterBar)
- **Interface Skeleton**: see §2 New Public Interfaces.

### Module 9: Example server, agent, runner and staging tests
- **Path**: `examples/agents/a2ui/linked_e2e/{server.py,agent.py,run_e2e.py}` (new), `packages/ai-parrot-server/tests/integration/test_linked_e2e_staging.py` (new), `packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py` (new), `pytest.ini` + `packages/ai-parrot-server/pyproject.toml` (register the `staging` marker)
- **Responsibility**:
  - `server.py` mounts, in order:
    1. `QuerySource(lazy=False).setup(app)`;
    2. `setup_dataplane_guard(app, policy_dir=<example>/policies)`;
    3. `BotManager` (registry/db bots off) with `EpsonLinkedAgent`;
    4. `AuthHandler(backends=[BasicAuth])`.
  - `agent.py` defines `EpsonLinkedAgent`, an `Agent` with `QuerysourceToolkit`, `build_epson_activity_dashboard` and `PublishSurfaceTool(bot=self)`.
  - `run_e2e.py` logs in via `/api/v1/login`, runs S1/S2/S3/S5 and prints a pass/fail table.
  - `test_linked_e2e_staging.py` runs the same assertions, marked `staging`; it skips unless `ENV=staging` and `QS_VERSION>=5.1.2`.
  - `test_linked_e2e_offline.py` runs S1/S3/S5 with FakeQS (the pattern in `test_linked_surfaces_e2e.py:203-308`).
- **Depends on**: M1, M2, M4, M5, M7, M8
- **Interface Skeleton**:
  ```python
  # run_e2e.py (new)
  @dataclass
  class ScenarioResult: id: str; passed: bool; detail: str
  async def login(session: aiohttp.ClientSession, base_url: str, user: str, password: str) -> str:
      """POST /api/v1/login with X-Auth-Method: BasicAuth (verified NA auth.py:684); returns the bearer token."""
  async def run_s1(ctx: "E2EContext") -> list[ScenarioResult]: ...
  async def run_s2(ctx: "E2EContext") -> list[ScenarioResult]: ...
  async def run_s3(ctx: "E2EContext") -> list[ScenarioResult]: ...
  async def run_s5(ctx: "E2EContext") -> list[ScenarioResult]: ...
  def main(argv: list[str] | None = None) -> int:
      """Exit code 0 only when every scenario passed."""
  ```

### Module 10: Docs + manual S4
- **Path**: `examples/agents/a2ui/linked_e2e/README.md` (new), `docs/outputs/a2ui-linked-surfaces.md` (append an "E2E validation" section)
- **Responsibility**:
  - README: requirements (`ENV=staging`, querysource ≥5.1.2, Node ≥24 for vitest, demo policy dir), how to run the seed, the server, `run_e2e.py`, `pytest -m staging`, and a step-by-step manual S4 in the admin UI with expected observations.
  - Record the run results in the task completion note.
- **Depends on**: M9, M6

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `conditions.test.ts` (existing, must pass) | M3 | The `limit_offset.json` fixture: no `limit`, `_offset` only when truthy |
| `A2UISurface.linked.test.ts::setParam ignores undeclared` | M3 | An undeclared or locked param triggers no fetch |
| `A2UISurface.linked.test.ts::serverRefresh applies dataModel` | M3 | Mocked 200 response; rows update |
| `test_validate_filterbar_param_unknown_source` / `_undeclared` / `_locked` | M4 | Issue codes emitted |
| `test_linked_surface_end_to_end` (fixed) | M4 | Guard calls `* 3` |
| `test_extract_last_linked_surface_result` | M5 | Dict result with the artifact → wrapped; precedence against interactive/infographic |
| `test_finalize_wraps_bare_create_surface` | M5 | Idempotent wrapping; three cases: direct output, tool-loop output, non-A2UI output unchanged (§9 S1) |
| `fetch.test.ts::selectFrame missing multi_output errors` | M3 | Missing or ambiguous frame → `error` status; the prior snapshot is kept (§9 S7) |
| `test_dashboard_tool_unauthorized_blocked` | M8 | Guard denies → the TOOL raises before returning rows (§9 S4) |
| `infographic-tab-builder.test.ts::linked widget root opens tab` | M6 | Chart/Column roots with `parrot_data_sources` → tab; plain non-Infographic → null |
| `test_publish_surface_tool_guard_resolution` | M7 | The four-step order |
| `test_epson_dashboard_golden` | M8 | The TOOL output equals the golden; `validate_envelope(TOOL)` passes |
| `parity.test.ts` + `test_epson_dashboard_parity` | M8 | The same expected conditions and rows in both lanes |

### Integration Tests
| Test | Description |
|---|---|
| `test_linked_e2e_offline.py::test_s1_server_lane_offline` | Publish → GET → refresh(params) → share → bearer refresh, plus 403/409/warnings, with FakeQS |
| `test_linked_e2e_offline.py::test_s3_multiquery_frames` | `multi_output` / `result` / ambiguous |
| `test_linked_e2e_offline.py::test_s5_tenant_descriptor` | `tenant="public"` goes through `QuerySlugSource(tenant=)` |
| `test_linked_e2e_staging.py::test_s1..s5` (`-m staging`) | The same against staging with querysource 5.1.2 |
| `test_querysource_version_gate` | Asserts `installed_version() >= 5.1.2` |

### E2E Scenarios
- **Policy**: `optional`. Staging depends on credentials and is not part of the merge gate.

| Scenario ID | Tier | Required | Target(s) | Notes |
|---|---|---|---|---|
| `s1-server-lane` | deterministic | no | offline pytest | Node IDs frozen at task time |
| `s3-multiquery` | deterministic | no | offline pytest | |
| `s5-tenant-route` | deterministic | no | offline pytest | |
| `s2-join-dsl-filterbar` | deterministic | no | golden + parity (py + vitest) | |
| `s1..s5` staging | live | no | `pytest -m staging`, `run_e2e.py` | Needs `ENV=staging`; never called deterministic |
| `s4-admin-chat` | exploratory | no (never required) | manual admin UI | Checklist in the README |

---

## 5. Acceptance Criteria

- [ ] `packages/ai-parrot` and `ai-parrot-tools` pin `querysource>=5.1.2`; `uv.lock` locks 5.1.2; `test_querysource_version_gate` passes.
- [ ] The existing linked suites pass on 5.1.2: `tests/outputs/a2ui/linked`, `ai-parrot-tools/tests/querysource`, and `ai-parrot-server/tests/{integration/test_linked_surfaces_e2e.py,handlers/test_ui_surfaces_linked_*}`.
- [ ] Vitest runs for real (not skipped) for `test_vitest_a2ui_linked_*`, and every suite is green after M3.
- [ ] With `ENV=staging`, `run_e2e.py` exits 0. S1, S2, S3 and S5 all pass on querysource 5.1.2, including every S1 negative case.
- [ ] Python and TS produce identical conditions and rows for the S2 parity fixture.
- [ ] A linked surface produced by a real agent chat (`output_mode=a2ui`) opens a canvas tab, renders in `A2UISurface`, the FilterBar re-queries, and Refresh updates the rows (S4 manual checklist, recorded).
- [ ] Nothing writes to production. The seed refuses to run unless the DB is staging, and the demo policy lives only under `examples/agents/a2ui/linked_e2e/policies/`.
- [ ] No breaking change to public APIs: new parameters are optional, and the default behaviour (no guard → 403) is preserved.
- [ ] `ruff check` is clean on the touched Python files.

---

## 6. Codebase Contract

Verified against base commit `ad49b248b` (branch dev, querysource 5.1.2 and navigator-auth 0.28.2 in `.venv`).
Abbreviations:
- `P` = `packages/ai-parrot/src/parrot`
- `T` = `packages/ai-parrot-tools/src/parrot_tools`
- `S` = `packages/ai-parrot-server/src/parrot`
- `C` = `packages/ai-parrot-server/ui/src/lib/components/agents/canvas`
- `QSP` = `.venv/lib/python3.11/site-packages/querysource`
- `NA` = `.venv/lib/python3.11/site-packages/navigator_auth`

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_linked_surface            # P/outputs/a2ui/builders.py:514
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest, ParamSpec, RefreshPolicy, TransformSpec, LinkedSources  # models.py:192,30,19,43,178,226
from parrot.outputs.a2ui.linked.executor import execute_sources, ExecutionOutcome  # executor.py:180,56
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService, LinkedGuardRequired, SnapshotError  # service.py:76,31,35
from parrot.outputs.a2ui.linked.conditions import derive_conditions       # conditions.py:17
from parrot.outputs.a2ui.catalog import validate_envelope                 # catalog/__init__.py:625
from parrot.outputs.a2ui.catalog.base import ProducerOrigin               # catalog/base.py:99
from parrot.outputs.a2ui.emission import finalize_a2ui_response           # emission.py:18
from parrot.outputs.a2ui.serialization import serialize                   # serialization.py:104
from parrot.auth.pbac import setup_dataplane_guard                        # pbac.py:292
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource  # query_slug.py:56
from parrot_tools.querysource.toolkit import QuerysourceToolkit           # toolkit.py:64
from parrot_tools.querysource._qs import installed_version                # _qs.py:67
from parrot_tools.ui_surfaces import PublishSurfaceTool                   # ui_surfaces.py:62
from navigator_auth import AuthHandler                                    # NA/__init__.py:9
from navigator_auth.backends import BasicAuth                             # NA/backends/__init__.py:6
from querysource.services import QuerySource                             # QSP/services.py:66
```

### Existing Class Signatures
```python
# P/outputs/a2ui/builders.py
def build_linked_surface(components: Sequence[dict[str, Any]], sources: Mapping[str, "LinkedDataSource"],
                         frames: Mapping[str, "pd.DataFrame"], *, surface_id: str, snapshot: bool = True,
                         max_snapshot_rows: int = 500, catalog_id: str = DEFAULT_CATALOG_ID) -> CreateSurface  # :514-523
# Raises ValueError if a source has no frame (:540); _validate_axes (:477) checks Chart x/y numeric, DataTable columns, KPICard value.

# P/outputs/a2ui/linked/models.py  (all models extra="forbid", populate_by_name=True — :13)
class ParamSpec: type: str|None; default: Any; required=False; editable=True; accepts_keywords=False     # :19
class SourceRequest: placeholders; filter; fields; ordering; grouping; limit: int|None; offset: int|None  # :30
class RefreshPolicy: policy: Literal["on_mount","manual","interval"]="on_mount"; interval_seconds (>=30)  # :43
class TransformSpec: ops: list[TransformOp]|None; ref: TransformRef|None   # exactly one — :178,186
# DSL ops: Select :81, Rename :87, Filter :93, GroupBy(by, aggregate{col: sum|avg|count|min|max}) :101,
#          Sort(by: list[SortKey]) :114, Limit :120, Derive(name, expr) :137, Pivot :144,
#          Join(with_ alias "with", how inner|left, on: list[JoinKey]) :159, Union_(sources) :167
class LinkedDataSource: kind: Literal["query_slug"]; slug; tenant; is_multiquery=False; multi_output;
    conditions (required); request (required); params: dict[str, ParamSpec]; locked: list[str];
    transform; target (absolute JSON pointer); snapshot_at; snapshot_truncated=False; refresh    # :192-223
class LinkedSources(RootModel[dict[str, LinkedDataSource]])  # key == target root token — :226-235

# P/outputs/a2ui/linked/executor.py
async def execute_sources(sources, *, param_overrides=None, pctx=None, guard=None,
                          max_snapshot_rows=None, max_fetch_rows=5000) -> ExecutionOutcome   # :180-188
# _conditions_for (:153-177): locked/undeclared overrides → ignored; querylimit=min(limit or cap, cap)
# QuerySlugSource(src.slug, prefetch_schema_enabled=False, tenant=, is_multiquery=, multi_output=, principal=) (:201-208)

# P/outputs/a2ui/linked/service.py
class LinkedSurfaceService:
    def __init__(self, *, guard: Any|None, max_fetch_rows=5000, max_snapshot_rows=500)  # :76
    async def validate_for_persistence(self, envelope: CreateSurface, *, owner_pctx)     # :109
    async def ensure_snapshot(self, envelope: dict, *, owner_pctx) -> dict               # :119 (_assert_sources_allowed at :127)
    async def refresh(self, envelope: dict, *, params: Mapping, owner_pctx) -> RefreshOutcome  # :152 (per-source vs broadcast :164-171)
# _assert_sources_allowed (:87-107): guard.authorize_source(pctx, PhysicalResources(source_type="query_slug", source_id=f"{tenant or 'public'}:{slug}"))

# P/outputs/a2ui/linked/conditions.py
def derive_conditions(request: SourceRequest, *, locked: Mapping[str, Any]) -> dict  # :17-37 — never `limit`; `_offset` only if truthy

# P/outputs/a2ui/catalog/__init__.py
def _validate_linked_sources(envelope: CreateSurface, *, origin: ProducerOrigin, issues: list[dict]) -> None  # :517-622 (called :846)

# P/outputs/a2ui/catalog/parrot/filterbar.py — filters[].param {source, name} (both required) :29-71; lowered to
#   ChoicePicker metadata.extensions.parrot_param (:113-115)

# P/outputs/a2ui/emission.py
def finalize_a2ui_response(response: Any) -> None   # :18-45 — takes response.output if dict (:32-34); no v1.0 wrapping

# P/bots/base.py — ask() :984; interactive lift :1491-1495 (_extract_last_interactive_result :867);
#   infographic lift :1522-1536 (_extract_last_infographic_result :921); finalize for A2UI :1596-1598
# tool_call.result for toolkit = raw dict (clients/base.py:1612-1620 unwraps ToolResult; openai_base.py:624)

# T/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):  # :64, tool_prefix="qs"
    def __init__(self, programs=None, allow_write=False, allow_raw_sql=False, allow_external_sources=True,
                 include_sql=True, max_rows=200, forced_conditions=None, dsn=None, multiquery_timeout=600.0, **kwargs)  # :77-88
    async def describe_slug(self, slug: str, dry_run: bool=False, tenant: str|None=None) -> SlugDetail  # :210
    async def build_linked_surface(self, slug, component, request=None, tenant=None, snapshot=True,
                                   surface_id=None, target_key=None, refresh=None, transform=None) -> dict  # :339-349
    #   returns {"a2ui_envelope": <inner CreateSurface dump>, "artifacts": [{"type": "a2ui_linked_surface", "surface_id", "sources", "slug", "tenant"}]} (:400-413)
    async def save_multiquery(self, slug, pipeline: dict, description: str, program=None, overwrite=False) -> SavedSlug  # :605-620

# T/ui_surfaces.py
class PublishSurfaceTool(AbstractTool):  # :62, name="publish_surface"
    def __init__(self, bot=None, surface_store=None, agent_id=None, user_id=None, session_id=None, linked_service=None, **kwargs)  # :83-91
    # standalone lane: service = self._linked_service or LinkedSurfaceService(guard=None)  (:217)

# P/bots/mixins/infographic_authoring.py — publish_surface(...) -> str :442-455; linked path :534-545 uses bot._dataplane_guard

# S/handlers/ui_surfaces.py — class-level @is_authenticated() @user_session() (:313-315)
#   PublishSurfaceRequest :69-93; RefreshSurfaceRequest{params: dict={}} :96-99; MintShareRequest :102-106
#   _pin_save :508-612 (201 {surface_id}); _refresh :617-686 (409 non-refreshable); _refresh_linked :688-736
#   (403 no guard/deny; CAS 409 "stale refresh"; X-Parrot-Refresh-Warnings); _mint_share :787-819
# Routes (S/manager/manager.py:2334-2338): /api/v1/ui/surfaces[/{id}[/refresh|/share[/{token}]]]; mirror /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id} (:2325)
# BotManager guard: on_startup _setup_dataplane_guard (:2304, :2707-2731) sets bot._dataplane_guard for bots loaded at startup

# P/auth/pbac.py
def setup_dataplane_guard(app, *, policy_dir: str="policies", cache_ttl: int=30) -> Optional[DataPlanePolicyGuard]  # :292-351 (default DENY)
# guard evaluates check_access(ctx, "source", f"{source_type}:{source_id}", "source:read", env) (P/auth/dataplane_guard.py:286-291)

# QSP (5.1.2)
QS.__init__(self, slug='', conditions=None, request=None, loop=None, *, tenant=None, definition=None, principal=None, residual=None, **kwargs)  # queries/qs.py:56-68
MultiQS.__init__(self, slug=None, queries=None, files=None, query=None, conditions=None, request=None, loop=None, user_session=None, *, tenant=None, definition=None, principal=None, **kwargs)  # queries/multi/__init__.py:106-121
# Tenant routes: /api/v1/{tenant}/queries/{slug}, alias /api/v1/queries/{tenant}/{slug} (services.py:381-418); v3 has no tenant route.
# qs_start → initialize_tenants() scans information_schema; failure aborts startup (services.py:486-522).
# NA: POST /api/v1/login → api_login (auth.py:684-685); BasicAuth password key "password".
```

```ts
// C/a2ui/linked/index.ts
export interface LinkedLane { start(); stop(); setParam(source, name, value): Promise<void>; refreshAll(): Promise<void>; }  // :54-61
export function createLinkedLane(sources, opts: LinkedLaneOptions): LinkedLane   // :140; opts {baseUrl, headers(), transformsBase, onUpdate}
// C/a2ui/linked/fetch.ts — selectFrame :22 (array | multi_output | 'result' | sole key | []); fetchSource :42 (body {...conditions, querylimit})
// C/a2ui/A2UISurface.svelte — props { envelope: A2UIEnvelope; persistedSurfaceId?: string; transformsBase?: string } (:37); lane proxy :100-107
// C/a2ui/a2ui-types.ts:75-78 — A2UIEnvelope = { version: "v1.0"; createSurface }
// C/a2ui/a2ui-kind.ts:18,42-46 — INFOGRAPHIC_LIKE_ROOTS = {'Infographic','Report'}; hasInfographicRoot
// ui/src/lib/features.ts:31 — features.a2ui = __AGENTCHAT_A2UI__ (true unless PUBLIC_AGENTCHAT_A2UI=false|0)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `build_epson_activity_dashboard` | `build_linked_surface` + `execute_sources` | function calls | builders.py:514, executor.py:180 |
| `seed_staging.seed_multiquery` | `QuerysourceToolkit.save_multiquery` | method call | toolkit.py:605 |
| `server.py` guard | `setup_dataplane_guard(app, policy_dir=…)` | on_startup, before BotManager's own hook | pbac.py:292, manager.py:2304 |
| `EpsonLinkedAgent` publish | `PublishSurfaceTool(bot=self)` → mixin `publish_surface` | delegation | ui_surfaces.py:131-142 |
| `_extract_last_linked_surface_result` | `ask()` lift chain | after :1522 block | base.py:1522-1536 |
| `isLinkedSurface` | `buildInfographicTabData` | guard at :60 | infographic-tab-builder.ts:60 |

### Does NOT Exist (Anti-Hallucination)
- ~~A multi-widget/dashboard helper in `QuerysourceToolkit`~~: `build_linked_surface` is one component and one source (toolkit.py:339-455). FEAT-610 may add one; this spec does not depend on it.
- ~~A `multi_output` param on `qs_build_linked_surface`~~.
- ~~`LinkedLane.refreshSource`~~ (FEAT-610 plans it) · ~~an `on_param_change` refresh policy~~.
- ~~Lifting of dict tool results in `bots/base.py`~~ · ~~a persisted surface id on messages or tabs~~ · ~~an admin page that lists surfaces~~.
- ~~Wiring of `PublishSurfaceTool(linked_service=…)`~~ or ~~`bot._linked_surface_service`~~.
- ~~FilterBar param validation~~ · ~~Python execution of `transform.ref`~~.
- ~~A `query_slug` / `source:read` policy in `policies/`~~ · ~~`ResourceType.SOURCE` in navigator_auth~~.
- ~~A `staging` pytest marker~~ · ~~`examples/agents/a2ui/linked_e2e/`~~ · ~~a v3 tenant query route~~ · ~~a sqlite provider in QS~~.
- ~~`package-lock.json`~~: the UI is pnpm-only (`pnpm-lock.yaml`).

### Edit Sites (Blueprint Anchors)
Verified against: `ad49b248b`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | `    "querysource>=4.1.11",` (db and integrations extras) | :225, :688 | 2 |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | `db = ["querysource>=5.1.1", "psycopg-binary>=3.2"]` | :77 | 1 |
| `uv.lock` | MODIFY (regenerate) | `name = "querysource"` / `version = "5.1.1"` | :13046-13047 | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py` | MODIFY | docstring mentioning `4.5.11` | :68 | (unverified — check before use) |
| `C/a2ui/linked/conditions.ts` | MODIFY | `out['limit'] = request.limit;` / `out['_offset'] = request.offset;` | :50, :53 | 1 / 1 |
| `C/a2ui/linked/index.ts` | MODIFY | `if (!src \|\| failed.has(source) \|\| (src.locked ?? []).includes(name)) return;` | :220 | 1 |
| `C/a2ui/linked/index.ts` | MODIFY | `snapshotAt: null` | :167, :171, :197, :207 | 4 |
| `C/a2ui/A2UISurface.svelte` | MODIFY | `async function serverRefresh(): Promise<void> {` / `body: JSON.stringify({ params: {} }),` | :146, :151 | 1 / 1 |
| `C/a2ui/A2UISurface.svelte` | MODIFY | `data as of {status.snapshotAt ?? 'never'}` | :171, :175 | 2 |
| `C/a2ui/linked/fetch.ts` | MODIFY | comment "never emits limit" | :48 | 1 |
| `P/outputs/a2ui/catalog/__init__.py` | MODIFY | `        if source.transform is not None and source.transform.ref is not None:` | :610 | 1 |
| `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py` | MODIFY | `        assert allow_guard.calls == [("query_slug", "public:epson_field_activity")] * 2` | :356 | 1 |
| `P/bots/base.py` | MODIFY | `infographic_envelope = self._extract_last_infographic_result(getattr(response, "tool_calls", None))` | :1522 | 1 |
| `P/bots/base.py` | MODIFY | `if interactive_envelope is not None or infographic_envelope is not None:` | :1579 | 1 |
| `P/outputs/a2ui/emission.py` | MODIFY | `    response.a2ui_envelope = envelope` | :41 | 1 |
| `T/ui_surfaces.py` | MODIFY | `        linked_service: Any = None,` / `            service = self._linked_service or LinkedSurfaceService(guard=None)` | :90, :217 | 1 / 1 |
| `C/infographic-tab-builder.ts` | MODIFY | `if (message.output_mode === 'a2ui' && !hasRoot) return null;` | :60 | 1 |
| `C/InfographicCanvas.svelte` | MODIFY | `<A2UISurface envelope={tabData?.envelope} />` | :353 | 1 |
| `packages/ai-parrot-server/ui/src/lib/types/agent.ts` | MODIFY | `a2ui_envelope?` | :51 | (re-grep at task time) |
| `pytest.ini` | MODIFY | `markers =` block | :1-12 | (re-grep at task time) |
| `.gitignore` | MODIFY (only if an `.html` is added) | `examples/**/*.html` | :37 | 1 |
| `examples/agents/a2ui/linked_e2e/{server,agent,dashboard_tool,seed_staging,run_e2e}.py`, `policies/source-epson.yaml`, `README.md` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_epson_dashboard.json`, `…/fixtures/parity/epson_dashboard_params.json` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py`, `packages/ai-parrot-server/tests/integration/test_linked_e2e_{offline,staging}.py`, `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py`, `C/a2ui/linked/parity.test.ts` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- The mount order from `app.py`, as reused by FEAT-610: QuerySource(lazy=False) → PBAC → BotManager → AuthHandler.
- FakeQS / fake guard / fake QueryModel from `test_linked_surfaces_e2e.py:203-308` for the offline tier.
- Epson envelopes `linked_dashboard_join.json` / `linked_multiquery_public.json` as the shape references.
- Svelte 5 runes only; tests next to the code; `pnpm` only.
- An example TOOL output carries the same `{"a2ui_envelope", "artifacts":[{"type":"a2ui_linked_surface"}]}` shape as the toolkit, so M5's lift covers both.

### Known Risks / Gotchas
- **Startup needs a real Postgres.** Since 5.1.x, public slugs resolve through `DefinitionRepository`, and `initialize_tenants()` failing aborts app startup. The offline tier must patch QS classes and must not boot `QuerySource.setup`.
- **`QuerySlugSource` lets `DataNotFound` escape.** An empty date range becomes a `data_stage` 502 in the linked lanes. S2 must use ranges known to have data (from M2's findings). Whether an empty result should be `[]` is §8 Q2.
- **`/refresh` params are not persisted.** A later refresh with `{}` reverts to the stored placeholders. M3's `serverRefresh` therefore always re-sends the current overrides.
- **The guard is only attached to bots loaded at startup** (manager.py:2728-2730). The example registers its agent before `on_startup` runs.
- **The PBAC resource string is inferred.** Navigator-auth has no `ResourceType.SOURCE`, so M2 must prove the policy actually allows the call (a 200) and that removing it yields a 403.
- **Share-token bearers still need an authenticated session**, because the handler decorators are at class level. S1 asserts the documented behaviour rather than assuming anonymous access.
- **Vitest has never run.** M3 starts by recording the baseline, which may be red before any change.
- **Conflict with FEAT-610** on `linked/index.ts` (it adds `refreshSource`) and on the pin. Rebase whichever lands second.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `querysource` | `>=5.1.2` | Latest release: JSONB `@>`, working tenant routes, `/api/v1/queries/{tenant}/{slug}` alias |
| `navigator-auth` | `>=0.28.2` (resolver) | Pulled by querysource 5.1.2 |
| Node | `>=24` | `ui/package.json` engines; needed for the vitest baseline |
| pnpm | `9.15.9` | `packageManager` |

---

## 8. Open Questions

- [x] Coverage scope. *Resolved in proposal*: all four (server lane + share + PBAC, join + DSL + FilterBar, multiquery, admin chat). S5 was added after querysource 5.1.2 fixed the tenant routes.
- [x] Dataset. *Resolved in proposal*: Epson (`epson_field_activity` + `epson_program_targets`).
- [x] Environment. *Resolved in proposal*: staging (`env/staging`); no production writes.
- [x] querysource version. *Resolved in proposal (2026-09-28, Javier)*: test on **5.1.2**. The venv is upgraded, and the pins and lock are bumped by M1.
- [ ] Q1: The real definitions of the `epson_*` slugs in staging, and staging credentials for the E2E user. *Owner: Javier (M2)*
- [ ] Q2: Should `QuerySlugSource` map `DataNotFound` to empty rows for linked lanes? This changes dataset_manager semantics, so it is out of scope unless approved. *Owner: Javier / Jesús*
- [ ] Q3: Merge order with FEAT-610, for the pin and for `linked/index.ts`. *Owner: Javier + Jesús*
- [ ] Q4: Should the core `QuerysourceToolkit.build_linked_surface` also execute under the caller's pctx and the dataplane guard? Today it uses `pctx=None, guard=None` (toolkit.py:386). This spec only hardens the example TOOL, because the core change alters behaviour for every agent. *Owner: Javier / Jesús* (escalated from §9 S4)

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: completed · Transcript: `sdd/state/FEAT-611/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | One canonical linked-surface envelope boundary (architecture) | CONFIRM | Matches F014 blockers 4 and 5; wrap at `finalize_a2ui_response`; test 3 output paths | §3 M5, §4 |
| S2 | Route linked surfaces through a generic canvas path (architecture) | CONFIRM | Verified `infographic-tab-builder.ts:60` rejects widget/Column roots | §3 M6 |
| S3 | Carry the persisted surface id; consume refresh responses (api) | CONFIRM | `serverRefresh` discards the response (A2UISurface.svelte:146-153); warnings header added | §3 M3, M5, M6 |
| S4 | Authorize execution before returning rows (risk) | CONFIRM + ESCALATE | Verified toolkit.py:386 `pctx=None, guard=None`. The example TOOL is hardened; the core toolkit change is escalated | §3 M8, §8 Q4 |
| S5 | Verify the exact PBAC resource/action (risk) | CONFIRM | The resource string is inferred (no `ResourceType.SOURCE`); M2 proves allow/deny and logs the evaluated strings | §3 M2, §7 |
| S6 | One conformance fixture for Python/TS conditions (testing) | CONFIRM | Already the M8 design; extended to ignored/locked params | §3 M8 |
| S7 | Identical multiquery frame selection across lanes (api) | CONFIRM | Verified divergence: Python raises (query_slug.py:238), TS falls back to `result`/`[]` (fetch.ts:22-40) | §3 M3, §4 |
| S8 | Validate FilterBar bindings at envelope validation (api) | CONFIRM | Already M4; locked names are an explicit issue code | §3 M4 |
| S9 | Separate the fake tier from the gated staging verdict (testing) | CONFIRM | Already M9 (offline + `-m staging`); the staging suite refuses non-staging targets | §3 M9 |
| S10 | Keep the Epson TOOL thin and example-scoped (alternative) | CONFIRM | Consistent with the M8 design | §3 M8 |

Summary: **10** confirmed (1 also escalated) · **0** rejected · **1** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-611-a2ui-linked-e2e-parallel`, from `origin/dev`. The coder engine gives each task a sub-worktree.
- **Module dependency graph**:
  - M6 → M5, because it consumes `a2ui_envelope` and `a2ui_surface_id`.
  - M6 → M3, because it relies on the `serverRefresh` contract.
  - M8 → M3, because the parity test needs the TS conditions fix.
  - M8 → M4, because validation must accept the FilterBar.
  - M2 → M1, because the seed runs on 5.1.2.
  - M9 → M1, M2, M4, M5, M7, M8.
  - M10 → M9, M6.
  - M1, M3, M4, M5 and M7 have no edges between them, so they can run concurrently.
- **Shared files**: `A2UISurface.svelte` (M3, M6). `linked/index.ts` (M3 only). `bots/base.py` (M5 only).
- **Exclusive resources**:
  - M1 regenerates `uv.lock` (`parallel: false`).
  - M3 installs Node 24 and `node_modules` for the UI (a local environment step).
  - M2 writes to staging (needs human confirmation).
- **Cross-feature dependencies**: none are hard. Coordinate with FEAT-610 (§8 Q3).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-28 | Javier León | Initial spec from the accepted FEAT-611 proposal; querysource 5.1.2 requirement; S5 tenant route |
