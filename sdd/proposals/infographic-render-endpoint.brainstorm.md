---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Infographic Render Endpoint — Deterministic Render-as-a-Service

**Date**: 2026-07-24
**Author**: jesuslara (with Claude)
**Status**: exploration
**Recommended Option**: A

> **Base-branch note**: the user originally chose `feat-326-dataagent-infographic` as base
> (sub-feature, to consume FEAT-326 code before its merge). FEAT-326 has since MERGED into
> `dev` (commit `481aec65a`, all 6 tasks done, worktree removed), so the base is `dev` —
> which now contains every FEAT-326 artifact this feature consumes. The intent of the
> original choice (build on FEAT-326 code) is fully preserved.

---

## Problem Statement

FEAT-326 gave ai-parrot the deterministic infographic machinery — `SectionDescriptor`
(machine-enforced section → data contract), the **data-splice** render mode
(`InfographicToolkit.render_data_template`), and `ArtifactStore` persistence — but it is only
reachable *in-process*: a parrot agent composed with `InfographicAuthoringMixin`, or code that
instantiates the toolkit directly.

**Any agent** (external frameworks, remote services, A2A peers, scripts) should be able to
send over HTTP: (1) a list of datasets (dataframes or JSON data), (2) a selected pre-registered
template, and (3) instructions describing how to fill the template's areas — and get back a
rendered infographic, **deterministically** (no LLM anywhere in the path), through the current
infographic API surface (`InfographicTalk` in ai-parrot-server, routes under
`/api/v1/agents/infographic/...`).

Today that HTTP surface is LLM-driven only: `POST /api/v1/agents/infographic/{agent_id}` calls
`bot.get_infographic()` with a natural-language query. There is no deterministic render route.

Affected users: external/remote agents and services that need report rendering; internal teams
that want render-as-a-service without wiring a parrot agent.

## Constraints & Requirements

- **Deterministic**: no LLM in the request path. Same datasets + template + descriptor ⇒ same
  HTML (modulo artifact ids/timestamps). Instructions = the FEAT-326 `SectionDescriptor`
  (user decision — machine-enforced, fail-fast validation before render).
- **Extend `InfographicTalk`**, not a new handler (user decision): new route(s) alongside the
  existing generate/templates/themes routes registered in
  `packages/ai-parrot-server/src/parrot/manager/manager.py:1829-1845`.
- **Route without `{agent_id}`** (user decision): the deterministic path needs no bot. Body
  accepts optional `agent_id`/`session_id` for artifact attribution; `user_id` comes from the
  authenticated session; system defaults when absent.
- **Datasets over the wire — all three transports** (user decision): inline JSON `records`,
  pandas `split` orientation, and multipart **Parquet/CSV** parts for real dataframes
  (parquet preserves dtypes; `pyarrow` 25.0.0 already importable in the venv).
- **Templates pre-registered only** (user decision): payload references templates by name
  (registered via `template_dirs` or the existing `POST .../templates` route). NO inline HTML
  templates — arbitrary caller HTML persisted and served back is a stored-XSS vector and
  breaks the trusted-template model.
- **Sync + optional async** (user decision): synchronous render by default; `async=true` ⇒
  `202 Accepted` + job id + polling route. Needed for large multipart payloads. Job store:
  **Redis via `parrot/memory/`** (multi-worker safe; resolved decision).
- **Body cap 50 MB** (configurable; resolved decision): oversized requests → 413.
- **Shared validator adapter** (resolved decision): `validate_descriptor_datasets` gets an
  adapter accepting ad-hoc `{name: DataFrame}` dicts and (possibly) references to dataframes
  in the python tool's `locals` — one gate for both the HTTP endpoint and the in-process
  authoring path.
- **Response content-negotiated** (user decision): `Accept: text/html` → the HTML;
  `application/json` → persisted artifact reference + URL (the handler's existing
  `_negotiate_accept` pattern, line 454).
- **HTTP-only v1** (user decision): no parrot-side client tool; in-framework agents already
  have `InfographicToolkit`/`InfographicAuthoringMixin` locally.
- Async-first (aiohttp), Pydantic request models, `self.logger`; auth via the handler's
  existing `@is_authenticated`/`user_session` decorators.

---

## Options Explored

### Option A: Deterministic `render` route on `InfographicTalk` + optional job mode

Add to the existing handler:

