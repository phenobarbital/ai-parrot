# TASK-3839: Linked E2E example server, Epson agent, HTTP runner and offline/staging tests

**Feature**: FEAT-611 — A2UI Linked Surfaces E2E (parallel track)
**Spec**: `sdd/specs/a2ui-linked-e2e-parallel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3831, TASK-3832, TASK-3834, TASK-3835, TASK-3837, TASK-3838
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 9 and §9 S9. The scenarios are S1 (server lane + share + PBAC),
S2 (the dashboard TOOL through the server), S3 (multiquery) and S5 (tenant route). They run in two tiers,
kept strictly separate (§9 S9):

- an **offline** deterministic pytest tier, using FakeQS and a fake guard;
- a **staging** live tier (`pytest -m staging` and `run_e2e.py`). It is skipped unless `ENV=staging` and
  querysource ≥ 5.1.2 are present, and it never counts as the deterministic verdict.

**Exclusive (`parallel: false`)**: this task edits the shared test configuration in `pytest.ini` and
`packages/ai-parrot-server/pyproject.toml` (it adds the `staging` marker).

Why each dependency:
- **TASK-3831**: the QS 5.1.2 pin, so the staging gate can assert `installed_version() >= 5.1.2`.
- **TASK-3832**: `examples/agents/a2ui/linked_e2e/seed_staging.py` provides `MQ_SLUG = "epson_activity_vs_targets_mq"`,
  and `policies/source-epson.yaml` is the policy dir the server mounts.
- **TASK-3834**: the fixed guard-call count in `test_linked_surfaces_e2e.py`, whose harness classes this task
  imports, and FilterBar validation on publish.
- **TASK-3835**: the dict-result envelope lift in `bots/base.py`, needed by the runner's `--via-agent` path.
- **TASK-3837**: the `PublishSurfaceTool(guard=...)` kwarg and `_resolve_linked_service`.
- **TASK-3838**: `build_epson_activity_dashboard` and `build_sources` in `dashboard_tool.py`.

---

## Scope

- `server.py`: `create_app(policy_dir=..., guard_mode=...)`. It mounts QuerySource(lazy=False), then the
  data-plane guard, then BotManager (db/registry bots off) with `EpsonLinkedAgent` added before startup,
  then AuthHandler(BasicAuth). It also has a `main()` CLI.
- `agent.py`: `EpsonLinkedAgent(InfographicAuthoringMixin, Agent)` with `QuerysourceToolkit`, the dashboard
  TOOL wrapped as an `@tool` closure (it injects pctx and guard), and `PublishSurfaceTool(bot=self)`.
- `run_e2e.py`: an aiohttp client with `login`, `run_s1`, `run_s2`, `run_s3`, `run_s5` and `main`. It prints
  a `ScenarioResult` table and exits 0 only when every non-skipped check passed.
- Offline tests `test_linked_e2e_offline.py`: S1, S3 and S5, using FakeQS and a fake guard.
- Staging tests `test_linked_e2e_staging.py` (marked `staging`), which drive `run_e2e`'s scenario functions.
- Register the `staging` marker in `pytest.ini` and in the server `pyproject.toml`.

**NOT in scope**:
- The seed and policy (TASK-3832).
- The dashboard TOOL (TASK-3838).
- Any core change: the envelope lift (TASK-3835) and the PublishSurfaceTool guard (TASK-3837).
- The README and docs (TASK-3840).
- The admin UI (S4, TASK-3836/3840).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/a2ui/linked_e2e/server.py` | CREATE | aiohttp app factory + CLI (mount order per spec §3 M9) |
| `examples/agents/a2ui/linked_e2e/agent.py` | CREATE | `EpsonLinkedAgent` |
| `examples/agents/a2ui/linked_e2e/run_e2e.py` | CREATE | Asserting HTTP runner S1/S2/S3/S5 |
| `packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py` | CREATE | Offline deterministic S1/S3/S5 |
| `packages/ai-parrot-server/tests/integration/test_linked_e2e_staging.py` | CREATE | `@pytest.mark.staging` live tier |
| `pytest.ini` | MODIFY | Register `staging` marker |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | Register `staging` marker |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web                                                 # used by app.py / form_server.py
from navigator_auth import AuthHandler                                  # app.py:6; AuthHandler(app_name='auth', secure_cookies=True,
                                                                        #   enable_authdb=True, backends: Iterable[str]=None, ...) — backends are DOTTED STRINGS
from querysource.services import QuerySource                           # app.py:7; QuerySource(*, tenant_allowlist=..., **kwargs); .setup(app)
from parrot.manager import BotManager                                   # app.py:9
from parrot.auth.pbac import setup_dataplane_guard                      # pbac.py:292
from parrot.auth.context import _pctx_var                               # auth/context.py:33 (ContextVar[PermissionContext|None])
from parrot.auth.permission import build_principal_context              # permission.py:166 (principal, *, channel, tenant_id=None, roles=None)
from parrot.bots import Agent                                           # bots/__init__.py:2
from parrot.bots.mixins.infographic_authoring import InfographicAuthoringMixin  # bots/info.py:33 (same import)
from parrot.tools import tool                                           # tools/__init__.py:151 (decorators.tool)
from parrot_tools.querysource.toolkit import QuerysourceToolkit         # toolkit.py:64
from parrot_tools.querysource._qs import installed_version              # _qs.py:65
from parrot_tools.ui_surfaces import PublishSurfaceTool                 # ui_surfaces.py:62
from parrot.outputs.a2ui.linked.executor import execute_sources         # executor.py:180
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest  # models.py:192, :30
from parrot.outputs.a2ui.linked.conditions import derive_conditions     # conditions.py:17
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService     # service.py:67
from parrot.auth.exceptions import AuthorizationRequired                # auth/exceptions.py:12
import parrot.tools.dataset_manager.sources.query_slug as query_slug    # _get_qs :30, _get_multiqs :43
# harness helpers (duplicated-harness precedent; tests/ and tests/integration/ are packages — both have __init__.py):
from .test_linked_surfaces_e2e import (_FakeAsyncDB, _StubResolver, _decode, _get, _handler, _post)  # :112, :184, :179, :169, :154, :174
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, UISurfaceShare  # models/ui_surfaces.py (UISurfaceShare :90)
from parrot.handlers.ui_surfaces_scope import SurfaceScope               # used by test_linked_surfaces_e2e.py:22
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:
    def __init__(self, enable_database_bots=ENABLE_DATABASE_BOTS, enable_crews=ENABLE_CREWS,
                 enable_registry_bots=ENABLE_REGISTRY_BOTS, enable_swagger_api=ENABLE_SWAGGER)   # :193-199
    def add_bot(self, bot) -> None     # :738 — keys self._bots by bot.name (get_bot(name) looks up self._bots.get(name), :781)
    def add_agent(self, agent) -> None # :1179 — keys by str(agent.chatbot_id); AgentTalk resolves by NAME → use add_bot
    def setup(self, app, *, agent_mount_config=None, ...) -> web.Application  # :2239; appends on_startup, then
        # _setup_dataplane_guard (:2304), and registers /api/v1/ui/surfaces[/{id}[/refresh|/share[/{token}]]] (:2334-2338)
        # and /api/v1/agents/chat/{agent_id} (:2312)
    async def _setup_dataplane_guard(self, app)  # :2707-2731 — guard = setup_dataplane_guard(app, policy_dir=PARROT_PBAC_POLICY_DIR);
        # injects into every self._bots bot lacking _dataplane_guard
