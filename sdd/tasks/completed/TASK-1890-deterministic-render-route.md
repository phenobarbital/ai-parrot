# TASK-1890: Deterministic render route (sync path) + URL two-behavior rule

**Feature**: FEAT-327 — Infographic Render Endpoint — Deterministic Render-as-a-Service
**Spec**: `sdd/specs/infographic-render-endpoint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1888, TASK-1889
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-327 — the core deliverable: `POST /api/v1/agents/infographic/render`, a
bot-less, LLM-free branch on `InfographicTalk`. Decode → validate (FEAT-326 gate via
`AdhocDatasetAdapter`) → render (server-owned `InfographicToolkit`) → persist (awaited) →
negotiated response with the resolved **two-behavior URL rule** (`public` → `STATIC_DIR`
static URL; S3 → always presigned; local non-public/inline → `url: null`).

---

## Scope

- Dispatch: extend `InfographicTalk.post()` (line 82) so the literal `render` path takes the
  deterministic branch (NO bot lookup); register routes in
  `packages/ai-parrot-server/src/parrot/manager/manager.py` BEFORE the
  `'/api/v1/agents/infographic/{agent_id}'` entry (line 1845):
  `POST /api/v1/agents/infographic/render` (and the jobs GET route path reserved for
  TASK-1891).
- Flow (sync): parse `RenderRequest` (TASK-1889) → template existence via
  `parrot.helpers.infographics.get_template` (unknown → 404) → `AdhocDatasetAdapter`
  (TASK-1888) + `validate_descriptor_datasets` + `validate_payload_shape` → ONE aggregated
  422 on deficits → assemble payload per section `target`s → server-owned
  `InfographicToolkit` (configured `template_dirs` + `ArtifactStore`; `descriptor.mode`
  picks `render_data_template` vs `render_template`) → persistence AWAITED with session
  `user_id`, body `agent_id`/`session_id`, system defaults → response.
- **URL rule (resolved)**: `public=true` → write the HTML under `STATIC_DIR`
  (`parrot/conf.py:43-45`; sanitized server-generated filename, no caller-controlled path
  segments) and return the static URL; S3 overflow backend → `ArtifactStore.get_public_url()`
  presigned ALWAYS (never public S3); local non-public or inline artifact
  (`get_public_url` raises, artifacts.py:~224) → `url: null` + explanatory field.
- Content negotiation via existing `_negotiate_accept` (line 454): `text/html` → HTML body;
  JSON → `RenderResponse`. Persistence failure with `persist=true`: structured 5xx; for
  `text/html` the HTML may return with `X-Artifact-Persisted: false`.
- Determinism test: repeat call with identical inputs produces identical spliced HTML.
- Unit tests (aiohttp test client).

**NOT in scope**: async jobs (TASK-1891 — but leave the dispatch seam), decoding internals
(TASK-1889), dependency declaration/docs (TASK-1892).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/infographic.py` | MODIFY | render dispatch branch + sync flow |
| `packages/ai-parrot-server/src/parrot/handlers/infographic_render.py` | MODIFY | flow helpers (payload assembly, URL rule) |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | route registration (literal before `{agent_id}`) |
| `packages/ai-parrot-server/tests/.../test_infographic_render_route.py` | CREATE | Route tests (verify test layout first) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools import SectionDescriptor, AdhocDatasetAdapter   # adapter from TASK-1888
from parrot.tools.infographic_sections import (
    validate_descriptor_datasets,   # infographic_sections.py:210
    validate_payload_shape,         # infographic_sections.py:262
)
from parrot.tools.infographic_toolkit import InfographicToolkit   # infographic_toolkit.py:144
from parrot.helpers.infographics import get_template              # core helpers:35
from parrot.conf import STATIC_DIR                                # parrot/conf.py:43-45 (Path)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/infographic.py
class InfographicTalk(AgentTalk):                                # line 57
    async def post(self) -> web.Response: ...                    # line 82  — extend dispatch
    async def get(self) -> web.Response: ...                     # line 102
    async def _generate_infographic(self) -> web.Response: ...   # line 135 — DO NOT TOUCH
    def _auto_save_infographic_artifact(...): ...                # line 244 — study, do not reuse
    #   (fire-and-forget; the render path persists AWAITED instead)
    def _negotiate_accept(self) -> str: ...                      # line 454 — REUSE