- `POST /api/v1/agents/infographic/render` — body (JSON or multipart): `datasets`
  (name → inline records/split payload, or references to multipart parquet/csv parts),
  `template` (registered name), `descriptor` (`SectionDescriptor`, embedded JSON), optional
  `theme`, `marker_id`, attribution (`agent_id`, `session_id`), `persist` (default true),
  `async` (default false).
- Flow: parse/decode datasets → build DataFrames (records/split/parquet/csv) → FEAT-326
  validation gate (`validate_descriptor_datasets` + `validate_payload_shape`) → assemble the
  payload per descriptor targets → `InfographicToolkit.render_data_template(...)`
  (data-splice) or `render_template(...)` (jinja mode per `descriptor.mode`) → persist →
  negotiated response.
- Async mode: `202` + `{job_id}`; `GET /api/v1/agents/infographic/render/jobs/{job_id}` polls
  status → terminal state returns the same negotiated result payload.

✅ **Pros:**
- Reuses everything: auth, `_negotiate_accept`, artifact auto-save pattern
  (`_auto_save_infographic_artifact`, line 244), template/theme registry, and the whole
  FEAT-326 render/validation stack — the feature is mostly request decoding + wiring.
- Zero LLM: fully deterministic and cheap; callable by ANY HTTP-capable agent.
- Multipart parquet gives dtype-faithful dataframes (dates, categoricals) that JSON cannot.

❌ **Cons:**
- `InfographicTalk` grows another responsibility (it already dispatches generate + templates +
  themes via `{resource}` routes); dispatch logic needs care.
- Async jobs introduce state: a job store must be chosen (in-memory vs Redis) — open question.
- Payload decoding (3 transports) is the bulk of the new surface and needs strict limits.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pyarrow` | Parquet part decoding | 25.0.0 importable in venv — verify it is a DECLARED dependency, not transitive `(unverified)` |
| `pandas` | records/split/CSV decoding | already core |
| (no new deps) | — | aiohttp multipart is built in |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/infographic.py` — `InfographicTalk` (routes, negotiation, artifact auto-save)
- `packages/ai-parrot-server/src/parrot/manager/manager.py:1829-1845` — route registration block
- `packages/ai-parrot/src/parrot/tools/infographic_sections.py` — descriptor + validation gate (FEAT-326)
- `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py:625` — `render_data_template`
- `packages/ai-parrot/src/parrot/helpers/infographics.py` — template registry helpers

---

### Option B: Dedicated `InfographicRender` handler class

Same routes/flow as A but in a new handler class (own file), leaving `InfographicTalk`
untouched.

✅ **Pros:**
- Isolation: deterministic path evolves without touching the LLM handler; smaller review
  surface per change.

❌ **Cons:**
- Duplicates auth/negotiation/attribution plumbing or forces extracting a shared base first
  (bigger refactor than the feature itself).
- User explicitly chose extending `InfographicTalk`.

📊 **Effort:** Medium

📦 **Libraries / Tools:** same as A.

🔗 **Existing Code to Reuse:** same as A, plus `handlers/agent.py:102` (`AgentTalk` base).

---

### Option C: Recipe-first — callers register a FEAT-324 recipe, endpoint only replays

No ad-hoc payloads: the caller first publishes an `InfographicRecipe`, then calls a replay
endpoint with parameter overrides; datasets come from `DatasetManager` sources.

✅ **Pros:**
- Strongest determinism story (recipes ARE the replay contract); zero new validation surface.

❌ **Cons:**
- Mismatch with the requirement: the caller's data lives OUTSIDE parrot (dataframes/JSON in
  hand) — FEAT-324 `DataSourceSpec` fetches from registered sources, it does not accept
  caller-supplied frames. Would require a "payload source" concept — deeper FEAT-324 surgery
  than adding a render route.
- Heavy on-ramp for the "any agent sends data" use case.

📊 **Effort:** High

🔗 **Existing Code to Reuse:** `parrot/tools/infographic_recipes/runner.py`, recipe stores.

---

### Option D (unconventional): Expose it as an MCP tool instead of REST

Publish `infographic_render` as a tool on parrot's MCP server integration; any MCP-capable
agent calls it natively (typed schema, no HTTP plumbing on the caller side).

✅ **Pros:**
- Best DX for the growing MCP agent ecosystem; schema-validated inputs for free.

❌ **Cons:**
- The requirement names "the current infographic API endpoint" (REST). MCP transport for
  multi-MB parquet parts is awkward (base64 inflation).
