# TASK-2129: examples/dev_loop/server_dev.py — development-only aiohttp server

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2122, TASK-2123, TASK-2128
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 + §2 table "server_dev.py and dev.html (deliverable
shape)". A sibling of `server.py` serving the dev-flow: no CloudWatch, no
mandatory Jira, WITH the gate-resolution route mounted (the HITL write path
that `server.py` never wires). Runs side-by-side with the ops console
(default port 8081).

---

## Scope

- Create `examples/dev_loop/server_dev.py` mirroring `server.py`'s
  structure with the spec's table of deltas:
  - `GET /` → `web.FileResponse(STATIC_DIR / "dev.html")`.
  - Startup: base `ClaudeCodeDispatcher`, development backend resolution,
    codereview/judge-panel dispatchers, repos, pool builder, graph memory,
    wiki_search — REUSE `server.py`'s builder helpers by import where they
    are ops-free; NO `_build_log_toolkits` anywhere; Jira toolkit optional
    (absent env → `None`, zero Jira calls).
  - Flow: `build_dev_flow(...)`; runner: `DevFlowRunner`.
  - `_build_dev_brief_from_form(form)`: `kind ∈ {enhancement, new_feature}`
    → `DevRequestBrief` (title + description required; optional context,
    jira_issue_key, dev_agents, judge_panel); `kind == "feature"` → reuse
    the `_build_feature_brief_from_form` logic (server.py:956). NO
    `affected_component`, NO `log_sources`, NO reporter/escalation.
  - `POST /api/flow/run`: build brief, mint run_id, `extra_shared` carries
    `skip_qa`, `skip_jira`, and per-run `require_plan_approval` (TASK-2123
    override). Response shape identical to server.py (`run_id`, `ws_url`,
    `state_ws_url`, `bundle_url`).
  - Gate resolution route mounted: `register_command_routes(app, runner)`
    or an `/api/flow/{run_id}/gates/{gate_id}/resolve` alias delegating to
    the same handler (pick ONE and document it in `/api/config`).
  - `GET /api/config`: llm_catalog payload + `kinds: [enhancement,
    new_feature, feature]`, `document_kinds`, `defaults: {development_agent,
    codereview_agent, qa_max_retries, development_pool_max,
    max_concurrent_runs, ideation_max_rounds, require_plan_approval,
    skip_qa, docs_artifact_dir, wiki_page_ingest, wiki_search}` — NO
    `log_group`, NO `time_window_minutes`, NO `jira_project`.
  - Cancel / bundle / replay / WS routes identical to server.py (same
    `flow_stream_ws`, same `RUN_ARTIFACT_DIR` convention).
  - `main()`: `PORT` default **8081**, `HOST` default `127.0.0.1`,
    `REDIS_URL` as in server.py.
- Integration tests with aiohttp test client + fakes.

**NOT in scope**: dev.html (TASK-2130), any modification to `server.py` or
`index.html` (must remain byte-identical), docs (TASK-2131).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/server_dev.py` | CREATE | Dev-flow server |
| `packages/ai-parrot/tests/flows/dev_flow/test_server_dev.py` | CREATE | Route/config/gate integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_flow.flow import build_dev_flow        # TASK-2127
from parrot.flows.dev_flow.runner import DevFlowRunner       # TASK-2128
from parrot.flows.dev_flow.models import DevRequestBrief     # TASK-2121
from parrot.flows.dev_loop.commands import register_command_routes  # commands.py
from parrot.flows.dev_loop.streaming import flow_stream_ws   # WS multiplexer
```

