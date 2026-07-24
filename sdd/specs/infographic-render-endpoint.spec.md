---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Infographic Render Endpoint — Deterministic Render-as-a-Service

**Feature ID**: FEAT-327
**Date**: 2026-07-24
**Author**: jesuslara
**Status**: draft
**Target version**: 0.26.x
**Brainstorm**: `sdd/proposals/infographic-render-endpoint.brainstorm.md` (Recommended Option A; all 6 open questions resolved)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-326 gave ai-parrot the deterministic infographic machinery — `SectionDescriptor`
(machine-enforced section → data contract), the **data-splice** render mode
(`InfographicToolkit.render_data_template`), and `ArtifactStore` persistence — but it is only
reachable *in-process* (a parrot agent composed with `InfographicAuthoringMixin`, or direct
toolkit use).

**Any agent** (external frameworks, remote services, A2A peers, scripts) should be able to
send over HTTP: (1) a list of datasets (dataframes or JSON data), (2) a selected
pre-registered template, and (3) instructions describing how to fill the template's areas —
and get back a rendered infographic, **deterministically** (no LLM anywhere in the path),
through the current infographic API surface (`InfographicTalk`, routes under
`/api/v1/agents/infographic/...`). Today that surface is LLM-driven only
(`POST /api/v1/agents/infographic/{agent_id}` → `bot.get_infographic()`); there is no
deterministic render route.

### Goals

- G-1: **Deterministic render route** `POST /api/v1/agents/infographic/render` on the
  existing `InfographicTalk` handler — no `{agent_id}` path segment, no bot, no LLM. Same
  datasets + template + descriptor ⇒ same HTML (modulo artifact ids/timestamps).
- G-2: **Instructions = FEAT-326 `SectionDescriptor`** embedded in the request; fail-fast
  validation (every deficit enumerated) BEFORE rendering.
- G-3: **Three dataset transports**: inline JSON `records`, pandas `split` orientation, and
  multipart **Parquet/CSV** parts (parquet preserves dtypes via `pyarrow`).
- G-4: **Validator adapter** (resolved in brainstorm): `validate_descriptor_datasets` gains an
  adapter accepting ad-hoc `{name: DataFrame}` dicts AND (possibly) named references into the
  python tool's `locals` (`PythonPandasTool.df_locals` / `locals_dict`) — ONE validation gate
  for the HTTP endpoint and the in-process authoring path.
- G-5: **Templates pre-registered only** (by name via `template_dirs` or the existing
  template-registration route). No inline template HTML.
- G-6: **Negotiated response**: `Accept: text/html` → the HTML; `application/json` → persisted
  artifact reference + URL (reuse `_negotiate_accept`).
- G-7: **Sync + optional async**: `async=true` ⇒ `202` + job id +
  `GET /api/v1/agents/infographic/render/jobs/{job_id}` polling. Job store: **Redis**
  (multi-worker; resolved). Terminal jobs expire after **1 day** (Redis TTL; resolved).
- G-8: **Body cap 50 MB** (configurable; resolved) → `413` when exceeded.
- G-9: **`pyarrow` declared as a direct (non-transitive) dependency** of the appropriate
  package (resolved).
- G-10: HTTP-only v1 — no parrot-side client tool (in-framework agents already have the
  toolkit/mixin locally).

### Non-Goals (explicitly out of scope)

- **Inline template HTML in the payload** — stored-XSS vector; breaks the trusted-template
  model (resolved decision).
- **A dedicated new handler class** — rejected in brainstorm (Option B); the route extends
  `InfographicTalk`.
- **Recipe-based-only API** (brainstorm Option C rejected: FEAT-324 recipes fetch from
  DatasetManager sources, not caller payloads) and **MCP tool transport** (Option D — natural
  follow-up feature, not v1).
- **Parrot-side HTTP client tool** for in-framework agents (resolved: HTTP-only v1).
- **LLM involvement of any kind** in the render path.

---

## 2. Architectural Design

### Overview

Extend `InfographicTalk` (ai-parrot-server) with a bot-less deterministic branch:

- `POST /api/v1/agents/infographic/render` — accepts **JSON** (small/medium data) or
  **multipart** (large dataframes): a `RenderRequest` model carrying `datasets`
  (name → inline `records`/`split` payload, or references to multipart parquet/CSV parts),
  `template` (registered name), `descriptor` (embedded `SectionDescriptor` — reused, not
  redefined), optional `theme`, `marker_id`, attribution (`agent_id`, `session_id`),
  `persist` (default `true`), `async` (default `false`).
