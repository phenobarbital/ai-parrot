# TASK-3957: [W0.2] Host mount hooks — prefix, view_wrapper, studio_routes flag, setup_registry_only (M4)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3956
**Assigned-to**: unassigned
**Spec task label**: W0.2 (spec §3 "Task plan") — **early subset** (§3 "Early subset and release gate"; no sibling-spec dependency)

---

## Context

Spec §2 "Host mount", "Registry-only lifecycle" items 1 (manager-level part only), Module 4, G6,
C5/C32/C39, §8 Q1. Today `setup_studio_routes(app)` (`studio/__init__.py:26`) hard-codes
`STUDIO_PREFIX`, registers parrot's bare view classes, appends `reconcile_skills_catalog` on every
call (`:88`), and `BotManager.setup()` mounts `/api/v1/astudio` unconditionally (`manager.py:2568`).
A multi-tenant host (FieldSync) needs: a `{tenant}` prefix, a `view_wrapper` to put its seam
prologue in front of every Studio view, a way to suppress the default mount, idempotent
registration, and a public registry-only loader that does not call `setup()` (which also mounts
chat, crews, A2UI, unscoped surfaces, the admin SPA and the PBAC guard).

This task ships the manager-level lifecycle for NON-Studio bots only. The Studio runtime call
(`add_studio_runtime_hooks`) is TASK-3965 (W2.2), because it needs FEAT-621 W2.

Unblocks: **U-FS** (FieldSync mount can be implemented against dev; NOT recommended for a tenant
release before W2.2 — say so in docstrings).

---

## Scope

- `setup_studio_routes(app, *, prefix=None, view_wrapper=None)`: `prefix=None` ⇒ `STUDIO_PREFIX`;
  `view_wrapper` called **once per distinct view class** (cache per call), result passed to
  `add_view` for every route of that class; a `None` result skips every route of that class.
- Idempotent per prefix (app key `_astudio_mounted_prefixes`); a second call with the same prefix is
  a logged no-op. Startup hooks (`reconcile_skills_catalog` today) appended **once per app**,
  whatever the number of prefixes (app key `_astudio_startup_installed`) — expose a tiny helper so
  FEAT-621's `resolve_studio_storage` and TASK-3971's `cleanup_studio_assistants` use the same guard.
- Split the route list into per-area helpers so no function exceeds 60 lines (AC22).
- `BotManager.setup(..., studio_routes: bool = True)`; `False` skips the call at `manager.py:2568`.
- `BotManager.setup_registry_only(app, *, import_modules=False, load_definitions=False)`: public,
  idempotent (app key); sets `self.app` and `app["bot_manager"]`; appends exactly ONE `on_startup`
  hook (`registry.setup(app)` + optional imports + start the legacy `_cleanup_expired_bots` loop),
  ONE `on_shutdown` hook (cancel the loop), ONE `on_cleanup` hook (`_cleanup_all_bots`).
  Registers no route; no startup agents, DB bots, crews, chat storage, Redis, PBAC guard.
  **§8 Q1**: when `has_installed_resolver(app)` and `import_modules` or `load_definitions` is True ⇒
  `RuntimeError` at setup.
- Tests: `test_setup_twice_single_hook`, `test_studio_routes_flag`, `test_registry_only_no_routes`,
  `test_registry_only_manager_lifecycle`, prefixed-route + wrapper + skip tests.

**NOT in scope**: `_scope()` / tenant_mismatch (TASK-3959 — the end-to-end `test_wrapper_prologue_runs_before_scope` lives there); `/me` route (TASK-3960); the call to FEAT-621 `add_studio_runtime_hooks` (TASK-3965); `cleanup_studio_assistants` (TASK-3971); any Studio instance cleanup.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | `prefix`/`view_wrapper`, per-prefix idempotency, once-per-app startup-hook guard, per-area route helpers |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `setup(studio_routes=)`; new `setup_registry_only(app, *, import_modules=False, load_definitions=False)` + its three hooks |
| `packages/ai-parrot-server/tests/studio/test_host_mount.py` | CREATE | Mount tests: prefixed routes, wrapper once per class, `None` skips, idempotency, single startup hook |
| `packages/ai-parrot-server/tests/manager/test_registry_only.py` | CREATE | `setup(studio_routes=False)`, registry-only: zero routes, one hook per signal, legacy loop lifecycle, Q1 refusal |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified for this task at `32b1a45d4`, `dev`). The implementing agent MUST use these
> exact imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed, VERIFY it
> exists first with `grep` or `read`. Paths are relative to the repo root unless a line says
> otherwise; `S/` = `packages/ai-parrot-server/src/parrot/handlers/`.