# parrot/conf.py:118 PARROT_PBAC_POLICY_DIR = config.get("PARROT_PBAC_POLICY_DIR", fallback="policies") — read at IMPORT time

# packages/ai-parrot/src/parrot/auth/pbac.py:292-348
def setup_dataplane_guard(app, *, policy_dir: str = "policies", cache_ttl: int = 30) -> Optional[DataPlanePolicyGuard]
#   IDEMPOTENT: returns an existing app["dataplane_guard"] unchanged (:332-334); None (and sets nothing) when PBAC can't init.

# app.py:108-113 — qry = QuerySource(lazy=False); qry.setup(self.app); then BotManager(...).setup(self.app); AuthHandler().setup(app) (:296-297)
# navigator_auth auth.py:469 api_login; :684-685 GET/POST /api/v1/login; header X-Auth-Method selects the backend (:343);
#   BasicAuth payload keys: username_attribute (AUTH_USERNAME_ATTRIBUTE) + "password" (backends/basic.py:47, :137-144);
#   the response JSON carries "token" (basic.py:290).

# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent: __init__(self, name="Agent", agent_id="agent", use_llm="google", llm=None, tools=None, ..., **kwargs)  # :84-96
#   agent_tools() is called INSIDE __init__ (:154) and registered via tool_manager.register_tools (handles AbstractToolkit,
#   AbstractTool and @tool-decorated callables — tools/manager.py:785-840). self._dataplane_guard is still None at that point,
#   so read it lazily at call time.
class Agent(BasicAgent): def agent_tools(self) -> List[AbstractTool]   # :1520-1525
async def configure(self, app=None) -> None                           # agent.py:177
# bots/info.py:37 — class InfoAgent(NarrativeMixin, InfographicAuthoringMixin, Agent) — the MRO pattern to copy

# parrot/tools/decorators.py:59-167 — @tool(name=..., description=...) sets _is_tool/_tool_metadata; schema from type hints
#   (so keep pctx/guard OUT of the decorated signature).
# packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py:83-121 — PublishSurfaceTool(bot=None, surface_store=None, agent_id=None,
#   user_id=None, session_id=None, linked_service=None, **kwargs) (+ guard= after TASK-3837). With a bot exposing publish_surface
#   (InfographicAuthoringMixin), it delegates; the mixin's linked path uses bot._dataplane_guard (infographic_authoring.py:534-545).

# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
#   POST dispatch by path suffix: /refresh → _refresh, /share → _mint_share, else _pin_save (:402-409)
#   _linked_service(): app["linked_surface_service"] or LinkedSurfaceService(guard=app.get("dataplane_guard")) (:346-356)
#   _pin_save → 201 {"surface_id"}; linked 403 on no guard / deny (:575-583)
#   _refresh: 409 when not record.refreshable (:630-638); share-bearer uses ?share=<token>; owner_pctx from record.user_id (:647)
#   _refresh_linked: 403 {"message": "Linked surfaces require a data-plane guard"} | 403 "Data source not permitted";
#     409 {"status":"error","error":"stale refresh","snapshot_at":...}; header X-Parrot-Refresh-Warnings = json.dumps(warnings) (:688-736)
#   _mint_share → 201 {"status":"success","token","expires_at","permissions"} (:787-819)
# resolve_surface_access (:196-210): owner → ok; scope grant → ok; token → store.resolve_share + claim_share; bad token → 410
# models/ui_surfaces.py:85 refreshable = recipe_name is not None or has_data_sources(envelope)
#   store.mint_share(surface_id, *, expires_at=None, use_default_ttl=False) -> UISurfaceShare (:697)
#   store.resolve_share(token) -> UISurfaceShare | None (:733); store.claim_share(token, user_id) -> None (:745)
#   The duplicated _FakeConn (test_linked_surfaces_e2e.py:70-109) does NOT implement share SQL → monkeypatch these three methods.
# service.py:161-171 — refresh params: key naming a source with a mapping value = per-source; everything else broadcast.
# service.py:184-189 — warnings "source <k>: ignored params [...]" for undeclared/locked names.