- Flow: decode datasets → **validator adapter** wraps the ad-hoc `{name: DataFrame}` dict and
  runs FEAT-326 `validate_descriptor_datasets` + `validate_payload_shape` (deficits aggregate
  to ONE `422`) → assemble payload per section targets → `render_data_template(...)`
  (data-splice) or `render_template(...)` (jinja) per `descriptor.mode`, on a **server-owned**
  toolkit instance (configured `template_dirs` + `ArtifactStore`, NOT bot-bound) → persist
  (awaited — the caller wants the reference back, unlike the fire-and-forget
  `_auto_save_infographic_artifact` used by the LLM path) → negotiated response.
- **Attribution** (resolved): `user_id` from the authenticated session; `agent_id`/
  `session_id` from the body; system defaults when absent.
- **Async mode** (resolved): `202` + `{job_id}`; job state in **Redis** (same
  `redis.asyncio` + `REDIS_HISTORY_URL` pattern as `parrot/memory/redis.py`), so polling
  works regardless of which worker executed the render; render runs as an `asyncio` task;
  terminal jobs carry a **1-day TTL**; a max-runtime watchdog transitions orphaned `running`
  jobs to `failed`.
- **Artifact URL** in the JSON response (resolved: evaluated during spec development):
  produced via the existing `ArtifactStore.get_public_url()` (presigned overflow URL,
  `artifacts.py:177`). NOTE: it raises for inline (non-offloaded) artifacts — rendered HTML
  documents of real size exceed the 200 KB inline threshold and offload, but the implementer
  must handle the small-artifact inline case (return a deeplink/handler route or omit `url`
  with an explanatory field; verify local-backend presigned support — see §8).

**Route-matching constraint**: the literal `render` segment must be registered so aiohttp
matches it BEFORE the existing `'/api/v1/agents/infographic/{agent_id}'` pattern
(`manager/manager.py:1845`).

### Component Diagram

```
Any HTTP caller (external agent / service / script)
        │  POST /api/v1/agents/infographic/render   (JSON | multipart)
        ▼
InfographicTalk (existing handler, new bot-less branch)
  ├─ RenderRequest (Pydantic)  ── datasets: records | split | parquet/csv parts (≤ 50 MB total)
  ├─ Dataset decoding ──► {name: DataFrame}
  ├─ AdhocDatasetAdapter ──► validate_descriptor_datasets + validate_payload_shape (FEAT-326)
  │        (also wraps PythonPandasTool.df_locals for the in-process path)
  ├─ sync ──► InfographicToolkit.render_data_template / render_template (server-owned instance)
  │              └─► ArtifactStore.save_artifact (awaited) ──► get_public_url()
  │                        └─► negotiated response: text/html → HTML · application/json → {artifact_id, url, ...}
  └─ async=true ──► 202 {job_id} ──► Redis job store (1-day TTL, watchdog)
                         ▲
        GET /api/v1/agents/infographic/render/jobs/{job_id}
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `InfographicTalk` (`packages/ai-parrot-server/src/parrot/handlers/infographic.py`) | modifies | render dispatch branch + request decoding + job polling; LLM path untouched |
| Route registration (`packages/ai-parrot-server/src/parrot/manager/manager.py:1829-1845`) | modifies | 2 new routes; literal `render` before `{agent_id}` |
| `parrot/tools/infographic_sections.py` (FEAT-326) | extends | validator ADAPTER: ad-hoc `{name: DataFrame}` dicts + python-tool `locals` references (resolved) |
| `parrot/tools/infographic_toolkit.py` (FEAT-326) | uses | `render_data_template` (line 625) / `render_template`; server-owned instance |
| `parrot/tools/pythonpandas.py` (`PythonPandasTool`) | uses (adapter source) | `df_locals` (line 122) / `locals_dict` kwarg (lines 128-130) |
| `parrot/helpers/infographics.py` | uses | template existence checks (`get_template`:35) |
| `parrot/storage/` (`ArtifactStore`) | uses | awaited persistence + `get_public_url` (artifacts.py:177) |
| Redis (`redis.asyncio`, `REDIS_HISTORY_URL` from `parrot/conf.py`) | depends on | job-store backend (resolved); pattern of `parrot/memory/redis.py:10-29` |
| `pyarrow` | depends on (declared) | parquet decoding; MUST become a direct dependency (resolved) |

### Data Models

```python
# NEW — server-side request/response models (names indicative; no implementation here).