- Doesn't serve plain HTTP callers.

📊 **Effort:** Medium

🔗 **Existing Code to Reuse:** `parrot/integrations/mcp/`.

---

## Recommendation

**Option A** — it is what the user's answers describe: extend `InfographicTalk` with a
bot-less `render` route (no `{agent_id}`), `SectionDescriptor` as the instruction format, all
three dataset transports, negotiated HTML/artifact-ref response, and sync + optional async.
It trades a fatter handler (dispatch complexity) for maximal reuse of existing auth,
negotiation, registries, and the freshly-merged FEAT-326 validation/render stack. Option C's
stronger recipe story stays available later — nothing in A precludes a future "publish this
render as a recipe" bridge; Option D (MCP tool) is a natural follow-up feature that would wrap
the same internal service function this feature creates.

---

## Feature Description

### User-Facing Behavior

Any authenticated HTTP caller (external agent, service, script) POSTs to
`/api/v1/agents/infographic/render`:

- **JSON body** (small/medium data): `{"datasets": {"projections": {"orient": "records",
  "data": [...]}, ...}, "template": "budget_variance", "descriptor": {...SectionDescriptor...},
  "theme": null, "persist": true, "async": false, "agent_id": "...", "session_id": "..."}`.
- **Multipart body** (large dataframes): one JSON part (`request`) with everything above,
  plus one part per dataset (`dataset:<name>` as parquet or CSV; content-type decides the
  decoder).

Response:
- `Accept: text/html` → the rendered HTML document.
- `Accept: application/json` (default) → `{artifact_id, url, template, sections_validated,
  persisted, timings}`.
- `async=true` → `202 {"job_id": ...}`; `GET .../render/jobs/{job_id}` → `{status:
  pending|running|done|failed, result?: <same negotiated payload>, error?: {...}}`.

Errors are structured and fail-fast: unknown template → 404; descriptor validation deficits →
422 with the full per-section deficit list (FEAT-326 gate output verbatim); oversized body →
413; malformed dataset part → 400 naming the part.

### Internal Behavior

1. **Dispatch**: `InfographicTalk.post()` routes `render`/`render/jobs` alongside the existing
   `{resource}` dispatch; no bot lookup for these paths.
2. **Request model** (Pydantic): `RenderRequest` with `datasets`, `template`, `descriptor`
   (embedded `SectionDescriptor` — reused, not redefined), `theme`, `marker_id`, attribution,
   `persist`, `async`. Multipart: the `request` part parses into the same model; dataset parts
   hydrate by name.
3. **Dataset decoding**: records/split → `pandas.DataFrame`; parquet part → `pyarrow` →
   DataFrame; CSV part → pandas. Per-dataset row/size caps; total body cap (configurable,
   e.g. 50 MB default) — enforced before decoding where possible.
4. **Validation gate**: FEAT-326 `validate_descriptor_datasets` through the new **adapter**
   (resolved decision): the adapter normalizes ad-hoc `{name: DataFrame}` dicts — and,
   possibly, named references into the python tool's `locals` for the in-process path — into
   whatever entry shape the merged gate expects; then `validate_payload_shape` per section
   target; deficits aggregate to one 422.
5. **Render**: `descriptor.mode == "data-splice"` → assemble payload per section targets and
   call `render_data_template(template, payload, descriptor, marker_id)`;
   `mode == "jinja"` → build context and call `render_template`. The toolkit instance is
   server-owned (configured `template_dirs` + `ArtifactStore`), NOT bot-bound.
6. **Persistence & attribution**: `persist=true` (default) saves via the existing artifact
   path with `user_id` from the session, `agent_id`/`session_id` from the body or system
   defaults (pattern of `_auto_save_infographic_artifact`, but awaited — the deterministic
   caller wants the reference back, not fire-and-forget).
7. **Async jobs**: job registry keyed by `job_id` (uuid4) holding status + result ref,
   backed by **Redis via `parrot/memory/`** (resolved decision — multi-worker safe; polling
   works regardless of which worker executed the render). Render runs as an `asyncio` task.

### Edge Cases & Error Handling

- **Unknown template name** → 404 (never render unregistered/inline HTML).
- **Descriptor/dataset mismatch** → 422 with every deficit (missing dataset, missing columns,
  shape mismatch) in one response.