# QS routes (5.1.2, QSP/services.py:381-418): POST /api/v1/{tenant}/queries/{slug}; alias /api/v1/queries/{tenant}/{slug};
#   POST /api/v3/queries/{slug} for public. No v3 tenant route.
# QuerySlugSource: qs_cls(slug=..., conditions=merged, **{tenant, principal, definition non-None}) (query_slug.py:106-110, :214);
#   is_multiquery → _get_multiqs(); result, _ = await qy.query(); _select_multi_frame raises RuntimeError on missing/ambiguous (:238-280)
#   → execute_sources maps it to SourceOutcome(error="data_stage").
```

### Does NOT Exist
- ~~`examples/agents/a2ui/linked_e2e/`~~ before this feature. TASK-3832 creates `seed_staging.py` and
  `policies/`, and TASK-3838 creates `dashboard_tool.py`. `examples/` is not a package, so load sibling
  modules by path (`importlib.util.spec_from_file_location`) or put the example directory on `sys.path`.
- ~~A `staging` pytest marker~~ in either marker list (verified `pytest.ini:4-10`, `pyproject.toml:118-127`).
- ~~`AuthHandler(backends=[BasicAuth])` with a class~~: `backends` takes dotted strings
  (`"navigator_auth.backends.BasicAuth"`).
- ~~`BotManager(policy_dir=...)`~~: the guard's policy dir comes only from `PARROT_PBAC_POLICY_DIR` at import
  time, or from a pre-set `app["dataplane_guard"]`.
- ~~Anonymous share-token access~~: the handler decorators are class-level (`@is_authenticated`,
  handlers/ui_surfaces.py:313-315). The bearer must also be logged in.
- ~~A v3 tenant route~~, and ~~persisting `/refresh` params~~ (spec §7).
- ~~Deterministic 409 "stale refresh" via `asyncio.gather` offline~~: the fake store is sequential. Offline,
  use the `lose_race` monkeypatch (test_linked_surfaces_e2e.py:413-417). `gather` is only for staging.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "examples/agents/a2ui/linked_e2e/server.py", "action": "CREATE"},
    {"path": "examples/agents/a2ui/linked_e2e/agent.py", "action": "CREATE"},
    {"path": "examples/agents/a2ui/linked_e2e/run_e2e.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/integration/test_linked_e2e_staging.py", "action": "CREATE"},
    {"path": "pytest.ini", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/pyproject.toml", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_bot",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.setup",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._setup_dataplane_guard",
    "sym:packages/ai-parrot/src/parrot/auth/pbac.py#setup_dataplane_guard",
    "sym:packages/ai-parrot/src/parrot/auth/context.py#_pctx_var",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#build_principal_context",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#Agent",
    "sym:packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py#InfographicAuthoringMixin",
    "sym:packages/ai-parrot/src/parrot/tools/decorators.py#tool",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py#installed_version",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py#execute_sources",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py#LinkedSurfaceService",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/conditions.py#derive_conditions",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#UISurfacesHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#PgUISurfaceStore",
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#UISurfaceShare",
    "sym:packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py#_handler",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#_get_qs",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#_get_multiqs"
  ]
}
```

---

## Implementation Notes

### Decisions (fixed)
- **Guard wiring**: `create_app` calls `setup_dataplane_guard(app, policy_dir=<example>/policies)`
  synchronously, BEFORE `bot_manager.setup(app)`. BotManager's own `_setup_dataplane_guard` startup hook
  then finds `app["dataplane_guard"]` (idempotent, pbac.py:332-334), reuses it and injects it into the
  agent. There is only one guard, and `PARROT_PBAC_POLICY_DIR` is not needed. The spec's QuerySource →
  PBAC → BotManager → AuthHandler order is preserved.
- **Negative 403 modes**: `create_app(guard_mode=...)` accepts three values.
  - `"policy"` (default): the example policies.
  - `"deny"`: an empty temporary policy dir, so the guard exists and denies → 403 "Data source not permitted".
  - `"none"`: no `setup_dataplane_guard` call, with `PARROT_PBAC_POLICY_DIR` pointed at a nonexistent dir
    before any parrot import. No guard exists → 403 "Linked surfaces require a data-plane guard".

  `run_e2e.py` accepts `--deny-base-url` and `--noguard-base-url` for servers started in those modes.
  When a URL is not given, that check is reported as `SKIP` (never as a pass). The offline tier covers
  both 403s deterministically.
- **Envelope source for S1/S2**: by default `run_e2e.py` calls the TOOL in-process with `snapshot=False` (no
  LLM needed) and publishes the result through `POST /api/v1/ui/surfaces`. The server then snapshots it
  once, under the owner pctx and the guard. `--via-agent` instead drives
  `POST /api/v1/agents/chat/epson_linked?output_mode=a2ui`. It asserts that the response carries
  `a2ui_envelope` (this exercises TASK-3835) and publishes that envelope.
- **Share bearer**: `E2E_SHARE_USER` / `E2E_SHARE_PASSWORD` log in a second user, who refreshes with
  `?share=<token>`. If they are absent, the same user is reused and the result detail says so.
- **Agent key**: register with `bot_manager.add_bot(agent)` and `name="epson_linked"`, because
  `get_bot(name)` looks the agent up by name.

### Key Constraints
- The staging tier refuses non-staging targets: skip unless `ENV == "staging"`, `installed_version() >= 5.1.2`,
  and `E2E_USER`/`E2E_PASSWORD` are set (§9 S9). Never write to production.
- A `SKIP` result never counts as passed, and `main()` returns 1 if any check failed.
- Offline tests must not boot `QuerySource.setup`, because 5.1.x startup needs Postgres (spec §7). They drive
  the handler directly, like `test_linked_surfaces_e2e.py`.
- Keep each file block ≤ 80 lines. `run_e2e.py` is split into blocks R1-R4 below. Append them in order.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `staging` marker to `pytest.ini` and to the server `pyproject.toml` first. Every later test file uses the marker.
2. Write `agent.py`. `server.py` imports it.
3. Write `server.py`. Verify `create_app("policy")` builds without starting: the routes are registered and `app["dataplane_guard"]` is set when navigator-auth is present.
4. Write `run_e2e.py` (R1-R4). The scenario functions are the single source of truth; the staging pytest calls them.
5. Write `test_linked_e2e_offline.py` and make it green. It is the deterministic tier for S1/S3/S5.
6. Write `test_linked_e2e_staging.py`. Collect it without `ENV=staging` and confirm every test is skipped.
7. If staging credentials are available, run `run_e2e.py` against staging and record the table in the Completion Note.

### `pytest.ini` (MODIFY)
```ini
# occurrences: 1 (verified: grep -c 'live_google: Opt-in paid' pytest.ini)
# AFTER — insert below `    live_google: Opt-in paid Google GenAI (Veo/Omni/Lyria) reel smoke tests. ...` (verified: pytest.ini:10)
    staging: Live tests against env/staging (FEAT-611). Skipped unless ENV=staging, querysource>=5.1.2 and E2E_USER/E2E_PASSWORD are set; never deterministic.
```
**Why**: a root-level run collects the staging tests. An unregistered marker warns, and it would error under `--strict-markers`.

### `packages/ai-parrot-server/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '"e2e: test lives under an e2e/ directory (FEAT-563 auto-mark)",' packages/ai-parrot-server/pyproject.toml)
# AFTER — insert below `    "e2e: test lives under an e2e/ directory (FEAT-563 auto-mark)",` (verified: packages/ai-parrot-server/pyproject.toml:127)
    "staging: live tests against env/staging (FEAT-611); skipped unless ENV=staging and querysource>=5.1.2",
