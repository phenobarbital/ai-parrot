# TASK-3849: Example aiohttp server for the linked dashboard

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3848
**Assigned-to**: unassigned

---

## Context

Spec §2 "Example server" + §3 Module 7 (FEAT-610). Mount order follows `app.py:109-113` and
`examples/forms/form_server.py:59-66` (AuthHandler last; `auth_exclude_list` extended).

---

## Scope

- `examples/a2ui/server.py`: `require_querysource("5.1.2")` (exit with a clear message when older),
  `create_app(with_agent_api=False, llm=None)`, `dashboard_handler` (`GET /api/a2ui/dashboard[?rebuild=1]`, cached in
  `app`, envelope via `extract_envelope`), `check_slugs` on_startup (read-only; missing by-course slug → log the
  `seed_by_course.py --yes` hint), `GET /` → `static/index.html`, `/static/` assets, `/static/vendor/echarts.min.js`
  served from the installed `parrot.outputs.formats.assets` path, CLI `--host --port --with-agent-api --llm`.
- `QuerySource(lazy=False).setup(app)`; optional `BotManager(enable_database_bots=False, enable_registry_bots=False)` +
  `add_agent` when `--with-agent-api`; `AuthHandler().setup(app)` last; exclude `/`, `/static/*`.
- `tests/examples/test_a2ui_server_routes.py` with QuerySource/AuthHandler/agent patched.

