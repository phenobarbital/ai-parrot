# TASK-2232: HTTP handler — POST /api/v1/thales + polling + artifact listing

**Feature**: FEAT-425 — "Thales" Research Flow with Structured Citations, Decks & Final Report
**Spec**: `sdd/specs/agentcrew-tales-research.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2231
**Assigned-to**: unassigned

---

## Context

Module 6 of FEAT-425, in the **ai-parrot-server** distribution. The HTTP
surface is POST + polling (resolved in brainstorm — explicitly NOT
SSE/WebSocket): launch a run, poll its status (fed by AgentsFlow
`on_node_event` via `ThalesRunner.add_progress_listener`), list artifacts
with `ArtifactStore` public URLs. Handler precedent:
`packages/ai-parrot-server/src/parrot/handlers/infographic.py`.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/handlers/thales.py`:
  - `POST /api/v1/thales` — body `{thesis, num_decks?, sources?, ...}` →
    validates into `ThalesConfig` (`num_decks < 10` → HTTP 400 with a
    message that names the ≥10 floor — spec §7 gotcha), launches
    `ThalesRunner.run()` as a background task, returns `{"run_id": ...}`.
  - `GET /api/v1/thales/{run_id}` — status document: run state
    (`pending|running|completed|failed`), per-node progress derived from
    node events (counts + last event), projected research-call count, and
    the manifest-so-far; full `ThalesResult` when completed.
  - `GET /api/v1/thales/{run_id}/artifacts` — artifact list with
    `ArtifactStore.get_public_url` links.
  - Run registry: in-process dict keyed by `run_id` behind a small
    `RunRegistry` class with an interface that allows a redis backend later
    (open question §8 — implement in-memory now, keep the seam).
  - Unknown `run_id` → 404; failed run → status `failed` with error summary.
- Register the handler with the server's routing following the
  `infographic.py` registration pattern.
- Unit tests with aiohttp test client and a mocked `ThalesRunner`.

**NOT in scope**: SSE/WebSockets; auth changes (inherit whatever the
handler precedent applies); the runner itself (TASK-2231).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/thales.py` | CREATE | Handler + RunRegistry |
| `packages/ai-parrot-server/src/parrot/handlers/<routing module>` | MODIFY | Register routes (mirror how infographic.py is wired — verify at implementation time) |
| `packages/ai-parrot-server/tests/handlers/test_thales_handler.py` | CREATE | aiohttp test-client tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-17 against `dev`.

### Verified Imports
```python
from aiohttp import web                                   # server framework (aiohttp only — never requests/httpx)
from parrot.flows.thales import ThalesRunner              # TASK-2231
from parrot.flows.thales.models import ThalesConfig, ThalesResult
from parrot.storage.artifacts import ArtifactStore        # storage/artifacts.py:27
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/infographic.py — the handler
# precedent for artifact-producing endpoints (route registration, request
# validation, ArtifactStore access). READ THIS FILE FIRST and mirror its
# registration mechanism — the exact router/registration API must be
# verified at implementation time (unverified beyond file existence —
# check before use).

# parrot/flows/thales/runner.py (TASK-2231):
class ThalesRunner:
    def __init__(self, thesis: str, *, num_decks: int = 10, sources=None,
                 output_dir=None, artifact_store=None, llm=None, **kwargs): ...
    async def run(self) -> ThalesResult: ...
    def add_progress_listener(self, cb): ...   # (event, node_id, info) contract

# AgentsFlow on_node_event vocabulary (flow/flow.py __init__ docstring):
#   flow_started | node_started | node_completed | node_failed |
#   node_skipped | flow_completed; info carries duration_ms / error / status.

# packages/ai-parrot/src/parrot/storage/artifacts.py
class ArtifactStore:                        # L27
    async def get_public_url(...): ...      # L177
