# TASK-4480: SemanticLayerHandler HTTP routes + manager registration (M11a)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4479
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 (handler) + AC14: `SemanticLayerHandler(BaseView)` with a role-filtered catalog GET and compile/query/hand-off POSTs; `PermissionContext` from the navigator-auth session; routes registered only when `parrot.semantic` is importable; 401 without a session.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/handlers/semantic.py`.
- Register the two views in `manager.py` behind `importlib.util.find_spec("parrot.semantic")`.
- Hand-off factory = the per-user, per-agent `DatasetManager` resolved like `DatasetManagerHandler._get_dataset_manager` (datasets.py:162) — call the module-level `_resolve_dataset_manager` helper.
- Write `packages/ai-parrot-server/tests/handlers/test_semantic_handler.py`.

**NOT in scope**: changes to `handlers/datasets.py` (owned by TASK-4482); MCP/docs (TASK-4481).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/semantic.py` | CREATE | SemanticLayerHandler |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | guarded route registration |
| `packages/ai-parrot-server/tests/handlers/test_semantic_handler.py` | CREATE | routes + 401 tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from aiohttp import web
from navigator.views import BaseView                                   # verified: packages/ai-parrot-server/src/parrot/handlers/datasets.py:19
from navigator_auth.decorators import is_authenticated, user_session   # verified: handlers/datasets.py:20
from navigator_session import get_session                              # verified: handlers/datasets.py:21
from parrot.auth import PermissionContext, UserSession                 # verified: auth/__init__.py lazy map
# handlers/datasets.py module-level helper (server package, relative import from handlers/semantic.py):
from .datasets import _resolve_dataset_manager                         # verified: handlers/datasets.py:91 (async def _resolve_dataset_manager(request, agent_id, session_key, logger))
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/datasets.py
async def _resolve_dataset_manager(request: web.Request, agent_id: str, session_key: str, logger: object)   # line 91
class DatasetManagerHandler(BaseView):   # line 141 — decorators + user_objects_handler.get_session_key(agent_id, "dataset_manager") (162-177)
# packages/ai-parrot-server/src/parrot/manager/manager.py
from ..handlers.datasets import DatasetManagerHandler                                  # line 45
router.add_view("/api/v1/agents/datasets/{agent_id}", DatasetManagerHandler)          # line 2571
router.add_view("/api/v1/agents/datasets/{agent_id}/{dataset_id}", DatasetManagerHandler)   # line 2572
```

### Does NOT Exist
- ~~`packages/ai-parrot-server/tests/unit/`~~ — does not exist; server handler tests live in `packages/ai-parrot-server/tests/handlers/` (spec Edit Sites row drift).
- ~~A module-level `from parrot.semantic import ...` in handlers/semantic.py~~ — import lazily inside methods so the server imports without the satellite.
- ~~How the agent exposes its configured toolkit~~ — FILL IN: read how `DatasetManagerHandler` finds the agent (BotManager lookup in `_resolve_dataset_manager`) and locate the agent's `SemanticLayerToolkit` instance among its tools; 404 when absent.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/semantic.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_semantic_handler.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/datasets.py#DatasetManagerHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/datasets.py#_resolve_dataset_manager"
  ]
}
```

---

## Implementation Notes

- Session id for result handles: put the navigator session id into `PermissionContext.extra['session_id']` (TASK-4476 reads it there).
- Errors map: `SemanticAccessError` → 403, `SemanticValidationError` → 400, `SemanticResultError` → 404, `SemanticExecutionError` → 502; never include SQL beyond the governed SQL the toolkit already returns.

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Write the handler (lazy satellite import) — *why*: server must import without the satellite.
2. Register routes guarded by find_spec — *why*: AC14.
3. Write tests.

### `packages/ai-parrot-server/src/parrot/handlers/semantic.py` (CREATE)
```python
"""HTTP surface of the semantic layer (FEAT-704 spec §3 Module 11)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session

from ..auth import PermissionContext, UserSession

if TYPE_CHECKING:
    from parrot.semantic import SemanticLayerToolkit


@is_authenticated()
@user_session()
class SemanticLayerHandler(BaseView):
    """GET catalog; POST compile | query | results/{result_id}/dataset for /api/v1/agents/semantic/{agent_id}."""

    async def get(self) -> web.Response:
        """Role-filtered catalog for {agent_id}."""
        # FILL IN: tk = await self._toolkit(agent_id); run tk.list_models under the session pctx
        raise NotImplementedError

    async def post(self) -> web.Response:
        """Dispatch on the tail route: compile | query | results/{result_id}/dataset."""
        # FILL IN: tail = self.request.match_info.get("tail", ""); parse JSON body into SemanticQuery
        #   (ValidationError -> 400); call the toolkit through its tool path with _permission_context=pctx
        raise NotImplementedError

    async def _toolkit(self, agent_id: str) -> "SemanticLayerToolkit":
        """Agent's configured toolkit (lazy import of parrot.semantic); 404 when the agent has none."""
        raise NotImplementedError

    async def _pctx(self) -> PermissionContext:
        """From the navigator-auth session; 401 when absent."""
        # FILL IN: mirror how DatasetManagerHandler reads the session user (datasets.py); session id -> extra
        raise NotImplementedError
```
**Why**: same decorator pattern as `DatasetManagerHandler` (datasets.py:141); `..auth` matches the server's relative-import style (verify — if datasets.py imports `parrot.auth` absolutely, do the same).

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F '        router.add_view("/api/v1/agents/datasets/{agent_id}/{dataset_id}", DatasetManagerHandler)' manager.py)
# AFTER — insert below that line (verified: manager.py:2572)
        # Semantic layer (FEAT-704) — only when the opt-in satellite is installed.
        if importlib.util.find_spec("parrot.semantic") is not None:
            from ..handlers.semantic import SemanticLayerHandler
            router.add_view("/api/v1/agents/semantic/{agent_id}", SemanticLayerHandler)
            router.add_view("/api/v1/agents/semantic/{agent_id}/{tail:.*}", SemanticLayerHandler)
```
**Why**: AC14. FILL IN: `manager.py` imports `contextlib, os, time, asyncio, copy` at lines 10-14 — add `import importlib.util` there if it is not already imported (grep first).

### FILL IN checklist
- [ ] Handler bodies — bounded by AC14 and the error map in Notes.
- [ ] Agent→toolkit lookup.
- [ ] `import importlib.util` in manager.py if missing.

---

## Acceptance Criteria

- [ ] `test_handler_routes_and_401` passes: routes registered only when `parrot.semantic` is importable (monkeypatch find_spec), 401 without a session (AC14).
- [ ] Server package imports with the satellite absent.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-server/tests/handlers/test_semantic_handler.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_semantic_handler.py
import pytest


def test_handler_routes_and_401(monkeypatch):
    # FILL IN: find_spec("parrot.semantic") -> None => no /api/v1/agents/semantic routes; present => routes;
    #          aiohttp test client without session -> 401 (follow test_knowledge_handler.py's client setup)
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4480 — SemanticLayerHandler HTTP routes + manager registration (M11a)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4480 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
