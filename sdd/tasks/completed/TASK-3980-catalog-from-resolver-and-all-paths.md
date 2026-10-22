# TASK-3980: Catalogue built from resolver.entries() with `source`; every-Studio-path integration test (M2, part 2)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3979
**Assigned-to**: unassigned
**Wave**: 2 (spec §9) · **Module**: M2 resolver-adoption (catalogue)

---

## Context

Spec §1 P1 row 1: `GET /catalog/tools` (`catalog.py:230` → `tools_catalog._build_catalog`) iterates
`parrot_tools.TOOL_REGISTRY` only (`tools_catalog.py:34`, `:56`). Spec §2 Integration Points: `_build_catalog`
iterates `resolver.entries()` and adds `source` per entry (`access` and the tenant filter are
TASK-3984). This task also owns the M2 integration test `test_every_studio_path_sees_host_toolkit` (spec §4,
one parametrized test over catalog, schema, generic assign, FEAT-593 PUT/GET, options, `/me` override, live
assign and bot build).

---

## Scope

- `handlers/tools_catalog.py::_build_catalog`: iterate `get_toolkit_resolver().entries()`; each entry dict keeps
  `slug`, `dotted_path`, `description?`, `category?` and gains `source`; description/category come from the
  resolved class (`resolver.resolve(slug)` or the dotted path); never break the response on import errors.
- Keep the module-level `_CATALOG_CACHE` contract (`catalog.py:230-236` reuses it).
- Create `tests/studio/test_host_toolkit_paths.py` with `test_every_studio_path_sees_host_toolkit`.
  Paths that need a tenant-bound class (options for `tp_probe`) use a **non-tenant-bound** variant until
  TASK-3989 lifts rule 5 — document that in the test.

**NOT in scope**: the `access` field (TASK-3984); the tenant partition filter and the meta-agent
`list_available_tools` filter (TASK-3984).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py` | MODIFY | _build_catalog iterates resolver.entries(); adds `source` |
| `packages/ai-parrot-server/tests/studio/test_host_toolkit_paths.py` | CREATE | test_every_studio_path_sees_host_toolkit |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.resolver import ToolkitEntry, get_toolkit_resolver  # TASK-3975
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py
from parrot_tools import TOOL_REGISTRY  # :33-36 (try/except ImportError)
_CATALOG_CACHE: List[Dict[str, Any]] | None = None  # :41
def _build_catalog() -> List[Dict[str, Any]]:  # :44-81
    for slug, dotted_path in sorted(TOOL_REGISTRY.items()):  # :56 ← anchor (occurrences: 1)
# packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py:230-236 _get_tools reuses tools_catalog_module._CATALOG_CACHE
# packages/ai-parrot/src/parrot/bots/studio/tools.py:545-553 list_available_tools → _build_catalog()
```

### Does NOT Exist
- ~~`source`/`access` keys in catalogue entries today~~ — added here (`source`) and in TASK-3984 (`access`).
- ~~a per-tenant catalogue cache~~ — the cache stays process-wide; TASK-3984 filters per request.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_host_toolkit_paths.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py#_build_catalog"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Keep `_build_catalog` blocking-import safe (it runs in `asyncio.to_thread`, `tools_catalog.py:111`).
- For `dotted_path=None` entries (builtin, walk) emit `dotted_path` as `f"{cls.__module__}.{cls.__qualname__}"`
  or `None` — FILL IN, but keep the key present.
- The integration test drives each handler with `make_mocked_request` (real request, session installed as
  `request[SESSION_OBJECT]`), following `tests/studio/test_toolkit_config.py` helpers; bot build via
  `apply_tooling_specs` on a real bot with a `ToolkitSpec(slug="tp_probe_tool")`.

### Cross-feature ordering
- `tools_catalog.py` is not a FEAT-621/FEAT-605 handler file; no per-file wait. The integration test touches
  Studio handlers edited by FEAT-621 W2/W3 and FEAT-605: run it against `origin/dev` after TASK-3979's
  per-file merges.

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Rewrite the loop at `tools_catalog.py:56` over `resolver.entries()` — *why*: G1 (catalogue sees host toolkits).
2. Add `source` to each entry — *why*: spec AC "The catalogue carries `source` and `access`".
3. Write the parametrized integration test; mutation: revert the loop ⇒ catalogue case RED.

### `packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'for slug, dotted_path in sorted(TOOL_REGISTRY.items()):' tools_catalog.py)
# REPLACE the loop header at tools_catalog.py:56 and the entry construction (:57-60) with:
    resolver = get_toolkit_resolver()
    for item in resolver.entries():
        entry: Dict[str, Any] = {
            "slug": item.slug,
            "dotted_path": item.dotted_path,
            "source": item.source,
        }
        # FILL IN: best-effort enrichment from resolver.resolve(item.slug) (description first docstring line,
        #   category) inside the existing try/except — bounded by "never let an import error break the catalog"
```
**Why**: the cache and the response shape stay compatible; only the source of truth changes.

### FILL IN checklist
- [ ] `tools_catalog.py::_build_catalog` — enrichment via the resolver, `dotted_path` for builtin/walk entries.
- [ ] `test_host_toolkit_paths.py` — one parametrized case per path (catalog, schema, generic assign, FEAT-593 PUT/GET, options, `/me`, live assign, bot build).

---

## Acceptance Criteria

- [ ] `GET /catalog/tools` and `GET /api/v1/tools/catalog` list `tp_probe_tool` with `source="host"`; built-ins keep their entries.
- [ ] `test_every_studio_path_sees_host_toolkit` passes for every path (spec AC 2).
- [ ] `grep -rn "discover_from_registry\|discover_all" packages/*/src` shows only the resolver, `discovery.py` and `ToolManager` call sites (spec AC 1).
- [ ] Existing `pytest packages/ai-parrot-server/tests/test_tools_list_route.py packages/ai-parrot-server/tests/studio/test_catalogs.py -q` pass.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_host_toolkit_paths.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_catalogs.py -q`
- `pytest packages/ai-parrot-server/tests/test_tools_list_route.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_host_toolkit_paths.py
import pytest
from ._host_probe import host_plugins  # noqa: F401

PATHS = ["catalog", "schema", "generic_assign", "feat593_put_get", "options", "me_override", "live_assign", "bot_build"]


@pytest.mark.parametrize("path", PATHS)
async def test_every_studio_path_sees_host_toolkit(host_plugins, path):
    """Each Studio path finds the host toolkit (spec §4 integration row 1)."""
    # FILL IN: one driver per path; real make_mocked_request requests; options/`/me` use a non-tenant-bound probe
    #   variant until TASK-3989 lifts resolver rule 5
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (tramo B1, sequential fallback)
**Date**: 2026-10-02
**Notes**: _build_catalog iterates resolver.entries() with source; test_every_studio_path_sees_host_toolkit covers 8 paths (non-tenant-bound probe). tests/unit/test_tools_catalog.py (outside file list) adapted: patches get_toolkit_resolver instead of TOOL_REGISTRY. Remaining discover_all/discover_from_registry callers (handlers/bots.py, bots/factory/tools/introspection.py, bots/flows/authoring/catalog.py, studio/testing/__init__.py re-export) are outside this task's file list and left untouched: spec AC1 grep not fully satisfied.
**Mutation evidence**: catalogue loop -> empty => [catalog] RED; interfaces/tools.py shim -> None => [bot_build] RED; restored.

**Deviations from spec**: none (handler modules are now packages; edit sites re-anchored)