class InlineDataset(BaseModel):
    """One dataset transported inline in the JSON body."""
    orient: Literal["records", "split"]
    data: Any                      # records: list[dict]; split: {"columns": [...], "data": [...]}

class RenderRequest(BaseModel):
    """Body of POST /render (JSON body, or the `request` part of a multipart body)."""
    datasets: dict[str, InlineDataset | None]   # None ⇒ hydrated from multipart part `dataset:<name>`
    template: str                               # pre-registered name ONLY
    descriptor: SectionDescriptor               # FEAT-326 model, reused — NOT redefined
    theme: Optional[str] = None
    marker_id: str = "report-data"
    agent_id: Optional[str] = None              # attribution (system default when absent)
    session_id: Optional[str] = None
    persist: bool = True
    async_: bool = Field(default=False, alias="async")

class RenderResponse(BaseModel):
    """application/json response for a completed render."""
    artifact_id: str
    url: Optional[str]                          # get_public_url(); see inline-artifact note
    template: str
    sections_validated: int
    persisted: bool
    timings: dict[str, float]

class RenderJob(BaseModel):
    """Redis-stored job record (1-day TTL on terminal states)."""
    job_id: str                                 # uuid4
    status: Literal["pending", "running", "done", "failed"]
    result: Optional[RenderResponse] = None
    error: Optional[dict] = None
    created_at: str
    deadline: str                               # max-runtime watchdog

# NEW — core-side adapter (parrot/tools/infographic_sections.py):
class AdhocDatasetAdapter:
    """Duck-typed DatasetManager stand-in for the FEAT-326 validation gate.

    Wraps `{name: DataFrame}` dicts (HTTP endpoint) or a PythonPandasTool
    locals namespace (in-process path) and exposes get_dataset_entry(name)
    returning an object with a `.columns` attribute, or None when unknown —
    exactly the duck-type validate_descriptor_datasets documents."""
```

### New Public Interfaces

```python
# parrot/tools/infographic_sections.py — the adapter (core, reusable by mixin AND server)
class AdhocDatasetAdapter:
    def __init__(self, frames: Mapping[str, "pd.DataFrame"] | None = None,
                 repl_locals: Mapping[str, Any] | None = None) -> None: ...
    def get_dataset_entry(self, name: str) -> Optional[Any]: ...   # entry.columns duck-type

# HTTP surface (ai-parrot-server):
#   POST /api/v1/agents/infographic/render                 → 200 (negotiated) | 202 | 4xx
#   GET  /api/v1/agents/infographic/render/jobs/{job_id}   → 200 | 404
```

---

## 3. Module Breakdown

### Module 1: Validator adapter (core)
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_sections.py`
- **Responsibility**: `AdhocDatasetAdapter` over `{name: DataFrame}` dicts and
  `PythonPandasTool` locals (`df_locals`/`locals_dict` — DataFrame values only; non-frame
  locals are ignored/rejected explicitly). Satisfies the documented duck-type of
  `validate_descriptor_datasets` (entry with `.columns`, `None` when unknown). Export it.
- **Depends on**: existing FEAT-326 gate (unchanged semantics).

### Module 2: Render request models + dataset decoding (server)
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/infographic.py` (+ a sibling
  module if the handler file grows unwieldy, e.g. `handlers/infographic_render.py` helpers)
- **Responsibility**: `RenderRequest`/`RenderResponse`/`RenderJob` models; decoding
  `records`/`split` inline payloads and multipart parquet (`pyarrow`) / CSV parts into
  DataFrames; **50 MB total body cap** (configurable) enforced pre-buffering where the
  transport allows → `413`; malformed part → `400` naming the part.
- **Depends on**: Module 1 (descriptor import); `pyarrow` (Module 5 declares it).

### Module 3: Deterministic render route (sync path)
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/infographic.py` +
  `packages/ai-parrot-server/src/parrot/manager/manager.py`
- **Responsibility**: dispatch branch for `render` (no bot lookup); template existence check
  (404); adapter + FEAT-326 gates (422 with full deficit list); payload assembly per section
  targets; server-owned `InfographicToolkit` (data-splice via `render_data_template`, jinja
  via `render_template`); awaited persistence with session `user_id` + body attribution +
  system defaults; negotiated response (HTML / `RenderResponse` with `get_public_url`,
  inline-artifact fallback); route registration BEFORE `{agent_id}`.
