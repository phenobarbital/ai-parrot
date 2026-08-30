# TASK-2584: Admin catalog endpoint + codegen models for the agent form

**Feature**: FEAT-475 — UI Agent Management — Admin UI Agent CRUD
**Spec**: `sdd/specs/ui-agent-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Python half" item 3, §2 Data Models, §3 Module 2, §8 Q2
(resolved: no hardcoded KB list — the server serves the options). The form
needs LLM providers, `operation_mode`/`memory_type` enums and KB class
options from the server, plus generated TS types for every payload it
sends/receives.

---

## Scope

- Create `parrot/server/ui/catalog.py` with Pydantic models
  `KnowledgeBaseOption`, `AdminCatalog`, a pure `build_catalog() -> AdminCatalog`
  and `AdminCatalogHandler(BaseView)` (`@is_authenticated() @user_session()`,
  `GET` → `AdminCatalog` JSON).
  - `llm_providers`: keys of `SUPPORTED_CLIENTS` deduplicated **by class**
    (keep the first key encountered per class), sorted.
  - `operation_modes = ["conversational","agentic","adaptive"]`,
    `memory_types = ["memory","file","redis"]` (mirror `BotModel.__post_init__`).
  - `knowledge_bases`: `RedisKnowledgeBase` always; `LocalKB` only if the
    lazy import succeeds (wrap in `try/except Exception`); each as
    `{class_path, name, description=first docstring line}`.
  - `bot_class_default = "BasicBot"`.
- Register the view in `setup_admin_ui()` at `/api/v1/admin/catalog`, next
  to the status view (API registers even when `dist/` is absent).
- Extend `parrot/server/ui/models.py` with codegen descriptors `ToolInfo`,
  `ToolsListResponse`, `BotWritePayload` (alias for `model_config`, see
  contract), `BotMutationResponse` exactly as in spec §2 Data Models.
- Add all six models to `scripts/generate_ts_types.py::_models()`, run it,
  then `pnpm generate` in `packages/ai-parrot-server/ui`; commit the
  regenerated `ui/schemas/*.json` and `ui/src/lib/types/generated/*.d.ts`.
- Tests.

**NOT in scope**: any UI component; `ToolList` registration (TASK-2583).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/server/ui/catalog.py` | CREATE | models + `build_catalog` + handler |
| `packages/ai-parrot-server/src/parrot/server/ui/models.py` | MODIFY | add 4 codegen descriptors |
| `packages/ai-parrot-server/src/parrot/server/ui/serving.py` | MODIFY | `add_view("/api/v1/admin/catalog", AdminCatalogHandler)` |
| `scripts/generate_ts_types.py` | MODIFY | add models to `_models()` |
| `packages/ai-parrot-server/ui/schemas/*.json` | CREATE | regenerated |
| `packages/ai-parrot-server/ui/src/lib/types/generated/*.d.ts` | CREATE | regenerated via `pnpm generate` |
| `packages/ai-parrot-server/tests/test_admin_catalog.py` | CREATE | auth, shape, degradation |
| `packages/ai-parrot-server/tests/test_ts_codegen.py` (existing, FEAT-468; contract corrected — task named `test_generate_ts_types.py`, actual file is `test_ts_codegen.py`) | VERIFY | `test_schemas_in_sync_with_committed` generically diffs every model in `_models()` against `ui/schemas/*.json`, so it already covers the 6 new models with no edit needed — confirmed green after regenerating schemas |
| `packages/ai-parrot-server/tests/test_admin_ui_serving.py` (existing, FEAT-468) | MODIFY | `TestAbsentDist::test_absent_dist_returns_false_and_registers_no_spa_routes` asserted the route set registered with no `dist/` present was exactly `{"/api/v1/admin/status"}`; the new `/api/v1/admin/catalog` route is UI-agnostic by design (spec §3 Module 2 — registers even when `dist/` is absent), so this pre-existing assertion needed the new path added to stay accurate, not a scope change |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.server.ui import setup_admin_ui                                  # server/ui/__init__.py
from parrot.server.ui.status import AdminStatusHandler                       # server/ui/status.py (pattern to copy)
from parrot.server.ui.models import BotAgentItem, BotsListResponse           # server/ui/models.py:19, :41
from parrot.clients.factory import SUPPORTED_CLIENTS                         # clients/factory.py:107 — dict[str, type]
from parrot.stores.kb import AbstractKnowledgeBase, RedisKnowledgeBase       # stores/kb/__init__.py:3-4
from parrot.stores.kb import LocalKB   # lazy __getattr__ kb/__init__.py:17-22 — REQUIRES ai-parrot-embeddings; wrap in try/except
from navigator_auth.decorators import is_authenticated, user_session
from navigator.views import BaseView
from pydantic import BaseModel, ConfigDict, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/server/ui/serving.py
def setup_admin_ui(app, *, prefix=DEFAULT_PREFIX) -> bool     # :156
    app.router.add_view("/api/v1/admin/status", AdminStatusHandler)   # :195  ← add catalog view right after

# packages/ai-parrot-server/src/parrot/server/ui/status.py — copy the decorator/handler/response pattern:
#   @is_authenticated() @user_session() class AdminStatusHandler(BaseView): async def get(self) -> web.Response
#   returns self.json_response(model.model_dump(mode="json")) (verify exact helper used there)

# packages/ai-parrot-server/src/parrot/server/ui/models.py
class BotAgentItem(BaseModel): model_config = ConfigDict(extra="allow"); name: str; source: Literal[...]   # :19
class BotsListResponse(BaseModel): agents: list[BotAgentItem]; total: int                                # :41

# scripts/generate_ts_types.py
def _models() -> dict[str, type[BaseModel]]   # :45-63 — extend the returned mapping
SCHEMAS_DIR = REPO_ROOT / "packages" / "ai-parrot-server" / "ui" / "schemas"   # :42

# packages/ai-parrot/src/parrot/clients/factory.py:107  SUPPORTED_CLIENTS = { 'claude': ..., 'anthropic': ..., 'google': ..., 'openai': ..., ... }
#   many alias keys map to the same class (claude/anthropic, xai/grok, local/localllm/ollama, …) → dedup by class
# packages/ai-parrot-server/src/parrot/handlers/models/bots.py:300-317  __post_init__ validates operation_mode / memory_type / tool_threshold
# packages/ai-parrot-server/ui/package.json  "generate": "json2ts -i schemas -o src/lib/types/generated --bannerComment ..."
```

### Does NOT Exist
- ~~`/api/v1/admin/catalog`, `parrot/server/ui/catalog.py`~~ — new.
- ~~`/api/v1/models`, `/api/v1/providers`, `/api/v1/embeddings`~~ — none exist; do not add them.
- ~~a KB instance registry (`KB_REGISTRY`, `list_kbs()`)~~ — only classes.
- ~~`BotModel.model_json_schema()`~~ — `BotModel` is not Pydantic; that is why `BotWritePayload` exists.
- **Pydantic gotcha**: `model_config` is reserved on `BaseModel`; declare the field as
  `model_config_: dict[str, Any] | None = Field(default=None, alias="model_config")` and set
  `ConfigDict(populate_by_name=True, extra="forbid")` so the JSON Schema/TS wire name is `model_config`.

---

## Implementation Notes

- `build_catalog()` must be import-safe and side-effect-free; unit-test it
  directly without aiohttp.
- Handler tests: reuse the harness from `tests/test_admin_status.py`
  (unauthenticated → 401, authenticated short-circuit).
- Run codegen from the worktree with
  `PYTHONPATH="$(pwd)/packages/ai-parrot-server/src:$(pwd)/packages/ai-parrot/src" python scripts/generate_ts_types.py`
  then `cd packages/ai-parrot-server/ui && pnpm install --frozen-lockfile && pnpm generate`.
  Node 24 / pnpm 9 per FEAT-468.

---

## Acceptance Criteria

- [ ] `GET /api/v1/admin/catalog` → 401 unauthenticated; 200 with `AdminCatalog` shape when authenticated
- [ ] Providers sorted, unique by class; enums equal those in `BotModel.__post_init__`
- [ ] `LocalKB` import failure drops the entry, never raises
- [ ] Six new schema files + generated `.d.ts` committed; `ToolInfo`/`ToolsListResponse`/`BotWritePayload`/`BotMutationResponse`/`AdminCatalog`/`KnowledgeBaseOption`
- [ ] Generated `BotWritePayload.d.ts` exposes the property named `model_config`
- [ ] `pytest packages/ai-parrot-server/tests/test_admin_catalog.py packages/ai-parrot-server/tests/test_generate_ts_types.py -v` passes; `pnpm test` still passes

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_admin_catalog.py
def test_build_catalog_shape(): ...
def test_build_catalog_dedups_provider_aliases(): ...
def test_build_catalog_kb_import_failure_degrades(monkeypatch): ...
async def test_catalog_requires_auth(...): ...
async def test_catalog_authenticated(...): ...
```

---

## Agent Instructions

1. Read spec §2 Data Models, §3 Module 2, §6, §8 Q2.
2. Verify contract line numbers; copy the status handler pattern.
3. Implement + codegen + tests; commit generated files.
4. Move to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-30
**Notes**: Created `parrot/server/ui/catalog.py` with `KnowledgeBaseOption`,
`AdminCatalog`, pure `build_catalog()`, and `AdminCatalogHandler`
(`@is_authenticated() @user_session()`, copies the `AdminStatusHandler`
pattern). Provider dedup keeps the first key per resolved client/lazy-
loader value (handles both class-valued and lazy-loader-function-valued
`SUPPORTED_CLIENTS` entries, e.g. `claude-agent`/`claude-code` share one
lazy loader). `LocalKB` import wrapped in `try/except Exception` with a
warning log, never raises. Registered `AdminCatalogHandler` in
`setup_admin_ui()` right after the status view (unconditional, dist-
agnostic). Extended `server/ui/models.py` with `ToolInfo`,
`ToolsListResponse`, `BotWritePayload` (aliased `model_config_` field,
`populate_by_name=True`, confirmed the generated `.d.ts` exposes the wire
name `model_config`), `BotMutationResponse`. Added all 6 new models to
`scripts/generate_ts_types.py::_models()`, ran the script and `pnpm
generate` — 6 new `ui/schemas/*.json` + `.d.ts` files committed.
Added `test_admin_catalog.py` (6 tests: 401/200, shape, dedup, KB
degradation, class_path importability) — all green.
Corrected a stale Codebase Contract entry: the task named
`test_generate_ts_types.py` but the actual FEAT-468 file is
`test_ts_codegen.py`; its `test_schemas_in_sync_with_committed` already
generically diffs every model in `_models()`, so it covers the 6 new
models with no edit — confirmed green.
Fixing `test_admin_ui_serving.py::TestAbsentDist::
test_absent_dist_returns_false_and_registers_no_spa_routes` was required:
it asserted the exact route set registered with `dist/` absent, and the
new catalog route is deliberately dist-agnostic per spec §3 Module 2 (same
pattern as the existing status route) — updated the expected set to
include `/api/v1/admin/catalog`.
Full `packages/ai-parrot-server/tests/` suite: 1293 passed, 7
pre-existing failures unrelated to this task (identical to the FEAT-475
TASK-2583 baseline), 1 skipped. `packages/ai-parrot-server/ui`: `pnpm
test` 59/59 passed unmodified. `ruff check` clean on all touched files.

**Deviations from spec**: none