### Existing Signatures to Use
```python
# examples/dev_loop/server.py — seams verified 2026-08-05:
#   STATIC_DIR = Path(__file__).parent / "static"              # :160
#   RUN_ARTIFACT_DIR = Path(conf.OUTPUT_DIR) / "dev_loop_runs" # :161
#   handle_index → FileResponse(STATIC_DIR / "index.html")     # :1027
#   handle_config                                              # :1031
#   handle_run (mode select :1111, run_id mint :1138,
#               extra_shared skip flags :1142-1148,
#               asyncio.create_task + app["flow_tasks"] :1150-1168)  # :1092
#   handle_cancel :1181 · handle_bundle :1215 · handle_replay :1270
#   _build_feature_brief_from_form                             # :956-1019
#   _build_log_toolkits (CloudWatch — MUST NOT be used here)   # :660
#   _build_jira_toolkit :579 · _build_git_toolkit :607 · _build_wiki_toolkit :626
#   reviewer/dispatcher builders :176-575 (ops-free, reusable)
#   _on_startup :1292-1501 · build_app :1533 (static mount :1540,
#               ws route :1545) · main :1550 (PORT default 8080)
#   llm_catalog: examples/dev_loop/llm_catalog.py — catalog_payload(),
#               get_backend(), JUDGE_BACKENDS

# parrot/flows/dev_loop/commands.py — register_command_routes(app, runner):
#   binds app["dev_loop_runner"]; routes:
#   POST /runs/{run_id}/gates/{gate_id}/resolve   (ResolveGateRequest body,
#        + answers field after TASK-2122)
#   POST /runs/{run_id}/cancel
```

### Does NOT Exist
- ~~a gate-resolve route in server.py~~ — the library handler exists but is
  unmounted there; server_dev.py is the first example to mount it.
- ~~`server_dev.py` / `static/dev.html`~~ — created by this task / TASK-2130.
- ~~templating in the example~~ — `handle_index` serves a hardcoded file;
  all dynamic config flows through `GET /api/config`.
- ~~revision-mode exposure~~ — `run_revision` stays unexposed (parity with
  server.py).
- ~~mandatory reporter/escalation/affected_component~~ — bug-intake-only
  concepts; must not appear in the dev brief builder.

---

## Implementation Notes

### Key Constraints
- Import reusable builders FROM `server.py` (`from server import
  _build_git_toolkit, ...` won't work as a script — either import via the
  examples package pattern used by existing tests, or copy the few needed
  helpers with a comment pointing at their origin; prefer whichever keeps
  `server.py` untouched).
- Feature-mode availability guard (server.py:1112-1121 pattern) is NOT
  needed — dev-flow always builds its single topology or the server fails
  startup loudly.
- `skip_jira` semantics: same extra_shared passthrough as server.py.
- Never require `JIRA_*` env at startup; degrade to `jira_toolkit=None`.

### References in Codebase
- `examples/dev_loop/server.py` — the structural template
- `examples/dev_loop/llm_catalog.py` — config payload source

---

## Acceptance Criteria