- **Depends on**: Modules 1-2.

### Module 4: Async job subsystem
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/infographic.py` + a small
  `handlers/render_jobs.py` (or equivalent) for the Redis job store
- **Responsibility**: `async=true` → `202 {job_id}`; Redis job store using `redis.asyncio`
  with `REDIS_HISTORY_URL` (pattern: `parrot/memory/redis.py:10-29`); render as `asyncio`
  task; polling route `GET .../render/jobs/{job_id}` (404 unknown/expired); **1-day TTL** on
  terminal jobs; max-runtime watchdog flips orphaned `running` → `failed`.
- **Depends on**: Module 3.

### Module 5: Dependency declaration, tests, docs
- **Path**: the appropriate `pyproject.toml` (declare `pyarrow` explicitly — resolved),
  `packages/ai-parrot-server/tests/` (or the verified server-test location), `docs/`
- **Responsibility**: `pyarrow` as a direct dependency; endpoint integration tests (all three
  transports, negotiation, async round-trip, error taxonomy: 400/404/413/422); docs page for
  the render API (request/response examples, limits, job lifecycle).
- **Depends on**: Modules 1-4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_adapter_wraps_frames_dict` | 1 | `get_dataset_entry` returns `.columns` entry; unknown → None |
| `test_adapter_wraps_repl_locals` | 1 | DataFrame locals exposed; non-frame locals not treated as datasets |
| `test_adapter_satisfies_validation_gate` | 1 | `validate_descriptor_datasets(descriptor, adapter)` passes/raises identically to DatasetManager path |
| `test_render_request_records_and_split` | 2 | Inline decodings → expected DataFrames |
| `test_multipart_parquet_and_csv_parts` | 2 | Part named `dataset:<name>` hydrates; dtypes preserved (parquet) |
| `test_body_cap_413` | 2 | >50 MB → 413 without full buffering |
| `test_malformed_part_400` | 2 | Broken parquet/CSV → 400 naming the part |
| `test_render_unknown_template_404` | 3 | Unregistered template name → 404 |
| `test_render_deficits_422_aggregated` | 3 | Missing dataset + missing columns + shape mismatch in ONE 422 |
| `test_render_html_negotiation` | 3 | `Accept: text/html` → HTML body; JSON default → `RenderResponse` |
| `test_render_persists_awaited_with_attribution` | 3 | session user_id + body agent_id/session_id + system defaults |
| `test_render_route_not_swallowed_by_agent_id` | 3 | `render` literal wins over `{agent_id}` |
| `test_async_202_and_poll_roundtrip` | 4 | 202 → pending/running → done with result |
| `test_job_ttl_one_day_and_404_after_expiry` | 4 | TTL set on terminal state; expired → 404 |
| `test_watchdog_flips_orphaned_running_to_failed` | 4 | deadline passed → failed with structured error |
| `test_pyarrow_declared_dependency` | 5 | `pyarrow` appears in the package's declared deps |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_render_budget_variance_json` | Inline records → data-splice render of the budget_variance template → HTML + persisted artifact |
| `test_e2e_render_multipart_parquet` | Parquet part with dtypes (dates) → identical deterministic output on repeat call |
| `test_e2e_async_multiworker_poll` | Job created by one app instance, polled through the shared Redis store |

### Test Data / Fixtures
```python
@pytest.fixture
def render_app():
    """aiohttp test app with InfographicTalk routes registered (render before {agent_id}),
    server-owned toolkit with tmp template_dirs, sqlite+local-overflow ArtifactStore."""

@pytest.fixture
def fake_redis_jobstore():
    """Redis test double (or fakeredis) for the job store."""

@pytest.fixture
def sample_frames():
    """{name: DataFrame} dict matching the budget_variance descriptor sections."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ -v` on the affected test paths)
- [ ] All integration tests pass (JSON, multipart-parquet, async multi-worker)
- [ ] **Deterministic**: no LLM call anywhere in the render path; same inputs ⇒ same HTML
  (modulo artifact ids/timestamps), demonstrated by a repeat-call test
- [ ] Instructions are the FEAT-326 `SectionDescriptor` (reused model, never redefined);
  validation is fail-fast and enumerates EVERY deficit in one 422