# packages/ai-parrot-server/src/parrot/manager/manager.py — route block lines 1829-1845:
#   '/api/v1/agents/infographic/{resource:templates}'            (1829)
#   '/api/v1/agents/infographic/{agent_id}'                      (1845)  ← register literal
#                                                                   'render' BEFORE this

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):                       # line 144
    def __init__(self, *, artifact_store, template_dirs=None, ...): ...  # line 177
    async def render_data_template(self, template_name: str, payload: Dict[str, Any],
        descriptor=None, marker_id="report-data", title=None)
        -> InfographicRenderResult: ...                          # line 625
    async def render_template(self, template_name, data=None, theme=None, title=None): ...

# packages/ai-parrot/src/parrot/storage/artifacts.py
class ArtifactStore:                                             # line 27
    async def save_artifact(self, user_id, agent_id, session_id, artifact) -> None: ...
    async def get_public_url(self, ...) -> str: ...              # line 177 — presigned;
    #   RAISES for inline (non-offloaded) artifacts (~line 224)
```

### Does NOT Exist
- ~~a `render` route / deterministic branch~~ — created HERE (zero hits pre-task).
- ~~`InfographicTalk.render()` or any bot-less path~~ — the current `post()` always resolves
  a bot for generation; the new branch must run WITHOUT bot lookup.
- ~~public S3 hosting for artifacts~~ — FORBIDDEN by resolved decision; presigned only.
- ~~serving non-public artifacts from `STATIC_DIR`~~ — FORBIDDEN.
- ~~an existing static-publication helper for artifacts~~ — none found; the `public=true`
  write is new code `(verify whether the server app exposes STATIC_DIR over HTTP and the URL
  prefix before constructing the static URL)`.

---

## Implementation Notes

### Key Constraints
- **No LLM anywhere**: the branch must not touch `bot.*`; determinism is an acceptance
  criterion (repeat-call test compares spliced HTML, not artifact metadata).
- Server-owned toolkit: construct ONE `InfographicToolkit` per app (or lazily) with the
  configured `template_dirs` + `ArtifactStore` — never bind it to a bot (`set_bot` unused).
- Auth: the class-level decorators already applied to `InfographicTalk` cover the new branch —
  add no new auth scheme.
- `STATIC_DIR` filename: server-generated (e.g. `infographic-<artifact_id>.html`); create the
  dir if missing; document world-readability of `public=true`.
- Errors: 404 unknown template · 422 aggregated deficits (gate output verbatim in `detail`) ·
  413/400 come from TASK-1889 decoding · 5xx persistence.

### References in Codebase
- `handlers/infographic.py:135-243` — the LLM generate flow (style/negotiation reference)
- `sdd/specs/infographic-render-endpoint.spec.md` §2 Overview + §7 Known Risks

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass (`pytest` on the created test module)
- [ ] No linting errors (`ruff check` on modified files)
- [ ] `render` literal route matches (never swallowed by `{agent_id}`) — pinned by test
- [ ] Unknown template → 404; deficits → ONE aggregated 422; no render/persist on failure
- [ ] Repeat call with identical inputs → identical spliced HTML (determinism test)
- [ ] URL rule: `public=true` → file under `STATIC_DIR` + static URL; S3 → presigned;
  local non-public/inline → `url: null` + explanatory field
- [ ] Persistence awaited with session user_id + body attribution + system defaults
- [ ] Existing generate/templates/themes routes unchanged (regression test or diff review)

---

## Test Specification

```python
# test_infographic_render_route.py
class TestRenderRoute:
    async def test_render_literal_not_swallowed_by_agent_id(self, render_app): ...
    async def test_unknown_template_404(self, render_app): ...
    async def test_deficits_aggregated_422(self, render_app): ...
    async def test_html_negotiation_and_json_default(self, render_app): ...
    async def test_deterministic_repeat_call(self, render_app): ...
    async def test_public_true_static_dir_url(self, render_app, tmp_static_dir): ...
    async def test_local_nonpublic_url_null(self, render_app): ...
    async def test_persist_awaited_with_attribution(self, render_app): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** (TASK-1888, TASK-1889 in `completed/`);