- [ ] `python examples/dev_loop/server_dev.py` starts without CloudWatch/Jira env (Redis required), port 8081
- [ ] `GET /` serves `dev.html`; `GET /api/config` matches the dev shape (no log_group/time_window/jira_project; kinds are the 3 dev intents)
- [ ] `POST /api/flow/run` accepts both NL kinds and `feature`; 400 on missing title/description
- [ ] Gate-resolve route mounted; resolving an `open_questions` gate with `answers` unblocks a parked run (test with fakes)
- [ ] `require_plan_approval` form flag reaches `extra_shared`
- [ ] `server.py` and `index.html` untouched (`git diff --name-only` shows neither)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_server_dev.py -v`; `ruff` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_server_dev.py
async def test_index_serves_dev_html(aiohttp_client): ...
async def test_config_shape_no_ops_keys(aiohttp_client): ...
async def test_run_enhancement_brief_built(aiohttp_client): ...
async def test_run_feature_brief_built(aiohttp_client, tmp_path): ...
async def test_run_missing_description_400(aiohttp_client): ...
async def test_gate_resolve_route_mounted(aiohttp_client): ...
async def test_plan_approval_flag_in_extra_shared(aiohttp_client): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2122, TASK-2123, TASK-2128 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**:

`server_dev.py` (~480 lines) + 28 integration tests (145 across `dev_flow`).

**Reuse decision.** The task offered "import from server.py" or "copy the few
needed helpers". I chose **import** — `sys.path.insert(...)` then
`import server as ops_server`, the same trick `server.py` itself uses for
`llm_catalog`. `server.py` is only *read*, never modified (asserted by
`git diff --name-only dev...HEAD -- examples/dev_loop/server.py` being empty).
Imported: the dispatcher/reviewer builders
(`_resolve_codereview_dispatcher`, `_build_judge_panel_dispatcher`,
`_log_development_agent_selection`, `_DEVELOPMENT_AGENT_MAX_CONCURRENT_ENV`),
the toolkit builders, `_build_feature_brief_from_form`, `_parse_dev_agents`,
`_parse_judge_panel`, `RUN_ARTIFACT_DIR`, `_on_cleanup`, and the
`handle_bundle`/`handle_replay`/`handle_cancel` handlers — those three are
app-key driven and mode-agnostic, so reusing them keeps the artifact/cancel
contract *identical* by construction rather than by convention
(`test_reuses_ops_helpers_without_modifying_them` asserts the reused handlers
are the very same objects, and that the ops `handle_index`/`handle_config`/
`handle_run` are NOT mounted). Deliberately **not** imported:
`_build_log_toolkits` (CloudWatch) and `_build_brief_from_form` (bug intake).

**Gate route — one option, as instructed.** Only the
`POST /api/flow/{run_id}/gates/{gate_id}/resolve` alias is mounted, not
`register_command_routes`'s `/runs/...` pair, so every console route shares
one prefix and `handle_cancel` remains the single cancel entry point. The
alias is a pure delegation to the library `resolve_gate_handler`, so the body
contract (`ResolveGateRequest` incl. `answers`) and every status code are
identical. It is published to the UI as `gate_resolve_url_template` in
`/api/config`, and `_on_startup` binds `app["dev_loop_runner"]` (the key the
library handler reads). `test_gate_resolve_route_mounted` drives the whole
round-trip: run → gate opens → REST POST with `answers` → the flow observes
those answers → 200. `test_gate_resolve_empty_answers_400` confirms the
host-side validation surfaces as `answers_required`.

**Jira is genuinely optional.** `_build_optional_jira_toolkit()` short-circuits
to `None` when `JIRA_INSTANCE`/`JIRA_USERNAME` are unset and also swallows a
construction failure, so a dev machine with no Jira env starts cleanly
(`test_jira_is_optional`). Startup never calls `_build_log_toolkits`.

**Per-run plan gate.** `require_plan_approval` is forwarded to `extra_shared`
**only when the key is present in the form**, so an absent toggle falls back
to the flow's build-time default rather than silently overriding it with
`False` — which is exactly the absent-vs-explicit-False distinction
TASK-2123 implemented. All three cases are tested
(`True` forwarded, explicit `False` forwarded, absent not forwarded).

**Test-design note worth recording.** My first pass asserted absence of ops
concerns by substring-scanning `inspect.getsource(module)`, which failed
because this module's *own documentation* names `_build_log_toolkits` and
`_build_brief_from_form` in order to state they are excluded. Replaced with
`_referenced_identifiers()`, which walks the **AST** and collects
`Name`/`Attribute`/`keyword`/`alias` identifiers — docstrings and comments are
excluded by construction. `test_index_serves_dev_html` was likewise rewritten
from source-scanning to behavioral (call the handler, assert the
`FileResponse` path is `STATIC_DIR/dev.html`).

Also verified: the module imports and `build_app()` succeeds standalone (15
routes), and `main()`'s port default is 8081 (`test_default_port_is_8081`).

`ruff`: `server_dev.py` and its test file at **0** findings.

**Deviations from spec**: none.

Note: `GET /` currently 404s because `static/dev.html` lands in TASK-2130 —
which is why `test_index_serves_dev_html` asserts the resolved path rather
than a 200.