```
**Why**: the server package's rootdir uses its own `[tool.pytest.ini_options]`, not `pytest.ini`.

### `examples/agents/a2ui/linked_e2e/agent.py` (CREATE)
```python
"""EpsonLinkedAgent — FEAT-611 M9 example agent: QuerysourceToolkit + Epson dashboard TOOL + publish_surface."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from parrot.auth.context import _pctx_var
from parrot.bots import Agent
from parrot.bots.mixins.infographic_authoring import InfographicAuthoringMixin
from parrot.tools import tool
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from parrot_tools.ui_surfaces import PublishSurfaceTool

HERE = Path(__file__).resolve().parent
AGENT_NAME = "epson_linked"


def _load_dashboard_tool():
    """Load the sibling dashboard_tool.py by path (examples/ is not a package)."""
    spec = importlib.util.spec_from_file_location("linked_e2e_dashboard_tool", HERE / "dashboard_tool.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EpsonLinkedAgent(InfographicAuthoringMixin, Agent):
    """Emits Epson linked surfaces (qs_build_linked_surface / build_epson_activity_dashboard) and publishes them."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("name", AGENT_NAME)
        kwargs.setdefault("agent_id", AGENT_NAME)
        super().__init__(**kwargs)

    def agent_tools(self) -> list:
        """QuerysourceToolkit + dashboard TOOL closure + PublishSurfaceTool(bot=self)."""
        dashboard = _load_dashboard_tool()
        agent = self

        @tool(name="build_epson_activity_dashboard")
        async def build_epson_activity_dashboard(
            firstdate: str = "FDOM", lastdate: str = "TODAY",
            programs: list[str] | None = None, snapshot: bool = True,
        ) -> dict:
            """Compose the Epson activity dashboard (KPIs, visits-by-day bar, attainment table, date + program filters)."""
            pctx = _pctx_var.get()
            # FILL IN: when pctx is None and agent._dataplane_guard is set, resolve the caller's pctx from the
            #   current request/user context the bot exposes, or leave None so the TOOL fails closed
            #   (AuthorizationRequired) — bounded by §9 S4; never fall back to an unguarded call when a guard exists
            return await dashboard.build_epson_activity_dashboard(
                firstdate, lastdate, programs, snapshot,
                pctx=pctx, guard=getattr(agent, "_dataplane_guard", None),  # read lazily: injected at startup
            )

        return [
            *super().agent_tools(),
            QuerysourceToolkit(),
            build_epson_activity_dashboard,
            PublishSurfaceTool(bot=self),
        ]
```
**Why this shape**:
- `agent_tools()` runs inside `__init__` (agent.py:154), before BotManager injects `_dataplane_guard`, so
  the closure reads the guard at call time.
- `pctx` and `guard` stay out of the `@tool` signature, because the schema is generated from type hints
  (decorators.py:128-131) and the LLM must never supply them.
- The mixin comes first in the MRO (the InfoAgent pattern), so `PublishSurfaceTool(bot=self)` delegates to
  `publish_surface`, which uses the injected guard.

### `examples/agents/a2ui/linked_e2e/server.py` (CREATE)
```python
"""FEAT-611 M9 example server: QuerySource → data-plane guard → BotManager(EpsonLinkedAgent) → AuthHandler(BasicAuth).

    ENV=staging python examples/agents/a2ui/linked_e2e/server.py --port 5000 [--guard-mode policy|deny|none]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY_DIR = HERE / "policies"
GUARD_MODES = ("policy", "deny", "none")
logger = logging.getLogger("examples.a2ui.linked_e2e.server")


def create_app(guard_mode: str = "policy"):
    """Build the aiohttp app in the spec §3 M9 mount order. `guard_mode` selects the S1 403 variants."""
    if guard_mode not in GUARD_MODES:
        raise ValueError(f"guard_mode must be one of {GUARD_MODES}")
    if guard_mode == "none":
        # parrot.conf reads PARROT_PBAC_POLICY_DIR at import time (conf.py:118) — set before importing parrot.
        os.environ["PARROT_PBAC_POLICY_DIR"] = str(HERE / "_no_policies_here")
    from aiohttp import web
    from navigator_auth import AuthHandler
    from querysource.services import QuerySource

    from parrot.auth.pbac import setup_dataplane_guard
    from parrot.manager import BotManager

    sys.path.insert(0, str(HERE))
    from agent import EpsonLinkedAgent  # noqa: E402 — sibling example module

    app = web.Application()
    QuerySource(lazy=False).setup(app)                                     # 1. /api/v3 + /api/v1/{tenant}/queries
    if guard_mode != "none":
        policy_dir = POLICY_DIR if guard_mode == "policy" else Path(tempfile.mkdtemp(prefix="linked-e2e-deny-"))
        guard = setup_dataplane_guard(app, policy_dir=str(policy_dir))    # 2. BEFORE BotManager: its hook reuses it
        logger.info("data-plane guard=%s policy_dir=%s", type(guard).__name__ if guard else None, policy_dir)
    manager = BotManager(enable_database_bots=False, enable_registry_bots=False)  # 3.
    manager.add_bot(EpsonLinkedAgent())       # BEFORE startup: _setup_dataplane_guard only walks registered bots
    manager.setup(app)
    # FILL IN: if BotManager.on_startup/load_bots does not configure bots added via add_bot, append an on_startup
    #   hook `await agent.configure(app)` — bounded by manager.py:2735-2765 (verify) and agent.py:177
    AuthHandler(backends=["navigator_auth.backends.BasicAuth"]).setup(app)  # 4. /api/v1/login (dotted-string backends)
    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--guard-mode", choices=GUARD_MODES, default="policy")
    args = parser.parse_args(argv)
    if os.environ.get("ENV") != "staging":
        raise SystemExit("linked_e2e server refuses to start unless ENV=staging (spec §5: no production writes)")
    from aiohttp import web

    web.run_app(create_app(args.guard_mode), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```
**Why**:
- Every import happens inside `create_app`, so the `guard_mode="none"` environment override lands before
  `parrot.conf` is imported.
- The "deny" mode uses an empty temporary directory, which keeps the demo policy file untouched.
- If `setup_pbac` returns `(None, None, None)` for an empty directory, the "deny" mode degenerates to "none".
  In that case, write a `default-deny` YAML into the temp dir instead, and record the change as a deviation.

### `examples/agents/a2ui/linked_e2e/run_e2e.py` (CREATE) — block R1: context, login, helpers
```python
"""FEAT-611 M9 asserting HTTP runner — S1/S2/S3/S5 against a running linked_e2e server (staging only).

    ENV=staging E2E_USER=... E2E_PASSWORD=... python examples/agents/a2ui/linked_e2e/run_e2e.py --base-url http://127.0.0.1:5000
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