- **Dataset name referenced by descriptor but no part/entry supplied** → part of the same 422.
- **Parquet/CSV decode failure** → 400 naming the offending part and decoder error.
- **NaN/Inf in payload** → FEAT-326 splice serializer already rejects loudly → surfaces as 422.
- **Body over cap** → 413 before buffering the full payload where the transport allows.
- **Job id unknown/expired** → 404; job TTL documented; failed jobs keep the structured error.
- **Persistence failure with `persist=true`** → 502-style structured error; with
  `Accept: text/html` the HTML can still be returned with a `X-Artifact-Persisted: false`
  header (surfaced, never silent).
- **Worker restart mid-job** → job state survives in Redis (resolved store choice), but a
  render task that died leaves the job `running` forever without a watchdog — jobs need a
  max-runtime/heartbeat so orphans transition to `failed` instead of hanging pollers.

---

## Capabilities

### New Capabilities
- `infographic-render-endpoint`: deterministic `POST .../infographic/render` route (JSON +
  multipart transports, negotiated response) on `InfographicTalk`.
- `infographic-render-jobs`: optional async execution (`202` + `GET .../render/jobs/{id}`).

### Modified Capabilities
- `get-infographic-handler` (existing spec): `InfographicTalk` gains the bot-less dispatch
  branch; existing generate/templates/themes behavior unchanged.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/infographic.py` | modifies | render dispatch + request decoding + job polling |
| `packages/ai-parrot-server/src/parrot/manager/manager.py:1829-1845` | modifies | register the 2 new routes (order matters: literal `render` segment must not be swallowed by `{agent_id}`) |
| `parrot/tools/infographic_sections.py` (FEAT-326) | extends | validator ADAPTER (resolved): ad-hoc `{name: DataFrame}` dicts + (possibly) python-tool `locals` references, normalized into the gate's entry shape |
| `parrot/tools/infographic_toolkit.py` (FEAT-326) | depends on | `render_data_template` (line 625) + `render_template`; server-owned toolkit instance |
| `parrot/helpers/infographics.py` | depends on | template existence checks (`get_template`:35) |
| `parrot/storage/` (`ArtifactStore`) | depends on | persistence + artifact URL |
| `parrot/memory/` (Redis) | depends on | job-store backend for async mode (resolved decision) |
| `pyarrow` | depends on | parquet decoding — confirm declared-dependency status |

No breaking changes to existing routes. Deployment: body-size cap + job TTL become config.

---

## Code Context

### User-Provided Code
(none — requirements given as prose)

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/infographic.py
_GENERATE_RESERVED_KEYS = frozenset({...})                       # line 39
class InfographicTalk(AgentTalk):                                # line 57
    async def post(self) -> web.Response: ...                    # line 82  (dispatch)
    async def get(self) -> web.Response: ...                     # line 102 (dispatch)
    async def _generate_infographic(self) -> web.Response: ...   # line 135 (LLM path — untouched)
    def _auto_save_infographic_artifact(self, ai_message, agent_id, user_id,
                                        session_id, template, theme): ...  # line 244
    def _negotiate_accept(self) -> str: ...                      # line 454

# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(BaseView): ...                                   # line 102

# Route registration — packages/ai-parrot-server/src/parrot/manager/manager.py:1829-1845
#   '/api/v1/agents/infographic/{resource:templates}'            (1829)
#   '/api/v1/agents/infographic/{resource:templates}/{template_name}' (1833)
#   '/api/v1/agents/infographic/{resource:themes}'               (1837)
#   '/api/v1/agents/infographic/{resource:themes}/{theme_name}'  (1841)
#   '/api/v1/agents/infographic/{agent_id}'                      (1845)

# packages/ai-parrot/src/parrot/tools/infographic_sections.py  (FEAT-326, merged @ 481aec65a)
class SectionSpec(BaseModel): ...                                # line 30
class SectionDescriptor(BaseModel): ...                          # line 68
class ProvenanceDescriptor(BaseModel): ...                       # line 99
def validate_descriptor_datasets(...): ...                       # line 210
def validate_payload_shape(...): ...                             # line 262
# NOTE for the spec: read the exact parameter types of the two validators — they were
# written against DatasetManager entries; the endpoint feeds ad-hoc DataFrames.

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py  (FEAT-326)
class InfographicToolkit(AbstractToolkit):                       # line 144
    async def render_data_template(self, template_name: str, payload: Dict[str, Any],
        descriptor: Optional["SectionDescriptor"] = None,
        marker_id: str = "report-data",
        title: Optional[str] = None) -> InfographicRenderResult: # line 625
    @staticmethod
    def _splice_payload(source, payload_json, marker_id) -> str: # line 752

# packages/ai-parrot/src/parrot/helpers/infographics.py  (core package; server imports it
# via the parrot.* namespace — the module does NOT live in ai-parrot-server)
def list_templates(...): ...                                     # line 18
def get_template(name: str) -> InfographicTemplate: ...          # line 35
def register_template(...): ...                                  # line 50
```