### Verified Imports
```python
from aiohttp import web  # verified: S/studio/__init__.py:21
from parrot.handlers.scope import has_installed_resolver  # created by TASK-3956
from parrot.handlers.studio import STUDIO_PREFIX, setup_studio_routes  # verified: S/studio/__init__.py:23,26 ; tests/studio/test_scaffold.py:15
from parrot.manager.manager import BotManager  # verified: tests/manager/test_reload_agent.py:17-20
from parrot.handlers.studio.skills_catalog import reconcile_skills_catalog  # verified: S/studio/__init__.py:70-75
```

### Existing Signatures to Use
```python
# S/studio/__init__.py
STUDIO_PREFIX = "/api/v1/astudio"                          # :23
def setup_studio_routes(app: web.Application) -> None:      # :26 ; routes :44-145 ; on_startup.append(reconcile_skills_catalog) :88
#   ordering constraint kept: literal /skills/resync BEFORE dynamic /skills/{id} (:79-84)
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:
    self._cleanup_task: Optional[asyncio.Task] = None       # :219
    async def load_bots(self, app) -> None                  # :396 ; self.registry.setup(app) :408 ; load_modules :411 ;
                                                            #   YAML definitions_dir = self.registry.agents_dir / "agents" :418-420 ; startup agents :424
    async def _cleanup_all_bots(self, ...)                  # :1693
    def setup(self, app, *, agent_mount_config=None, agent_mount_auth_template=None,
              agent_mount_pbac_resolver=None, agent_mount_audit_sink=None) -> web.Application  # :2239
        self.app.on_startup.append(self.on_startup)          # :2284
        self.app.on_shutdown.append(self.on_shutdown)        # :2285
        self.app.on_cleanup.append(self._cleanup_all_bots)   # :2288
        self.app["bot_manager"] = self                       # :2295
        setup_studio_routes(self.app)                        # :2568
    async def _cleanup_expired_bots(self)                   # :2631 (loop; started only by on_startup :2776)
    async def on_startup(self, app)                         # :2740 ; create_task(_cleanup_expired_bots) :2776
    async def on_shutdown(self, app)                        # :2806 ; cancels _cleanup_task :2809-2815
```

### Does NOT Exist
- ~~`setup_studio_routes(prefix=…, view_wrapper=…)`~~, ~~`BotManager.setup(studio_routes=…)`~~, ~~`BotManager.setup_registry_only`~~ — created here
- ~~the expiry task or `on_shutdown`/`on_cleanup` hooks outside `BotManager.setup()`~~ (`manager.py:2284-2288`, `:2776`) — this task adds the registry-only equivalents
- ~~cleanup inside `remove_bot`~~ (`:870-874`) — do not add it
- ~~`add_studio_runtime_hooks`~~, ~~`manager/studio_runtime.py`~~, ~~`ensure_studio_storage`~~, ~~`resolve_studio_storage`~~ — FEAT-621 W1/W2; NOT called here (TASK-3965)
- ~~a composite `on_startup` hook or storage "extension points" in `setup_registry_only`~~ — dropped by C39; do not create
- ~~`/api/v1/{tenant}/astudio`~~ — no such route today

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_host_mount.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/manager/test_registry_only.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py#setup_studio_routes",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.setup",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_bots",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.on_startup",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.on_shutdown",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._cleanup_expired_bots",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._cleanup_all_bots"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Route registration stays plain `app.router.add_view()` (never `AbstractModel.configure()` — catch-all `{id:.*}` trap, `__init__.py:34-37`).
- Lifecycle shape mirrors `setup()` (`manager.py:2284-2288`) and `on_startup`/`on_shutdown` (`:2776`, `:2809-2815`), restricted to registry + legacy expiry loop.

### Key Constraints
- `view_wrapper` cache is per call (dict `{cls: wrapped_or_None}`); never call the wrapper twice for one class within a call (AC16).
- The host's seam prologue must run before Studio's scope resolution: never resolve anything at class creation or in `__init__` (spec §2 "Host mount").
- Idempotency keys are app keys, not module globals (a test process builds many apps).
- `setup_registry_only` never imports `AGENTS_DIR` modules or YAML definitions by default (spec §8 "Registry-only default content"); with an installed resolver, `import_modules=True` or `load_definitions=True` raises `RuntimeError` at setup (Q1).
- Manager-level hooks never touch a Studio instance (X8): they only operate on `BotManager._bots`.
- Docstring of `setup_registry_only` states "incomplete lifecycle — not recommended to tenant hosts until W2.2 (TASK-3965) merges".