- [ ] **Adapter** (resolved): `validate_descriptor_datasets` accepts ad-hoc
  `{name: DataFrame}` dicts and `PythonPandasTool` locals references through
  `AdhocDatasetAdapter`, with identical semantics to the DatasetManager path
- [ ] All three dataset transports work: inline `records`, `split`, multipart parquet/CSV;
  parquet preserves dtypes
- [ ] Templates resolve by pre-registered name only; inline template HTML is rejected
- [ ] Response is content-negotiated: `text/html` → HTML; `application/json` →
  `RenderResponse` with artifact reference + URL (via `get_public_url`, with a defined
  inline-artifact fallback)
- [ ] Route registered without `{agent_id}`; existing generate/templates/themes routes
  unchanged (no breaking API change)
- [ ] **Async mode** (resolved): `async=true` → 202 + job id; polling route returns job
  state; job store is **Redis** and works across workers
- [ ] **Job TTL = 1 day** on terminal jobs (resolved); expired job → 404; watchdog flips
  orphaned `running` jobs to `failed`
- [ ] **Body cap 50 MB** (configurable; resolved) → 413
- [ ] **`pyarrow` is a declared direct dependency** (resolved) — verified by a test or CI check
- [ ] Documentation updated in `docs/` (API examples, limits, job lifecycle)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All references re-verified 2026-07-24 on `dev` (post FEAT-326 merge `481aec65a`).

### Verified Imports
```python
from parrot.tools import SectionDescriptor            # lazy export, tools/__init__.py:245,266
from parrot.helpers.infographics import get_template  # core pkg: packages/ai-parrot/src/parrot/helpers/infographics.py
from redis.asyncio import Redis                        # pattern: parrot/memory/redis.py:4
from parrot.conf import REDIS_HISTORY_URL              # imported by parrot/memory/redis.py:7 as ..conf
import pyarrow                                         # 25.0.0 importable; MUST become declared dep (Module 5)
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/infographic.py
_GENERATE_RESERVED_KEYS = frozenset({...})                       # line 39
class InfographicTalk(AgentTalk):                                # line 57
    async def post(self) -> web.Response: ...                    # line 82  (dispatch)
    async def get(self) -> web.Response: ...                     # line 102 (dispatch)
    async def _generate_infographic(self) -> web.Response: ...   # line 135 (LLM path — untouched)
    def _auto_save_infographic_artifact(self, ai_message, agent_id, user_id,
                                        session_id, template, theme): ...  # line 244
    # inside it: artifact = Artifact(...) (~line 284); artifact_store.save_artifact (~line 294)
    def _negotiate_accept(self) -> str: ...                      # line 454

# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(BaseView): ...                                   # line 102

# Route registration — packages/ai-parrot-server/src/parrot/manager/manager.py:1829-1845
#   .../infographic/{resource:templates}[/{template_name}]  (1829, 1833)
#   .../infographic/{resource:themes}[/{theme_name}]        (1837, 1841)
#   .../infographic/{agent_id}                              (1845)  ← literal 'render' must
#                                                                     register to match first

# packages/ai-parrot/src/parrot/tools/infographic_sections.py  (FEAT-326, merged)
class SectionSpec(BaseModel): ...                                # line 30
class SectionDescriptor(BaseModel): ...                          # line 68
def validate_descriptor_datasets(descriptor: SectionDescriptor,
                                 dataset_manager: Any) -> None:  # line 210
    # DUCK-TYPED (docstring, verified): needs only dataset_manager.get_dataset_entry(name)
    # returning an entry with a `.columns` attribute, or None when unknown.
    # Raises InfographicValidationError("sections_unmet", {"sections": [...]}) aggregating
    # ALL deficits. Lazy-imports InfographicValidationError to avoid a circular import.
def validate_payload_shape(...): ...                             # line 262

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py  (FEAT-326)
class InfographicToolkit(AbstractToolkit):                       # line 144
    async def render_data_template(self, template_name: str, payload: Dict[str, Any],
        descriptor: Optional["SectionDescriptor"] = None,
        marker_id: str = "report-data",
        title: Optional[str] = None) -> InfographicRenderResult: # line 625
    @staticmethod
    def _splice_payload(source, payload_json, marker_id) -> str: # line 752
    async def render_template(self, template_name, data=None, theme=None, title=None): ...

# packages/ai-parrot/src/parrot/tools/pythonpandas.py
class PythonPandasTool(PythonREPLTool):                          # line 25
    # self.df_locals = {}                                          line 122
    # locals_dict kwarg merged into REPL namespace                 lines 128-130
# (base: class PythonREPLTool(AbstractTool) — parrot/tools/pythonrepl.py:88)

# packages/ai-parrot/src/parrot/memory/redis.py — Redis client pattern for the job store
class RedisConversation(ConversationMemory):                     # line 10
    # Redis.from_url(REDIS_HISTORY_URL, decode_responses=True, ...)  lines 22-29
# NOTE: RedisConversation itself is CONVERSATION memory — the job store follows its
# client-construction pattern but is a NEW small class (Module 4), not a subclass.

# packages/ai-parrot/src/parrot/storage/artifacts.py
class ArtifactStore:                                             # line 27
    async def save_artifact(self, user_id, agent_id, session_id, artifact) -> None: ...
    async def get_public_url(self, ...) -> str: ...              # line 177 — presigned overflow
    # RAISES for inline (non-offloaded) artifacts (~line 224) — handle small-artifact case.

# packages/ai-parrot/src/parrot/helpers/infographics.py
def list_templates(...): ...                                     # line 18
def get_template(name: str) -> InfographicTemplate: ...          # line 35
def register_template(...): ...                                  # line 50
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AdhocDatasetAdapter` | `validate_descriptor_datasets` | duck-typed `get_dataset_entry` | `infographic_sections.py:210` (docstring) |
| render route | `render_data_template` / `render_template` | server-owned toolkit instance | `infographic_toolkit.py:625` |
| render route | `_negotiate_accept` | method reuse | `handlers/infographic.py:454` |
| render route | `ArtifactStore.save_artifact` + `get_public_url` | awaited persist + URL | `storage/artifacts.py:27,177` |
| job store | `redis.asyncio.Redis.from_url(REDIS_HISTORY_URL)` | client pattern | `memory/redis.py:22-29` |
| route table | manager route block | new entries before `{agent_id}` | `manager/manager.py:1829-1845` |