**NOT in scope**: the static files (TASK-3850/3851); no demo auth backend, no PBAC policy (Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/a2ui/server.py` | CREATE | aiohttp app + CLI |
| `tests/examples/test_a2ui_server_routes.py` | CREATE | route tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Verified Imports
```python
from aiohttp import web
from navigator_auth import AuthHandler                                 # app.py:6
from querysource.services import QuerySource                           # app.py:7
from parrot.manager import BotManager                                  # app.py:9
```
### Existing Signatures to Use
```python
qry = QuerySource(lazy=False); qry.setup(self.app)                     # app.py:109-110
class BotManager: __init__(enable_database_bots=..., enable_crews=..., enable_registry_bots=..., enable_swagger_api=...)  # manager.py:193
    def add_agent(self, agent: AbstractBot) -> None                     # manager.py:1179
    def setup(self, app: web.Application, *, agent_mount_config=None, ...) -> web.Application  # manager.py:2239
# form_server.py:59-66
    auth = AuthHandler(); auth.setup(app)
    app["auth_exclude_list"].extend(["/admin", "/", "/gallery", "/forms/*"])
# echarts bundle: packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/echarts.min.js
#   (resolve with importlib.resources.files("parrot.outputs.formats") / "assets" / "echarts.min.js")
```
### Does NOT Exist
- ~~`/api/v1/ui/surfaces/{id}/refresh` usage~~ — not used. ~~NoAuth / demo auth~~ — BasicAuth via AuthHandler only.
- ~~Seeding at startup~~ — `check_slugs` is read-only (S9).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/a2ui/server.py",
      "action": "CREATE"
    },
    {
      "path": "tests/examples/test_a2ui_server_routes.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: depends on TASK-3848: imports build_dashboard_agent / extract_envelope / dashboard_question from examples/a2ui/dashboard.py and needs its .gitignore whitelist.
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. `require_querysource` via `importlib.metadata.version("querysource")` + `packaging.version` — before any import of
   QuerySource side effects, because older versions fail later with confusing errors.
2. Build the app in the documented mount order; register routes BEFORE AuthHandler so its middleware sees them.
3. `dashboard_handler`: cache under `app["a2ui_envelope"]`; `?rebuild=1` clears it; run the agent via
   `await agent.configure()` (FILL IN: verify the Agent lifecycle call used by other examples) then `await agent.ask(dashboard_question())`.
4. Tests with everything patched.

```python
# examples/a2ui/server.py — CREATE
"""FEAT-610 — A2UI linked dashboard example server (QuerySource + AuthHandler + static renderer).

Run: ENV=prod QS_PBAC_ENABLED=false python examples/a2ui/server.py --port 5000
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import importlib.resources
import logging
import sys
from pathlib import Path

from aiohttp import web
from packaging.version import Version

logger = logging.getLogger("a2ui.example")
HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"


def require_querysource(min_version: str = "5.1.2") -> None:
    """Exit with a clear message when querysource is older than min_version."""
    # FILL IN: read installed version (PackageNotFoundError → exit too); sys.exit(f"querysource>={min_version} required, found {v}")


async def check_slugs(app: web.Application) -> None:
    """on_startup, read-only: warn when a dashboard slug is missing (never seed here — S9)."""
    # FILL IN: QuerysourceToolkit(programs=["polestar"]).describe_slug(...) for SLUG and BY_COURSE_SLUG inside try/except;
    #   on a missing by-course slug log: "run: ENV=prod python examples/a2ui/seed_by_course.py --yes".


async def index_handler(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html")


async def dashboard_handler(request: web.Request) -> web.Response:
    """GET /api/a2ui/dashboard[?rebuild=1] → cached envelope JSON."""
    # FILL IN: cache + lock (asyncio.Lock in app) so concurrent first loads run the agent once; json_response(envelope).


def create_app(*, with_agent_api: bool = False, llm: str | None = None) -> web.Application:
    """Build the example app (QuerySource → [BotManager] → routes → AuthHandler last)."""
    from navigator_auth import AuthHandler
    from querysource.services import QuerySource

    app = web.Application()
    app["llm"] = llm
    app["a2ui_lock"] = asyncio.Lock()
    QuerySource(lazy=False).setup(app)
    # FILL IN: optional BotManager(enable_database_bots=False, enable_registry_bots=False) + add_agent(build_dashboard_agent(llm)) + setup(app)
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/a2ui/dashboard", dashboard_handler)
    # FILL IN: /static/vendor/echarts.min.js route (FileResponse from the installed assets path) then add_static("/static/", STATIC)
    app.on_startup.append(check_slugs)
    AuthHandler().setup(app)
    app["auth_exclude_list"].extend(["/", "/static/*"])
    return app


def main() -> None:
    # FILL IN: argparse --host (0.0.0.0) --port (5000) --with-agent-api --llm (DEFAULT_LLM); require_querysource(); web.run_app
    ...


if __name__ == "__main__":
    main()
```
**Why**: `/api/a2ui/dashboard` is NOT excluded from auth — the page sends the Bearer token (§4 integration test asserts a
token-less request is rejected).

```python
# tests/examples/test_a2ui_server_routes.py — CREATE
"""FEAT-610 TASK-3849 — example server routes (spec §4 integration test)."""
# FILL IN: sys.path insert of examples/a2ui (as in test_a2ui_dashboard_example.py); monkeypatch QuerySource.setup,
#   AuthHandler (a fake whose setup adds a middleware rejecting requests without Authorization unless path excluded),
#   and the agent (returns an AIMessage with a qs_build_linked_dashboard ToolCall); aiohttp_client fixture:
#   GET / → 200 html; GET /api/a2ui/dashboard with token → envelope with parrot_data_sources; without → 401/403;
#   require_querysource("99.0") → SystemExit.
```
**FILL IN checklist**
- [ ] version check; check_slugs; cached handler; BotManager branch; echarts route; main(); route tests.

---

## Acceptance Criteria

- [ ] Serves `/` and `/api/a2ui/dashboard`; token-less dashboard request rejected (AC6).
- [ ] Exits with a clear message on querysource < 5.1.2 (AC6).
- [ ] Mount order QuerySource → [BotManager] → AuthHandler; no PBAC policy; startup never writes.

---

## Validation Commands

- `pytest tests/examples/test_a2ui_server_routes.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_dashboard_example_server_routes` | AC6 |
| `test_require_querysource_exits` | AC6 |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3849 — Example aiohttp server for the linked dashboard`.
5. Close with `scripts/sdd/close_task.sh TASK-3849 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