### Cross-feature ordering (package X16)
- Cross-feature ordering: no sibling dependency (early subset, X16).
- Cross-feature ordering: `studio/__init__.py` is also edited by FEAT-621 W1 "Backend selection + partition hook" (registers `resolve_studio_storage`) — serialise, whichever merges first; whichever lands second must put `resolve_studio_storage` behind this task's once-per-app startup guard (X10).
- Cross-feature ordering: `manager/manager.py` is also edited by FEAT-621 W2 "Runtime + cache + lifecycle + builder + BotManager hooks" — serialise, whichever merges first (small non-overlapping edits, X16); FEAT-621 must NOT edit `setup_registry_only` (C39).

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` — full route list to re-home under `base`
- `packages/ai-parrot-server/tests/studio/test_scaffold.py` — existing mount tests that must stay green (default prefix)
- `packages/ai-parrot-server/tests/manager/test_reload_agent.py` — BotManager construction pattern in tests

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. In `__init__.py`, add the app keys, `_install_startup_hook_once(app, hook)` and a `_Registrar` (base prefix + wrapper cache) — *why*: one place enforces "wrapper once per class" and "None skips".
2. Move the existing `add_view` calls into per-area helpers that take the registrar (`_register_agents`, `_register_drafts`, `_register_files`, `_register_skills`, `_register_keys`, `_register_testing`, `_register_toolkits`, `_register_catalog`, `_register_assistant`) keeping the exact current order — *why*: route order matters (`/skills/resync` before `/skills/{id}`) and AC22 caps function length.
3. Rewrite `setup_studio_routes` per the block; replace the bare `app.on_startup.append(reconcile_skills_catalog)` with `_install_startup_hook_once` — *why*: AC17.
4. Add `studio_routes: bool = True` to `BotManager.setup` and guard the call at `:2568` — *why*: AC18.
5. Add `setup_registry_only` + `_registry_only_startup` / `_registry_only_shutdown` — *why*: G6 / AC18 (manager-level part).
6. Write the two test modules; run `test_scaffold.py` unchanged.

### `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def setup_studio_routes(app: web.Application) -> None:' __init__.py) — :26
# occurrences: 1 (verified: grep -c '    app.on_startup.append(reconcile_skills_catalog)' __init__.py) — :88 (REMOVE; use the guard)
from collections.abc import Callable
from typing import Any

_STUDIO_MOUNTS_APP_KEY = "_astudio_mounted_prefixes"
_STUDIO_STARTUP_APP_KEY = "_astudio_startup_installed"

ViewWrapper = Callable[[type[web.View]], "type[web.View] | None"]


def install_startup_hook_once(app: web.Application, hook: Any, *, signal: str = "on_startup") -> bool:
    """Append ``hook`` to ``app.<signal>`` at most once per app (X10). Returns True when appended."""
    installed: set = app.setdefault(_STUDIO_STARTUP_APP_KEY, set())
    marker = (signal, getattr(hook, "__qualname__", repr(hook)))
    if marker in installed:
        return False
    installed.add(marker)
    getattr(app, signal).append(hook)
    return True


class _Registrar:
    """Applies ``prefix`` and ``view_wrapper`` (once per class) to every Studio route."""

    def __init__(self, app: web.Application, base: str, view_wrapper: ViewWrapper | None) -> None:
        self.app, self.base, self._wrapper = app, base.rstrip("/"), view_wrapper
        self._cache: dict[type, type | None] = {}

    def add(self, path: str, view: type[web.View]) -> None:
        if view not in self._cache:
            self._cache[view] = view if self._wrapper is None else self._wrapper(view)
        target = self._cache[view]
        if target is not None:
            self.app.router.add_view(f"{self.base}{path}", target)


def setup_studio_routes(
    app: web.Application,
    *,
    prefix: str | None = None,
    view_wrapper: ViewWrapper | None = None,
) -> None:
    """Register every Studio route under ``prefix`` (default STUDIO_PREFIX). Same prefix twice ⇒ no-op."""
    base = prefix or STUDIO_PREFIX
    mounted: set = app.setdefault(_STUDIO_MOUNTS_APP_KEY, set())
    if base in mounted:
        logging.getLogger("Parrot.AgentStudio").info("setup_studio_routes: %s already mounted", base)
        return
    mounted.add(base)
    reg = _Registrar(app, base, view_wrapper)
    for register in (_register_agents, _register_drafts, _register_files, _register_skills,
                     _register_keys, _register_testing, _register_toolkits, _register_catalog,
                     _register_assistant):
        register(reg)
    # FILL IN: install_startup_hook_once(app, reconcile_skills_catalog) (lazy import as today) —
    #   bounded by AC17 (one hook per app across prefixes).