HERE = Path(__file__).resolve().parent
MQ_SLUG = "epson_activity_vs_targets_mq"  # == seed_staging.MQ_SLUG (TASK-3832)


@dataclass
class ScenarioResult:
    id: str
    passed: bool
    detail: str
    skipped: bool = False


@dataclass
class E2EContext:
    session: aiohttp.ClientSession
    base_url: str
    token: str
    share_token_user: str | None = None          # bearer JWT of the second (share) user, when configured
    deny_base_url: str | None = None
    noguard_base_url: str | None = None
    via_agent: bool = False
    state: dict[str, Any] = field(default_factory=dict)  # surface ids etc. shared between checks

    def headers(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.token}", "Content-Type": "application/json"}


async def login(session: aiohttp.ClientSession, base_url: str, user: str, password: str) -> str:
    """POST /api/v1/login with X-Auth-Method: BasicAuth (NA auth.py:684); returns the bearer token."""
    user_key = os.environ.get("AUTH_USERNAME_ATTRIBUTE", "username")  # BasicAuth.username_attribute
    async with session.post(f"{base_url}/api/v1/login", json={user_key: user, "password": password},
                            headers={"X-Auth-Method": "BasicAuth"}) as resp:
        body = await resp.json(content_type=None)
        if resp.status != 200 or "token" not in body:
            raise RuntimeError(f"login failed ({resp.status}): {body}")
        return body["token"]


def check(results: list[ScenarioResult], sid: str, ok: bool, detail: str) -> bool:
    results.append(ScenarioResult(sid, bool(ok), detail))
    return bool(ok)


def skip(results: list[ScenarioResult], sid: str, detail: str) -> None:
    results.append(ScenarioResult(sid, False, detail, skipped=True))