3. **Verify the Codebase Contract** (static-serving prefix is marked unverified);
4. **Update status** in `sdd/tasks/index/infographic-render-endpoint.json` → `"in-progress"`;
5. **Implement**; 6. **Verify criteria**; 7. **Move file to completed/**;
8. **Update index** → `"done"`; 9. **Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-24
**Notes**: Implemented the `render` dispatch branch on `InfographicTalk.post()`
(`{resource:render}` matched literal, registered in `manager.py` BEFORE
`{agent_id}` — pinned by `TestRenderRouteRegistration`), `_decode_render_request`
(JSON or multipart), `_resolve_render_attribution` (session user_id; body
agent_id/session_id; system defaults), a lazily-cached, app-owned
`InfographicToolkit` (`app["infographic_render_toolkit"]`), and the full
validate → assemble → render → persist → resolve-URL flow in
`infographic_render.render_deterministic` (+ `assemble_section_payload`,
`resolve_response_url`/`publish_to_static_dir` implementing the two-behavior
URL rule). 12 route-level tests pass (404/422/400/HTML+JSON negotiation/
determinism/persist attribution/persist=false/public→STATIC_DIR/S3-style
presigned/local-null/async-seam) plus the route-ordering assertion; full
`tests/handlers/` suite (201 passed, 1 pre-existing skip) shows no regressions.

**Deviations from spec — three genuine architecture gaps surfaced and
resolved with documented judgment calls (none contradict the spec; all are
connective tissue the spec didn't fully wire):**

1. **`render_data_template`/`render_template` persist UNCONDITIONALLY** under
   a `_bot`-scope-derived (or `"_anon"`, bot-less) identity, with NO `persist`
   switch — incompatible with this endpoint's caller-supplied attribution and
   optional persistence, and `infographic_toolkit.py` is not in this task's
   file scope to fix directly. Resolution: bypass those two methods entirely
   and call the toolkit's own lower-level, persist-free primitives instead —
   `_template_engine` + `InfographicToolkit._splice_payload` (data-splice) /
   `_template_engine.render` (jinja) — the EXACT same calls those methods
   make internally. `_splice_payload` is explicitly listed as a verified
   signature in the SPEC's OWN §6 Codebase Contract, which is the strongest
   signal this was the intended seam. Persistence then happens via
   `ArtifactStore.save_artifact` directly, with THIS call's own
   user_id/agent_id/session_id, only when `persist=True`.
2. **No app-level `template_dirs` wiring exists anywhere** for a bot-less
   `InfographicToolkit` (`InfographicAuthoringMixin`/`ResultAgent` only ever
   build one per-AGENT, at agent-configure time). Resolution: a new,
   minimal `app["infographic_render_template_dirs"]` config key (read at
   first render, defaulting to `None`), mirroring the EXISTING
   `app["artifact_store"]` DI convention (`manager.py on_startup`). Absent
   config degrades to `TEMPLATE_ENGINE_UNSET`/`TEMPLATE_UNKNOWN` (mapped to
   500) rather than failing to build — deploy-time config, not this task's
   concern to populate with real production template paths.
3. **Two disjoint template registries**: `parrot.helpers.infographics.get_template`
   (block-spec metadata, used for the 404 pre-check per this task's own
   contract) is UNRELATED to `InfographicToolkit`'s own Jinja
   `template_dirs`/`templates=` registry (used for the actual render). A
   name passing the 404 check can still fail to render if the toolkit's OWN
   registry doesn't know it — surfaced as a 500 (`InfographicValidationError`
   not `sections_unmet`/`payload_shape_mismatch`), logged. Flagging for
   follow-up: reconciling these two registries (e.g. `register_template`
   also registering the raw HTML source with the render toolkit) is a
   cross-cutting concern beyond this task's file scope.
4. **Payload assembly algorithm** (`assemble_section_payload`) is NOT spec'd
   anywhere beyond "assemble payload per section targets" — no shape
   transformation algorithm is described. Implemented the narrow, safe
   common case (exactly ONE dataset alias per section, sliced to
   `columns[alias]`, shaped per `records`/`table`/`mapping`/`scalar`) and
   FAIL LOUDLY (`RenderPayloadError`, 400) for sections naming MORE than one
   dataset alias, rather than guessing a combination strategy. Flagging for
   product confirmation if multi-dataset sections are a real v1 requirement.
5. Async mode (`async_=True`) returns `501` with a message naming TASK-1891
   — the explicit "leave the dispatch seam" instruction; no job/queue logic
   here.
6. `self.error(..., status=501)` would silently degrade to `400` —
   `BaseView.error()` only remaps a fixed status set
   (400/401/403/404/406/412/428). Used `self.json_response(..., status=501)`
   instead so the real status code is honored; noted inline.