```

### Does NOT Exist
- ~~SSE/WebSocket endpoints for Thales~~ — out of scope (resolved in
  brainstorm: POST + polling only).
- ~~A shared run-registry service in ai-parrot-server~~ — none exists; this
  task creates the in-memory `RunRegistry` (redis backend is a §8 open
  question, seam only).
- ~~`GET /api/v1/thales` list-all endpoint~~ — not in spec; only the three
  routes above.
- ~~requests/httpx~~ — forbidden repo-wide; aiohttp only.

---

## Implementation Notes

### Pattern to Follow
```python
# Background task launch (aiohttp):
task = asyncio.create_task(runner.run())
registry.attach(run_id, runner=runner, task=task)
# progress listener updates registry state:
runner.add_progress_listener(lambda ev, nid, info: registry.record(run_id, ev, nid, info))
```

### Key Constraints
- 400 on `num_decks < 10` with an explanatory message (spec AC / §7).
- Never block the event loop; the run is a background task whose exception
  is captured into the registry (status `failed`), not raised into aiohttp.
- Status document includes projected research-call count once known.
- Google-style docstrings, `self.logger`.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/infographic.py` — precedent.

---

## Acceptance Criteria

- [ ] POST launches a run and returns `run_id`; the run executes in background
- [ ] POST with `num_decks=5` → HTTP 400 naming the ≥10 minimum
- [ ] GET status reflects node-event progress (mocked runner emits events)
- [ ] GET artifacts returns public URLs; unknown run_id → 404
- [ ] Failed run → status `failed` with error summary, HTTP 200 on the status GET
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_thales_handler.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/thales.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_thales_handler.py
import pytest

@pytest.mark.asyncio
async def test_handler_post_poll(aiohttp_client, mocked_runner):
    """POST → run_id; poll GET transitions pending→running→completed."""

@pytest.mark.asyncio
async def test_handler_rejects_small_num_decks(aiohttp_client):
    """POST num_decks=5 → 400, body mentions minimum of 10."""

@pytest.mark.asyncio
async def test_handler_unknown_run_404(aiohttp_client):
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2231 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — READ `handlers/infographic.py` first;
   its route-registration mechanism is the unverified item to confirm
4. **Update status** in `sdd/tasks/index/agentcrew-tales-research.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2232-thales-http-handler.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-17
**Notes**: Followed `handlers/mcp_helper.py` as the routing precedent
instead of `infographic.py` — verified at implementation time that
`infographic.py`'s `InfographicTalk(AgentTalk)` is a heavy, per-agent-
scoped handler class (auth + PBAC + session + agent lookup) unsuited to
Thales's standalone, non-agent-scoped routes; `mcp_helper.py`'s
`BaseView`-derived classes + a plain `setup_*_routes(app)` function
(registered from `manager/manager.py`) is the generic pattern that
actually fits, and is also its OWN test file's convention (direct
`await HandlerClass.method(mock_self)` calls, no full aiohttp app/auth
middleware needed).

Implemented `ThalesRunHandler` (POST, `num_decks<10` → 400 naming the
floor, launches `ThalesRunner.run()` as a background `asyncio.Task`),
`ThalesStatusHandler` (GET status document from node events, embeds the
full `ThalesResult` on completion, error summary + HTTP 200 on failure),
`ThalesArtifactsHandler` (GET artifact list — refs already carry public
URLs from `ThalesRunner`'s own `ArtifactStore.get_public_url` calls, no
second lookup needed here), and `RunRegistry` (in-memory, `attach`/`get`/
`record_event`/`complete`/`fail` — the seam for a future redis backend
per spec §8). Registered via `setup_thales_routes()`, wired into
`manager.py` mirroring `setup_mcp_helper_routes(self.app)` exactly.

11 unit tests pass (mocked `ThalesRunner`, no network/real run). `ruff
check` shows only `BLE001`/`G201` — both match `mcp_helper.py`'s own
unaddressed pattern verbatim (bare "Invalid JSON body" catch; `logger.
error(..., exc_info=True)` instead of `.exception(...)`) — plus the usual
pre-existing `UP006`/`UP035`/`UP037`/`UP045` style categories.

**Deviations from spec**: none (the routing-module precedent choice
(`mcp_helper.py` over `infographic.py`) was explicitly left open by the
task itself: "verify at implementation time").