def load_dashboard_tool():
    spec = importlib.util.spec_from_file_location("linked_e2e_dashboard_tool", HERE / "dashboard_tool.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def publish(ctx: E2EContext, envelope: dict, title: str, base_url: str | None = None) -> tuple[int, dict]:
    """POST /api/v1/ui/surfaces {kind: dashboard, title, envelope} → (status, body)."""
    async with ctx.session.post(f"{base_url or ctx.base_url}/api/v1/ui/surfaces", headers=ctx.headers(),
                                json={"kind": "dashboard", "title": title, "envelope": envelope}) as resp:
        return resp.status, await resp.json(content_type=None)
```

### `run_e2e.py` — block R2: S1 (append)
```python
async def refresh(ctx: E2EContext, surface_id: str, params: dict, *, token: str | None = None,
                  share: str | None = None) -> tuple[int, dict, dict]:
    url = f"{ctx.base_url}/api/v1/ui/surfaces/{surface_id}/refresh" + (f"?share={share}" if share else "")
    async with ctx.session.post(url, headers=ctx.headers(token), json={"params": params}) as resp:
        return resp.status, await resp.json(content_type=None), dict(resp.headers)


async def run_s1(ctx: E2EContext) -> list[ScenarioResult]:
    """Server lane + share + PBAC (spec §2 S1, including every negative case)."""
    results: list[ScenarioResult] = []
    tool = load_dashboard_tool()
    envelope = (await tool.build_epson_activity_dashboard(snapshot=False))["a2ui_envelope"]
    # FILL IN: when ctx.via_agent, replace `envelope` with the chat response's a2ui_envelope["createSurface"]
    #   from POST /api/v1/agents/chat/epson_linked?output_mode=a2ui {"query": ...} — bounded by TASK-3835 (v1.0 wrapper)
    status, body = await publish(ctx, envelope, "FEAT-611 S1")
    if not check(results, "s1.publish", status == 201, f"{status} {body}"):
        return results
    sid = ctx.state["s1_surface_id"] = body["surface_id"]
    # FILL IN: GET /api/v1/ui/surfaces/{sid} (200, dataModel rows present) and ?format=html (200) — no execution
    #   implied by an unchanged snapshot_at between the two GETs — bounded by spec §2 S1 "(no execution)"
    status, body, headers = await refresh(ctx, sid, {"firstdate": "FDOM", "lastdate": "TODAY"})
    check(results, "s1.refresh_params", status == 200, f"{status}")
    status, _, headers = await refresh(ctx, sid, {"activity": {"store_id": 7}})
    check(results, "s1.warnings_undeclared", "X-Parrot-Refresh-Warnings" in headers, headers.get("X-Parrot-Refresh-Warnings", "missing"))
    # FILL IN: mint share (POST .../share → 201 token); refresh as bearer with ?share=<token> using
    #   ctx.share_token_user (or ctx.token, noting "same user" in detail) → 200 — bounded by handlers/ui_surfaces.py:196-210, :647
    # FILL IN: 409 baked non-recipe — publish an envelope with NO parrot_data_sources (e.g. strip metadata.extensions and
    #   rows-bindings → a static Column/Text surface), then refresh → 409 {"refreshable": false} — bounded by :630-638
    # FILL IN: 409 stale — asyncio.gather(refresh(...), refresh(...)); pass when statuses contain 200 and 409 with
    #   body["error"] == "stale refresh"; if both 200 (no race won), record SKIP not pass — bounded by :716-727
    for sid_key, url, expect in (("s1.403_no_policy", ctx.deny_base_url, "Data source not permitted"),
                                 ("s1.403_no_guard", ctx.noguard_base_url, "Linked surfaces require a data-plane guard")):
        if url is None:
            skip(results, sid_key, "server URL for this guard mode not given")
            continue
        status, body = await publish(ctx, envelope, sid_key, base_url=url)
        check(results, sid_key, status == 403 and expect in json.dumps(body), f"{status} {body}")
    return results
```
**Why**:
- `snapshot=False` keeps the client from fetching rows before the server authorizes them. The server
  snapshots once, under the owner pctx (§9 S4).
- Per-source params (`{"activity": {...}}`) exercise the service's per-source branch (service.py:167). The
  undeclared name must come back in the warnings header.
- The 403 checks against another server reuse the same token only if both servers share the auth DB. Log in
  again on those URLs if they do not.

### `run_e2e.py` — block R3: S2 + S3 (append)
```python
async def run_s2(ctx: E2EContext) -> list[ScenarioResult]:
    """Dashboard TOOL envelope publishes (validates server-side) and a FilterBar-param refresh changes rows."""
    results: list[ScenarioResult] = []
    tool = load_dashboard_tool()
    result = await tool.build_epson_activity_dashboard(snapshot=False)
    status, body = await publish(ctx, result["a2ui_envelope"], "FEAT-611 S2")
    if not check(results, "s2.publish_validates", status == 201, f"{status} {body}"):
        return results
    sid = body["surface_id"]
    # FILL IN: refresh with {"activity": {"firstdate": A}} and then {"activity": {"firstdate": B}} for two ranges
    #   KNOWN to have data (from TASK-3832 findings F020 — an empty range is a 502 data_stage, spec §7) and assert
    #   the /activity/rows differ between them while /targets/rows are unchanged — bounded by spec §2 S2
    return results


async def run_s3(ctx: E2EContext) -> list[ScenarioResult]:
    """Multiquery DataTable over MQ_SLUG: multi_output / 'result' fallback / ambiguous → error (spec §2 S3)."""
    results: list[ScenarioResult] = []
    from parrot.outputs.a2ui.linked.conditions import derive_conditions  # noqa: PLC0415 — only for descriptor build
    from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest  # noqa: PLC0415

    request = SourceRequest(placeholders={"firstdate": "FDOM", "lastdate": "TODAY"})
    for case, multi_output, expect_ok in (("multi_output", "targets", True), ("result_fallback", None, True)):
        source = LinkedDataSource(slug=MQ_SLUG, is_multiquery=True, multi_output=multi_output,
                                  conditions=derive_conditions(request, locked={}), request=request, target="/mq/rows")
        # FILL IN: wrap `source` in a one-DataTable envelope (columns present in that frame, per TASK-3832's MQ
        #   definition), publish, refresh; pass when status == 200 (expect_ok) — bounded by query_slug.py:238-280
    # FILL IN: ambiguous case — the seed's two outputs with multi_output=None and no 'result' frame is impossible
    #   for MQ_SLUG (it has 'result'), so name a non-existent multi_output ("nope") and assert publish/refresh
    #   fails with a data_stage status (502) — bounded by query_slug.py:258-264 (missing multi_output raises)
    return results
```

### `run_e2e.py` — block R4: S5 + main (append)
```python
async def run_s5(ctx: E2EContext) -> list[ScenarioResult]:
    """tenant='public' descriptor: browser route /api/v1/public/queries/{slug} and /refresh both equal S1 rows."""
    results: list[ScenarioResult] = []
    body = {"firstdate": "FDOM", "lastdate": "TODAY", "querylimit": 5000}
    async with ctx.session.post(f"{ctx.base_url}/api/v1/public/queries/epson_field_activity",
                                headers=ctx.headers(), json=body) as resp:
        tenant_rows = await resp.json(content_type=None)
        check(results, "s5.tenant_route", resp.status == 200, f"{resp.status}")
    # FILL IN: fetch the same slug via POST /api/v3/queries/epson_field_activity (public lane) and assert equal rows;
    #   publish a one-Chart envelope whose descriptor has tenant="public", refresh it, and assert its
    #   dataModel rows == the S1 surface's /activity/rows after an identical-params refresh — bounded by spec §2 S5
    return results


def _print_table(results: list[ScenarioResult]) -> None:
    width = max((len(r.id) for r in results), default=10)
    for r in results:
        verdict = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
        print(f"{r.id:<{width}}  {verdict:<4}  {r.detail[:160]}")


async def run_all(ctx: E2EContext, scenarios: list[str]) -> list[ScenarioResult]:
    runners = {"s1": run_s1, "s2": run_s2, "s3": run_s3, "s5": run_s5}
    results: list[ScenarioResult] = []
    for name in scenarios:
        results.extend(await runners[name](ctx))
    return results


def main(argv: list[str] | None = None) -> int:
    """Exit code 0 only when every non-skipped check passed (and at least one ran)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("E2E_BASE_URL", "http://127.0.0.1:5000"))
    parser.add_argument("--deny-base-url")
    parser.add_argument("--noguard-base-url")
    parser.add_argument("--via-agent", action="store_true")
    parser.add_argument("--scenarios", default="s1,s2,s3,s5")
    args = parser.parse_args(argv)
    if os.environ.get("ENV") != "staging":
        print("run_e2e refuses to run unless ENV=staging", file=sys.stderr)
        return 2
    # FILL IN: asyncio.run(...) — open ClientSession, login(E2E_USER/E2E_PASSWORD) (+ optional share user), build
    #   E2EContext, run_all, _print_table; return 0 iff any(not r.skipped) and all(r.passed for r in non-skipped)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### `packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py` (CREATE) — block O1: harness
```python
"""FEAT-611 M9 — offline deterministic tier for S1/S3/S5 (FakeQS + fake guard; no Postgres, no QuerySource.setup)."""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import parrot.tools.dataset_manager.sources.query_slug as query_slug
from parrot.auth.exceptions import AuthorizationRequired
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, UISurfaceShare
from parrot.handlers.ui_surfaces_scope import SurfaceScope
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService

from .test_linked_surfaces_e2e import _FakeAsyncDB, _StubResolver, _decode, _get, _handler, _post

pytestmark = pytest.mark.asyncio
REPO = Path(__file__).resolve().parents[4]
EXAMPLE = REPO / "examples/agents/a2ui/linked_e2e"
ACTIVITY = pd.DataFrame({"day": ["2026-09-01", "2026-09-02"], "visits": [10, 20],
                         "program": ["epson", "pokemon"], "store_id": [1, 2]})
TARGETS = pd.DataFrame({"program": ["epson", "pokemon"], "target": [100, 50]})


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"linked_e2e_{name}", EXAMPLE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_qs(monkeypatch):
    """Slug-keyed FakeQS + FakeMultiQS; records kwargs (tenant!) per execution."""
    state = SimpleNamespace(kwargs=[], frames={"epson_field_activity": ACTIVITY, "epson_program_targets": TARGETS},
                            multi={"result": ACTIVITY, "targets": TARGETS})

    class FakeQS:
        def __init__(self, **kwargs):
            state.kwargs.append(kwargs)
            self._slug = kwargs["slug"]

        async def query(self, output_format=None):
            return state.frames[self._slug].copy(), None

        async def close(self):
            return None

    class FakeMultiQS(FakeQS):
        async def query(self, output_format=None):
            return dict(state.multi), None

    monkeypatch.setattr(query_slug, "_get_qs", lambda: FakeQS)
    monkeypatch.setattr(query_slug, "_get_multiqs", lambda: FakeMultiQS)
    return state
```

### `test_linked_e2e_offline.py` — block O2: guard, store with shares, app (append)
```python
class _Guard:
    """Recording guard; denies `source_type:source_id` keys in `deny` (test_service.py:23-34 pattern)."""

    def __init__(self, deny: set[str] | None = None) -> None:
        self.deny, self.calls = deny or set(), []

    async def authorize_source(self, ctx, resources):
        self.calls.append((getattr(ctx, "session", ctx), resources.source_type, resources.source_id))
        if f"{resources.source_type}:{resources.source_id}" in self.deny:
            raise AuthorizationRequired(tool_name="dataplane_authz", message="denied")

    async def rls_predicates(self, ctx, resources):
        return []


@pytest.fixture
def store(monkeypatch):
    """Real PgUISurfaceStore over the duplicated fake connection + in-memory share methods."""
    state = SimpleNamespace(surfaces={}, ddl_calls=[], shares={})
    value = PgUISurfaceStore(dsn="postgres://fake/linked-e2e-offline")
    monkeypatch.setattr(value, "_get_db", lambda: _FakeAsyncDB(state))

    async def mint_share(surface_id, *, expires_at=None, use_default_ttl=False):
        share = UISurfaceShare(token=f"tok-{len(state.shares)}", surface_id=surface_id, created_at=datetime.now(UTC))
        state.shares[share.token] = share
        return share

    async def resolve_share(token):
        return state.shares.get(token)

    async def claim_share(token, user_id):
        return None

    for name, fn in (("mint_share", mint_share), ("resolve_share", resolve_share), ("claim_share", claim_share)):
        monkeypatch.setattr(value, name, fn)
    return value


def _app(store, guard=None, *, user_id="owner-1"):
    app = {"ui_surfaces_store": store,
           "ui_surfaces_scope_resolver": _StubResolver(SurfaceScope(user_id=user_id, tenant=None, groups=frozenset()))}
    if guard is not None:
        app["linked_surface_service"] = LinkedSurfaceService(guard=guard)
    return app
```

### `test_linked_e2e_offline.py` — block O3: tests (append)
```python
async def test_s1_server_lane_offline(fake_qs, store):
    """Publish → GET → refresh(params) → share → bearer refresh; plus 403 / 409 / warnings (spec §4)."""
    tool = _load("dashboard_tool")
    envelope = (await tool.build_epson_activity_dashboard(snapshot=False))["a2ui_envelope"]
    guard = _Guard()
    app = _app(store, guard)
    resp = await _post(_handler(app, path="/api/v1/ui/surfaces",
                                json_body={"kind": "dashboard", "title": "S1", "envelope": envelope}))
    assert resp.status == 201
    sid = (await _decode(resp))["surface_id"]
    # FILL IN (each its own assert block, reusing _handler/_get/_post exactly as test_linked_surfaces_e2e.py):
    #   GET json + ?format=html (importorskip interactive_html as :391-394) with no new fake_qs.kwargs;
    #   refresh {"params": {"firstdate": "2026-09-02", "lastdate": "2026-09-03"}} → 200 and the last activity-slug
    #   kwargs["conditions"] carry those dates; refresh {"params": {"activity": {"store_id": 7}}} → header
    #   X-Parrot-Refresh-Warnings contains "store_id"; mint share (path .../share) → 201 token; bearer refresh with
    #   _handler(_app(store, guard, user_id="viewer-2"), user_id="viewer-2", query={"share": token}) → 200 and the
    #   guard's last call ctx is the OWNER (user "owner-1"); 403 no guard (_app(store) without service and
    #   no "dataplane_guard") and 403 deny (_Guard(deny={"query_slug:public:epson_field_activity"})) on publish;
    #   409 baked non-recipe (publish a static envelope, refresh → 409 refreshable False); 409 stale via the
    #   lose_race monkeypatch of store.update_envelope (test_linked_surfaces_e2e.py:399-429)
    #   — bounded by spec §2 S1 negatives and handlers/ui_surfaces.py:617-736


async def test_s3_multiquery_frames(fake_qs):
    """multi_output / 'result' fallback / ambiguous-or-missing → data_stage (execute_sources, spec §4)."""
    # FILL IN: build LinkedDataSource(slug="epson_activity_vs_targets_mq", is_multiquery=True, multi_output=X,
    #   conditions=derive_conditions(req, locked={}), request=req, target="/mq/rows") for X in ("targets", None);
    #   execute_sources → rows equal TARGETS / ACTIVITY records; then fake_qs.multi = {"a": ..., "b": ...} with
    #   multi_output=None → outcome.error == "data_stage", and multi_output="nope" → "data_stage"
    #   — bounded by query_slug.py:238-280 and executor.py:216-220


async def test_s5_tenant_descriptor(fake_qs):
    """tenant='public' reaches QS as tenant='public' and yields the same rows as the tenant=None descriptor."""
    # FILL IN: execute_sources for two otherwise-identical activity descriptors (tenant=None vs "public");
    #   assert rows equal and fake_qs.kwargs[-1]["tenant"] == "public" while the tenant=None call has no "tenant"
    #   key (QuerySlugSource._qs_kwargs drops None, query_slug.py:106-110); with a _Guard + pctx assert
    #   source_id == "public:epson_field_activity" for both — bounded by spec §2 S5 and service.py:100
```
**Why**:
- These tests import the handler harness from `test_linked_surfaces_e2e.py` rather than copy another 100
  lines. That module's own fixtures are not imported, so nothing collides.
- If a relative import from a test module fails under the chosen rootdir, copy `_FakeConnCtx`, `_FakeConn`
  and `_FakeAsyncDB` into block O1 verbatim, and note the deviation.
- S3 and S5 call `execute_sources` directly: the handler adds nothing to frame selection or tenant routing.

### `packages/ai-parrot-server/tests/integration/test_linked_e2e_staging.py` (CREATE)
```python
"""FEAT-611 M9 — live staging tier (§9 S9): same assertions as run_e2e.py; never the deterministic verdict."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
RUN_E2E = REPO / "examples/agents/a2ui/linked_e2e/run_e2e.py"


def _qs_ok() -> bool:
    try:
        from parrot_tools.querysource._qs import installed_version
    except ImportError:
        return False
    major, minor, patch = (int(p) for p in installed_version().split(".")[:3])
    return (major, minor, patch) >= (5, 1, 2)


pytestmark = [
    pytest.mark.staging,
    pytest.mark.asyncio,
    pytest.mark.skipif(os.environ.get("ENV") != "staging", reason="staging tier: ENV=staging required"),
    pytest.mark.skipif(not _qs_ok(), reason="querysource >= 5.1.2 required"),
    pytest.mark.skipif(not (os.environ.get("E2E_USER") and os.environ.get("E2E_PASSWORD")),
                       reason="E2E_USER / E2E_PASSWORD not set"),
]


def _runner():
    spec = importlib.util.spec_from_file_location("linked_e2e_run_e2e", RUN_E2E)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def ctx():
    """Log in against E2E_BASE_URL (a running server.py) and yield an E2EContext."""
    # FILL IN: aiohttp.ClientSession; token = await run_e2e.login(...); yield run_e2e.E2EContext(session, base_url,
    #   token, deny_base_url=os.environ.get("E2E_DENY_BASE_URL"), noguard_base_url=os.environ.get("E2E_NOGUARD_BASE_URL"));
    #   close the session — bounded by run_e2e.E2EContext fields (block R1)


@pytest.mark.parametrize("scenario", ["s1", "s2", "s3", "s5"])
async def test_staging_scenario(ctx, scenario):
    run_e2e = _runner()
    results = await getattr(run_e2e, f"run_{scenario}")(ctx)
    failed = [r for r in results if not r.skipped and not r.passed]
    assert results and not failed, "\n".join(f"{r.id}: {r.detail}" for r in failed)
```
**Why**:
- Three independent `skipif`s make the skip reason explicit. The version gate uses `installed_version()`
  (the spec's `test_querysource_version_gate` lives in TASK-3831).
- The staging tier drives the same functions as `run_e2e.py`, so the two tiers cannot drift apart.

### FILL IN checklist
- [ ] `agent.py::build_epson_activity_dashboard` closure — the pctx fallback when `_pctx_var` is empty. Bounded by §9 S4 (fail closed when a guard exists).
- [ ] `server.py::create_app` — whether bots added with `add_bot` need an explicit `configure(app)` startup hook. Bounded by manager.py:2735-2765 and agent.py:177.
- [ ] `run_e2e.py::run_s1` — the via-agent envelope, the GET json/html checks, share + bearer refresh, the baked 409, and the stale 409 via `gather` (SKIP when no race is won). Bounded by handlers/ui_surfaces.py:617-819.
- [ ] `run_e2e.py::run_s2` — two data-bearing ranges from TASK-3832's F020, with rows that differ. Bounded by spec §7 (DataNotFound → 502).
- [ ] `run_e2e.py::run_s3` — the per-case DataTable envelope, plus a missing `multi_output` → 502. Bounded by query_slug.py:238-280.
- [ ] `run_e2e.py::run_s5` — v3 vs tenant-route rows, and tenant-descriptor refresh rows == S1. Bounded by spec §2 S5.
- [ ] `run_e2e.py::main` — `asyncio.run` orchestration and the exit-code rule. Bounded by "SKIP never counts as pass".
- [ ] `test_linked_e2e_offline.py::test_s1_server_lane_offline` — every S1 leg and negative case. Bounded by spec §4 integration table.
- [ ] `test_linked_e2e_offline.py::test_s3_multiquery_frames` / `test_s5_tenant_descriptor`. Bounded by query_slug.py:106-110 and :238-280.
- [ ] `test_linked_e2e_staging.py::ctx` — session and login lifecycle. Bounded by block R1.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py` passes. It covers S1 (including the no-guard 403, the deny 403, the baked 409, the stale 409 and the warnings header), S3 (multi_output / result / missing → data_stage) and S5 (tenant="public").
- [ ] `test_linked_e2e_staging.py` is collected and fully skipped without `ENV=staging`. It is marked `staging`, and the marker is registered in both `pytest.ini` and the server `pyproject.toml`.
- [ ] `server.create_app("policy")` mounts QuerySource → guard → BotManager (+EpsonLinkedAgent registered before startup) → AuthHandler. `app["dataplane_guard"]` is set once and reused by BotManager.
- [ ] With `ENV=staging`, `run_e2e.py` exits 0 when every non-skipped check passes, and non-zero otherwise. SKIP rows are printed as SKIP (spec §5).
- [ ] No production writes: `server.py` and `run_e2e.py` refuse to run unless `ENV=staging`.
- [ ] `ruff check examples/agents/a2ui/linked_e2e/server.py examples/agents/a2ui/linked_e2e/agent.py examples/agents/a2ui/linked_e2e/run_e2e.py packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py packages/ai-parrot-server/tests/integration/test_linked_e2e_staging.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py -q`
- `pytest packages/ai-parrot-server/tests/integration/test_linked_e2e_staging.py -q`
- `pytest packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py -q`

---

## Test Specification

Required node ids (frozen for spec §4 E2E Scenarios):
- `test_linked_e2e_offline.py::test_s1_server_lane_offline` → `s1-server-lane`
- `test_linked_e2e_offline.py::test_s3_multiquery_frames` → `s3-multiquery`
- `test_linked_e2e_offline.py::test_s5_tenant_descriptor` → `s5-tenant-route`
- `test_linked_e2e_staging.py::test_staging_scenario[s1|s2|s3|s5]` → the live tier (`-m staging`)

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-linked-e2e-parallel --feature-id FEAT-611`).
2. **Read the spec**, especially §2 S1/S3/S5 negatives, §7 gotchas and §9 S9.
3. **Check dependencies**. TASK-3831, TASK-3832, TASK-3834, TASK-3835, TASK-3837 and TASK-3838 must all be `"done"`.
4. **Verify the Codebase Contract**. Re-grep every path:line, especially BotManager startup and handler line numbers.
5. **Update status** to `"in-progress"`, and commit only the index file.
6. **Implement** from blocks. Append blocks R1→R4 and O1→O3 in order, and complete every `FILL IN`.
7. **Verify**: run the Validation Commands. With staging credentials, also run `run_e2e.py` and paste its table into the Completion Note.
8. **Commit** only the files this task lists.
9. **Close** with `scripts/sdd/close_task.sh TASK-3839 a2ui-linked-e2e-parallel verified`.
10. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented. Include the `run_e2e.py` result table (or "staging not run: <reason>").

**Deviations from spec**: none | describe if any