#### Verified Imports
```python
from parrot.tools import SectionDescriptor            # lazy export, tools/__init__.py:245,266
from parrot.bots.mixins import InfographicAuthoringMixin   # mixins/__init__.py:12 (context only)
from parrot.helpers.infographics import get_template  # resolves to packages/ai-parrot/src/...
import pyarrow                                        # 25.0.0 importable in the venv
```

#### Key Attributes & Constants
- Existing LLM route: `POST /api/v1/agents/infographic/{agent_id}` (manager.py:1845) — the new
  literal `render` route must be registered so aiohttp matches it BEFORE the `{agent_id}`
  pattern.
- `_negotiate_accept` (infographic.py:454) — reuse for the render response.
- FEAT-326 merge commit on dev: `481aec65a`.

### Does NOT Exist (Anti-Hallucination)
- ~~a deterministic `render` route / `infographic/render` anywhere in ai-parrot-server~~ —
  zero hits; created by this feature.
- ~~any job/polling infrastructure for infographics~~ — none exists; created here (backend TBD).
- ~~`packages/ai-parrot-server/src/parrot/bots/manager.py`~~ — wrong path; route registration
  lives in `packages/ai-parrot-server/src/parrot/manager/manager.py`.
- ~~`packages/ai-parrot-server/src/parrot/helpers/infographics.py`~~ — the helpers module is
  in the CORE package (`packages/ai-parrot/src/parrot/helpers/infographics.py`); the server
  reaches it through the PEP 420 namespace.
- ~~inline template HTML support~~ — deliberately excluded (stored-XSS risk; user decision).
- ~~a caller-payload dataset source in FEAT-324 recipes~~ — recipes fetch from DatasetManager
  sources only (why Option C was rejected).

---

## Parallelism Assessment

- **Internal parallelism**: Low-moderate. Request decoding (3 transports) and the job
  subsystem are separable from the core render route, but both plug into the same handler
  file and dispatch — sequential tasks in one worktree is simpler.
- **Cross-feature independence**: depends on FEAT-326 (already MERGED to dev — no in-flight
  dependency). Touches `handlers/infographic.py` + `manager/manager.py`; check
  `sdd/tasks/index/` for other in-flight server-handler work before cutting the worktree.
- **Recommended isolation**: `per-spec`.
- **Rationale**: one handler file is the center of gravity; splitting worktrees would conflict
  on it immediately.

---

## Open Questions

- [x] **Job-store backend** for async mode — *Owner: jesuslara*: **Redis via `parrot/memory/`**
  (multi-worker safe); no in-memory fallback as the primary store.
- [x] **Body-size caps** — *Owner: jesuslara*: total body cap **50 MB** (configurable);
  per-dataset caps and pre-buffering enforcement are spec-level details under that ceiling.
- [x] **Validator adapter** — *Owner: jesuslara*: ADD an adapter so
  `validate_descriptor_datasets` (infographic_sections.py:210) accepts **ad-hoc
  `{name: DataFrame}` dicts** AND, possibly, **references to dataframes living in the python
  tool's `locals`** (PythonPandasTool REPL namespace) — so the same gate serves the HTTP
  endpoint (ad-hoc frames) and the in-process authoring path (REPL-built frames) without
  duplicating validation logic.
- [ ] **Artifact URL shape** in the JSON response: presigned/overflow URL vs deeplink route —
  follow whatever `_auto_save_infographic_artifact` + artifacts handler already produce.
  — *Owner: spec author*
- [ ] **`pyarrow` dependency status**: importable in the venv (25.0.0) but confirm it is a
  declared dependency of the right package (`ai-parrot` vs `ai-parrot-server` extra) — if
  transitive, declare it. — *Owner: implementer*
- [ ] **Job TTL / cleanup policy** for terminal jobs. — *Owner: implementer*