### Does NOT Exist (Anti-Hallucination)
- ~~a deterministic `render` route / `infographic/render` anywhere in ai-parrot-server~~ —
  zero hits; created by this feature.
- ~~any job/polling infrastructure for infographics~~ — none; created here (Redis-backed).
- ~~a generic KV/job store in `parrot/memory/`~~ — only `ConversationMemory` subclasses
  exist; the job store is NEW code following the Redis client pattern.
- ~~`packages/ai-parrot-server/src/parrot/bots/manager.py`~~ — wrong path; routes live in
  `packages/ai-parrot-server/src/parrot/manager/manager.py`.
- ~~`packages/ai-parrot-server/src/parrot/helpers/infographics.py`~~ — helpers module is in
  the CORE package; the server reaches it via the PEP 420 namespace.
- ~~inline template HTML support~~ — deliberately excluded (stored-XSS; resolved decision).
- ~~`AdhocDatasetAdapter`, `RenderRequest`, `RenderResponse`, `RenderJob`~~ — created by this
  feature (Modules 1-2).
- ~~a caller-payload dataset source in FEAT-324 recipes~~ — recipes fetch from DatasetManager
  sources only (why brainstorm Option C was rejected).
- ~~`pyarrow` as a declared dependency~~ — currently importable but not confirmed declared;
  Module 5 MUST declare it (resolved decision).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Handler style: follow `InfographicTalk`'s existing dispatch (`post()`/`get()` resource
  branching) and `_negotiate_accept`; auth via the class's existing
  `@is_authenticated`/`user_session` decorators — the render branch adds NO new auth scheme.
- Redis client: construct exactly like `parrot/memory/redis.py:22-29`
  (`Redis.from_url(REDIS_HISTORY_URL, decode_responses=True, ...)`); key prefix e.g.
  `infographic:job:`; set TTL (86400 s) when a job reaches a terminal state.
- Pydantic (`extra="forbid"`) for `RenderRequest`/`RenderResponse`/`RenderJob`; reuse
  `SectionDescriptor` by import — never copy the model.
- Async-first: parquet/CSV decoding of large parts should run in an executor
  (`loop.run_in_executor`) — pandas/pyarrow decode is CPU-bound blocking work.
- Config keys for the cap/TTL follow existing server config conventions (see how the handler
  reads config today; keep 50 MB and 86400 s as defaults).

### Known Risks / Gotchas
- **Route shadowing**: `'/api/v1/agents/infographic/{agent_id}'` (manager.py:1845) would
  swallow `render` — register the literal routes first; test pins this.