```
**Why**: Names `_STUDIO_MOUNTS_APP_KEY`/`_STUDIO_STARTUP_APP_KEY` are fixed by the spec M4 skeleton. `install_startup_hook_once` is the single guard FEAT-621 (`resolve_studio_storage`) and TASK-3971 (`cleanup_studio_assistants`) must reuse (X10). Add `import logging` at the top.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        setup_studio_routes(self.app)' manager.py) — :2568
        if studio_routes:
            setup_studio_routes(self.app)
# + add keyword-only parameter `studio_routes: bool = True,` to `def setup(` (:2239) after
#   `agent_mount_audit_sink`, and document it in the Args block.

# NEW methods on BotManager (place after `setup`, before `on_startup` :2740):
_REGISTRY_ONLY_APP_KEY = "_bot_manager_registry_only"   # module level

    def setup_registry_only(
        self, app: web.Application, *, import_modules: bool = False, load_definitions: bool = False
    ) -> None:
        """Mount the agent registry without ``setup()`` (spec §2 "Host mount"; X10).

        Idempotent per app. One on_startup, one on_shutdown, one on_cleanup hook — non-Studio bots
        only. Incomplete lifecycle for tenant hosts until W2.2 wires the Studio runtime.
        Raises RuntimeError when a scope resolver is installed and either opt-in flag is True (§8 Q1).
        """
        if (import_modules or load_definitions) and has_installed_resolver(app):
            raise RuntimeError("setup_registry_only: import_modules/load_definitions are refused in a tenant host")
        if app.get(_REGISTRY_ONLY_APP_KEY):
            self.logger.info("setup_registry_only: already installed on this app")
            return
        app[_REGISTRY_ONLY_APP_KEY] = {"import_modules": import_modules, "load_definitions": load_definitions}
        self.app = app
        app["bot_manager"] = self
        app.on_startup.append(self._registry_only_startup)
        app.on_shutdown.append(self._registry_only_shutdown)
        app.on_cleanup.append(self._cleanup_all_bots)

    async def _registry_only_startup(self, app: web.Application) -> None:
        """registry.setup(app) (+ opt-in imports), then start the legacy expiry loop."""
        opts = app[_REGISTRY_ONLY_APP_KEY]
        # FILL IN: if self.enable_registry_bots: self.registry.setup(app); when opts["import_modules"]:
        #   await self.registry.load_modules(); when opts["load_definitions"]: load YAML from
        #   self.registry.agents_dir / "agents" exactly as load_bots :418-420 — bounded by §8 Q1
        #   (nothing imported by default) and "no startup agents" (never instantiate_startup_agents).
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_bots())

    async def _registry_only_shutdown(self, app: web.Application) -> None:
        """Cancel the legacy expiry loop (mirrors on_shutdown :2809-2815)."""
        # FILL IN: cancel + await self._cleanup_task, swallow CancelledError, set it to None.
```
**Why**: AC18: exactly one hook per signal however often it is called. `has_installed_resolver` import comes from TASK-3956 (`from parrot.handlers.scope import has_installed_resolver`). Never call `on_startup` (it loads DB bots, crews, chat storage).

### `packages/ai-parrot-server/tests/studio/test_host_mount.py` (CREATE)
```python
"""FEAT-605 M4 — Studio mount hooks (prefix, view_wrapper, idempotency)."""
from __future__ import annotations

from aiohttp import web
from parrot.handlers.studio import STUDIO_PREFIX, setup_studio_routes

TENANT_PREFIX = "/api/v1/{tenant}/astudio"


def _paths(app: web.Application) -> list[str]:
    return [r.resource.canonical for r in app.router.routes() if r.resource is not None]


def test_prefixed_routes_resolve_with_router_tenant(): ...   # FILL IN: aiohttp_client, match_info["tenant"]
def test_wrapper_called_once_per_class(): ...                # FILL IN: count calls per distinct class
def test_wrapper_none_skips_class(): ...                     # FILL IN: e.g. StudioKeysHandler ⇒ no /keys routes
def test_setup_twice_single_hook(): ...                      # FILL IN: same prefix twice ⇒ same routes, one reconcile hook;
                                                             #   two prefixes ⇒ one reconcile hook (mutation: drop the guard ⇒ RED)
def test_default_prefix_unchanged(): ...                     # FILL IN: no args ⇒ every route under STUDIO_PREFIX
```
**Why**: Spec §4 mutation row `idempotent hooks` names `test_setup_twice_single_hook`.

### `packages/ai-parrot-server/tests/manager/test_registry_only.py` (CREATE)
```python
"""FEAT-605 M4 — BotManager.setup(studio_routes=) and setup_registry_only (manager-level lifecycle)."""
from __future__ import annotations

import pytest
from aiohttp import web
from parrot.manager.manager import BotManager


def test_studio_routes_flag(): ...                    # FILL IN: setup(app, studio_routes=False) ⇒ no /api/v1/astudio route
def test_registry_only_no_routes(): ...               # FILL IN: zero routes; app["bot_manager"] is the manager
def test_registry_only_hooks_once(): ...              # FILL IN: two calls ⇒ exactly one hook per signal
async def test_registry_only_manager_lifecycle(aiohttp_client): ...
    # FILL IN: start the app ⇒ _cleanup_task running exactly once; shutdown cancels it; _cleanup_all_bots runs once;
    #   no Studio hook installed. Mutation: skip starting the loop ⇒ RED.
def test_registry_only_refuses_imports_in_tenant_host(): ...   # FILL IN: app["scope_resolver"] set + import_modules=True ⇒ RuntimeError
```
**Why**: Spec §4 unit rows `test_studio_routes_flag`, `test_registry_only_no_routes`, `test_registry_only_manager_lifecycle`.

### FILL IN checklist
- [ ] `__init__.py::_register_*` — move every existing `add_view` call, same order, `reg.add("/agents", StudioAgentsHandler)` style; bounded by `test_scaffold.py` staying green
- [ ] `__init__.py::setup_studio_routes` — reconcile hook through `install_startup_hook_once`; bounded by AC17
- [ ] `manager.py::_registry_only_startup` — registry setup + opt-in imports; bounded by §8 Q1 and "no startup agents"
- [ ] `manager.py::_registry_only_shutdown` — cancel the loop; bounded by `on_shutdown` :2809-2815 semantics
- [ ] test bodies in both modules; bounded by AC16-AC18

---

## Acceptance Criteria

- [ ] AC16 (mount part): `setup_studio_routes(..., view_wrapper=w)` registers `w(cls)` for every route of every view class, calls `w` once per class, skips classes for which `w` returns `None`
- [ ] AC17: calling `setup_studio_routes` twice with the same prefix adds no route and no startup hook; startup hooks are installed once per app across prefixes
- [ ] AC18 (manager-level part): `BotManager.setup(studio_routes=False)` leaves no `/api/v1/astudio` route; `setup_registry_only(app)` sets `app["bot_manager"]`, registers no route, appends exactly one `on_startup`, one `on_shutdown`, one `on_cleanup` hook per app however often it is called
- [ ] §8 Q1: `setup_registry_only(app, import_modules=True)` (or `load_definitions=True`) with an installed resolver raises `RuntimeError`; nothing is imported by default
- [ ] Mutation: skip starting the legacy loop ⇒ `test_registry_only_manager_lifecycle` RED; drop the once-per-app guard ⇒ `test_setup_twice_single_hook` RED
- [ ] `tests/studio/test_scaffold.py` green unchanged; no function > 60 lines / complexity > 10 in the diff

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_host_mount.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_registry_only.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_scaffold.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_host_mount.py
def test_prefixed_routes_resolve_with_router_tenant(): ...
def test_wrapper_called_once_per_class(): ...
def test_wrapper_none_skips_class(): ...
def test_setup_twice_single_hook(): ...
# packages/ai-parrot-server/tests/manager/test_registry_only.py
def test_studio_routes_flag(): ...
def test_registry_only_no_routes(): ...
def test_registry_only_hooks_once(): ...
async def test_registry_only_manager_lifecycle(aiohttp_client): ...
def test_registry_only_refuses_imports_in_tenant_host(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-tenant-visibility --feature-id FEAT-605`)
2. **Read the spec** at the path listed above for full context (§2 is normative; §3 has the task table)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-tenant-visibility.json`, AND every
   "Cross-feature ordering" item in Implementation Notes must hold (sibling feature tasks merged)
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Re-run each blueprint `grep -c` anchor; a count of `0` means drift — stop and report
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-tenant-visibility.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands, and run each
   listed mutation check (revert the guard, see the named test go RED, restore by re-applying
   the edit — never with `git checkout` of the file)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3957 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
