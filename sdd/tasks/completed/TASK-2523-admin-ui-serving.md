# TASK-2523: Admin UI serving — `setup_admin_ui(app)`, packaging and BotManager wiring

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Spec**: `sdd/specs/ui-server-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (Python half) + §3 Module 1. The Admin UI SPA must be
served by the aiohttp server itself, library-owned: a `setup_admin_ui(app)`
function in a new `parrot.server.ui` subpackage, called from
`BotManager.setup()`, that mounts the compiled `dist/` when present and
degrades gracefully when absent. This is the foundation every other task
plugs into.

---

## Scope

- Create the `parrot/server/ui/` subpackage (`__init__.py`, `serving.py`)
  in `packages/ai-parrot-server/src/`.
- Implement `setup_admin_ui(app: web.Application, *, prefix: str = "/admin") -> bool`:
  - Resolve dist dir as `Path(__file__).parent / "dist"`.
  - If `dist/index.html` is missing: log ONE `WARNING` and return `False`
    without registering anything.
  - Mount hashed assets: `app.router.add_static(f"{prefix}/assets/",
    path=dist/"assets", show_index=False, follow_symlinks=False)`.
  - Register catch-all `GET /admin{tail:.*}` handler returning
    `web.FileResponse(dist/"index.html")` with `Cache-Control: no-cache`
    on the index; assets get long-cache/immutable headers.
  - Register `/admin*` in navigator-auth's exclude list when an
    `AuthHandler` is installed; no crash when it is not (see contract).
  - The catch-all must NEVER shadow `/api/*` (it is anchored at the
    prefix; add an explicit test).
- Wire `setup_admin_ui(self.app)` into `BotManager.setup()` next to the
  existing `setup_*_routes` calls.
- Add `"parrot.server.ui" = ["dist/*", "dist/assets/*"]` to
  `[tool.setuptools.package-data]` in `packages/ai-parrot-server/pyproject.toml`.
- Add `packages/ai-parrot-server/src/parrot/server/ui/dist/` to `.gitignore`.
- Write unit tests using a fake-dist fixture (`tmp_path` + monkeypatch of
  the dist resolution).

**NOT in scope**: the status endpoint (TASK-2524), the actual Vite build
(TASK-2525), wheel-content assertions and CI (TASK-2531).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/server/ui/__init__.py` | CREATE | exports `setup_admin_ui` |
| `packages/ai-parrot-server/src/parrot/server/ui/serving.py` | CREATE | main implementation |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | one import + one call in `setup()` |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | package-data entry |
| `.gitignore` | MODIFY | ignore the built dist |
| `packages/ai-parrot-server/tests/test_admin_ui_serving.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from navigator_auth import AuthHandler          # installed navigator_auth 0.22.11
# Exclude-list access: the AuthHandler instance is created in app-level code
# (app.py:301-302). From library code, do NOT assume app['auth'] exists —
# see "Existing Signatures" for the safe pattern.
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:  # :109
    def setup(self, app: web.Application) -> web.Application:  # :1686
        # accepts web.Application OR navigator Application (unwraps via app.get_app(), :1688-1690)
        # router obtained at :1708: router = self.app.router
        # module-level setup_* calls at :2039 (setup_credentials_routes),
        # :2041 (setup_mcp_helper_routes), :2043 (setup_thales_routes)
        # → add setup_admin_ui(self.app) in this cluster; imports live at
        #   manager.py:91-98 (from ..handlers.credentials import setup_credentials_routes, …)

# .venv/.../navigator_auth/auth.py (0.22.11)
class AuthHandler:
    def add_exclude_list(self, path: str) -> None: ...        # :728 — fnmatch patterns (:840-842)
    def register_exclusions(self, paths) -> None: ...         # :750
    async def verify_exceptions(self, request) -> bool: ...   # :833
        # :848-855: StaticResource routes and /static/* paths bypass auth
        # middleware automatically. The index-fallback HANDLER is a normal
        # route → it DOES pass through auth middleware unless excluded.
# Exclusion storage: AuthHandler.setup() seeds app[AUTH_EXCLUDE_LIST_KEY] (:595).
# Safe library-side pattern: append the '/admin*' pattern to the app's
# exclude-list key if present (grep navigator_auth.conf for AUTH_EXCLUDE_LIST_KEY
# and import it), OTHERWISE no-op with a debug log. Precedent for degrading
# when navigator_auth is absent: parrot/handlers/web_hitl.py:286-293.

# Static mount precedent — repo-root app.py:94-102 (Telegram):
#   telegram_static = Path(_tg_pkg_file).parent / 'static'
#   self.app.router.add_static('/telegram/', path=telegram_static,
#       name='telegram_static', show_index=False, follow_symlinks=False)

# packages/ai-parrot-server/pyproject.toml:104 —
# [tool.setuptools.package-data]  (globs NON-recursive per key)
#   "parrot.handlers" = ["*.sql"]  … extend with "parrot.server.ui" entry.
```

### Does NOT Exist
- ~~any `/admin` route today~~ — this task creates it (formdesigner
  `templates.py:157,176` already redirects there).
- ~~`add_static`/`web.static` anywhere in `packages/ai-parrot-server/src/`~~
  — zero prior usage in the server package.
- ~~`static/`, `dist/`, `ui/` under `parrot/server/`~~ — package holds only
  `__init__.py` + `version.py` today.
- ~~`app['auth']` guaranteed key~~ — do not assume; use the exclude-list
  key pattern above.
- ~~a shipped app factory~~ — assembly is repo-root `app.py`/`run.py`;
  library mounts MUST be `setup_*(app)` functions.

---

## Implementation Notes

### Pattern to Follow
```python
# handlers/credentials.py:506 — module-level route-group setup
def setup_credentials_routes(app: web.Application) -> None:
    ...
# serving.py mirrors this shape; return bool per spec §2 New Public Interfaces.
```

### Key Constraints
- `parrot.server.ui` needs a real `__init__.py` (parent `parrot/server/`
  already has one — it is NOT a PEP 420 namespace level; do not add
  `__init__.py` anywhere else).
- Warning logged exactly once; module logger via `logging.getLogger(__name__)`.
- Dist resolution must be monkeypatchable for tests (module-level function
  or parameter, not hardcoded inline).
- `test_wheel_layout.py` `FORBIDDEN_INIT_PATHS` (:16-25) does not include
  `parrot/server/*` — no conflict, but do not touch other namespace levels.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/web_hitl.py:286-293` — degrade-without-navigator_auth precedent.
- `packages/ai-parrot-integrations/pyproject.toml:148-150` — package-data HTML/JS precedent.

---

## Acceptance Criteria

- [ ] `from parrot.server.ui import setup_admin_ui` works.
- [ ] Missing dist → returns `False`, zero `/admin` routes, one WARNING.
- [ ] With fake dist → `GET /admin` and `GET /admin/agents` return
  `index.html` (no-cache); `/admin/assets/*` served (long-cache).
- [ ] `/api/v1/anything` never matches the SPA fallback (test).
- [ ] `/admin*` present in the auth exclude list when the key exists; no
  exception when it does not (test both).
- [ ] `BotManager.setup()` calls `setup_admin_ui` (test via stub app).
- [ ] `pytest packages/ai-parrot-server/tests/test_admin_ui_serving.py -v` passes;
  `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_admin_ui_serving.py
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient

@pytest.fixture
def fake_dist(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>admin</html>")
    (dist / "assets" / "app-abc123.js").write_text("//js")
    from parrot.server.ui import serving
    monkeypatch.setattr(serving, "_dist_dir", lambda: dist)
    return dist

async def test_absent_dist_returns_false_and_registers_nothing(caplog): ...
async def test_index_fallback_serves_deep_links(fake_dist): ...
async def test_assets_served_with_long_cache(fake_dist): ...
async def test_api_routes_not_shadowed(fake_dist): ...
async def test_exclude_list_registered_when_auth_present(fake_dist): ...
async def test_no_crash_without_auth_handler(fake_dist): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm every class/method in "Existing Signatures" still matches
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/ui-server-backend.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2523-admin-ui-serving.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-08-27
**Notes**: Implemented `setup_admin_ui(app, *, prefix="/admin")` in
`parrot/server/ui/serving.py`, package-relative dist resolution via
`_dist_dir()` (monkeypatchable), static asset mount, catch-all SPA
fallback anchored at the prefix, and a best-effort navigator-auth
exclude-list registration that no-ops (debug log) when
`AUTH_EXCLUDE_LIST_KEY` is absent from the app. Wired into
`BotManager.setup()` next to the other `setup_*_routes` calls. Added
`"parrot.server.ui" = ["dist/*", "dist/assets/*"]` package-data entry and
gitignored the dist output. 6/6 unit tests pass
(`pytest packages/ai-parrot-server/tests/test_admin_ui_serving.py -v`);
`ruff check` clean on all new/modified files (pre-existing lint debt in
`manager.py` untouched by this diff).

**Post-review fixes**: the adversarial code-reviewer caught two
CRITICAL bugs in the first cut:
1. The SPA fallback route (`"/admin{tail:.*}"`) and the auth exclude
   pattern (`"/admin*"`) were bare string-prefix matches, not
   path-segment-anchored — a future route like `/administer` would be
   silently swallowed by the SPA catch-all, and `fnmatch` has no
   notion of `/` as special, so the same lookalike would also bypass
   auth via the exclude list. Fixed to register an exact-prefix route
   (`GET /admin`) plus a children route (`GET /admin/{tail:.*}`), and
   two segment-boundary exclude patterns (`/admin`, `/admin/*`).
2. (IMPORTANT, also fixed) static assets never actually got
   long-cache/immutable `Cache-Control` headers — `add_static()`/
   `FileResponse` don't set it, despite the docstring and acceptance
   criteria claiming otherwise. Fixed via an `on_response_prepare`
   hook scoped to the assets prefix.

Added regression tests for both (lookalike-route non-shadowing,
segment-boundary exclude patterns, and the actual `Cache-Control`
header value). 14/14 unit tests pass after the fix.

**Deviations from spec**: none

**Post-hoc fix (FEAT-468 final adversarial review, 2026-08-27)**: the
exclude-list registration was still wrong — `_register_auth_exclusion()`
was called eagerly, synchronously, inside `setup_admin_ui()`. In BOTH real
entrypoints (`app.py`, `appauto.py`), `BotManager.setup(app)` (which calls
`setup_admin_ui()`) runs BEFORE `AuthHandler().setup(app)`, and
`AuthHandler.setup()` unconditionally OVERWRITES
`app[AUTH_EXCLUDE_LIST_KEY]` with a fresh list — so `/admin` was NEVER
actually excluded from auth in production, meaning the login page itself
could be blocked. Fixed by deferring registration to an `app.on_startup`
callback (`_register_auth_exclusions_on_startup`), which fires only after
all synchronous `.setup()` calls have completed. Added
`test_survives_real_entrypoint_ordering` reproducing the exact production
ordering as a regression test. See commit
`fix(ui-server-backend): address CRITICAL code-review findings on
FEAT-468`.