- **Inline-artifact URL**: `get_public_url` raises for inline artifacts (artifacts.py:~224);
  small HTML renders (< 200 KB inline threshold) need the defined fallback. Verify
  local-overflow presigned behavior (§8).
- **CPU-bound decode on the event loop**: multipart parquet/CSV decode must not block aiohttp
  workers — executor offload.
- **Cap enforcement**: enforce the 50 MB cap at the transport level (aiohttp
  `client_max_size`/streamed multipart) BEFORE buffering; a post-hoc check defeats the point.
- **NaN/Inf**: FEAT-326's splice serializer rejects them loudly → surface as 422, not 500.
- **Persistence failure with `persist=true`**: structured 5xx; with `Accept: text/html` the
  HTML may still return with `X-Artifact-Persisted: false` — surfaced, never silent.
- **Worker dies mid-job**: Redis keeps the job `running` forever without the max-runtime
  watchdog — the `deadline` field + poll-time check flips it to `failed`.
- **Adapter locals safety**: REPL `locals` contain non-DataFrame values — the adapter must
  filter to DataFrames explicitly and never execute/eval anything from the namespace.
- **Determinism caveat**: artifact ids/timestamps/URLs differ per call by design; the
  deterministic guarantee applies to the rendered HTML content — the repeat-call test
  compares spliced HTML, not artifact metadata.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pyarrow` | `>=25.0` (align with venv 25.0.0) | Parquet part decoding — MUST be declared direct (resolved) |
| `redis` | already in tree (`redis.asyncio` used by `parrot/memory/redis.py`) | job store |
| (no other new deps) | — | aiohttp multipart is built-in; pandas already core |

---

## 8. Open Questions

> All brainstorm questions were resolved before this spec was drafted
> (`sdd/proposals/infographic-render-endpoint.brainstorm.md`). Decision trail:

- [x] Job-store backend — *Resolved in brainstorm*: Redis via `parrot/memory/` pattern
  (multi-worker safe); no in-memory primary store. → §2 Overview, §3 Module 4, §5, §7.
- [x] Body-size caps — *Resolved in brainstorm*: total cap 50 MB (configurable); per-dataset
  caps and pre-buffering enforcement are spec-level details under that ceiling. → §1 G-8,
  §3 Module 2, §5, §7 Known Risks.
- [x] Validator adapter — *Resolved in brainstorm*: adapter for
  `validate_descriptor_datasets` accepting ad-hoc `{name: DataFrame}` dicts AND (possibly)
  references to dataframes in the python tool's `locals` — one gate for HTTP and in-process
  paths. → §1 G-4, §2 Data Models, §3 Module 1, §5.
- [x] Job TTL / cleanup — *Resolved in brainstorm*: terminal jobs expire after 1 day (Redis
  TTL); expired poll → 404. → §1 G-7, §3 Module 4, §5.
- [x] `pyarrow` dependency status — *Resolved in brainstorm*: must be a declared
  (non-transitive) dependency of the appropriate package. → §1 G-9, §3 Module 5, §7.
- [x] Artifact URL shape — *Resolved in brainstorm*: evaluated by the implementation during
  spec development — evaluation done: use `ArtifactStore.get_public_url()`
  (artifacts.py:177), with an explicit fallback for inline artifacts. → §2 Overview,
  §7 Known Risks.

- [ ] `get_public_url` behavior on the LOCAL overflow backend (presigned URLs are S3
  semantics — verify what the local `FileManagerInterface` returns and define the fallback
  precisely). — *Owner: implementer (Module 3)*
- [ ] Max-runtime watchdog value (job `deadline`) — pick a default (e.g. 10 min) during
  Module 4. — *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in ONE worktree
  (`.claude/worktrees/feat-327-infographic-render-endpoint`, branched from `dev`).
- **Rationale**: `handlers/infographic.py` is the center of gravity for Modules 2-4;
  parallel worktrees would conflict on it immediately. Module 1 (core adapter) is the only
  cleanly independent piece — not worth a second worktree.
- **Cross-feature dependencies**: FEAT-326 — already MERGED to dev (`481aec65a`); nothing
  in-flight blocks this spec. Check `sdd/tasks/index/` for other server-handler work before
  cutting the worktree.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-24 | jesuslara + Claude | Initial draft from brainstorm (Option A, 6 resolved questions carried forward) |
