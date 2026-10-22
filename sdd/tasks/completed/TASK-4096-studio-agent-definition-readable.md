# TASK-4096: Readable Studio agent definition (B1)

**Feature**: FEAT-634 — Agent Studio — UI Backend Gaps
**Spec**: `sdd/specs/agentstudio-ui-backend-gaps.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 1 / G1 (B1) / AC1-AC4. The UI General tab needs `llm`, `description`, `category` flat on every Studio item and a manager-only `definition` object on detail/PATCH/visibility responses.

---

## Scope

- Add flat `llm`, `description`, `category` (from `rec.definition`) to `_studio_item`.
- Add `_studio_definition(rec)` returning `{bot_class, llm, description, category, model_params (model_dump), system_prompt, tools}` — never `config`/`schema_version`.
- Give `_studio_item_for` a keyword `detail: bool = False`; with `detail=True` AND `can_manage` in the visibility fields, add `item['definition']`. Non-manager viewers never get `definition` (Resolved 2026-10-05, Juan: viewers do NOT read `system_prompt`).
- Pass `detail=True` at the three call sites: `GET /agents/{name}` (`agents/_db.py:35`), `PATCH` (`agents/_db.py:213`), visibility PATCH (`agents/_visibility.py:55`); the list (`_db.py:39`) does NOT.
- Write `tests/studio/test_agent_definition_readable.py` (AC1-AC4).

**NOT in scope**: `tools` editing (B3), `config` exposure, changes to legacy (GLOBAL) items, docs (TASK-4101).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/agents/_mixin.py` | MODIFY | flat keys, `_studio_definition`, `detail` kwarg |
| `packages/ai-parrot-server/src/parrot/handlers/studio/agents/_db.py` | MODIFY | `detail=True` on GET detail and PATCH |
| `packages/ai-parrot-server/src/parrot/handlers/studio/agents/_visibility.py` | MODIFY | `detail=True` on visibility PATCH |
| `packages/ai-parrot-server/tests/studio/test_agent_definition_readable.py` | CREATE | real-app tests for AC1-AC4 |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `e840b4b44` (2026-10-05). Use these VERBATIM; verify anything else with grep first.

### Verified Imports
```python
from parrot.handlers.studio.storage.models import StudioAgentDefinition, StudioAgentRecord, StudioModelParams  # storage/models.py:91,258,81
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/agents/_mixin.py
    @staticmethod
    def _studio_item(rec: Any) -> dict:                                  # :173 (keys name..at_startup; rec.definition.bot_class used at :189)
    def _studio_item_for(self, access: Any, rec: Any) -> dict:           # :263 ; item.update(access.visibility_fields(_store_record("agent", rec.agent_id, rec)))
# packages/ai-parrot-server/src/parrot/handlers/studio/access.py:157  def visibility_fields(self, r) -> dict   (includes "can_manage" :161)
# packages/ai-parrot-server/src/parrot/handlers/studio/agents/_db.py:35  return self.json_response(self._studio_item_for(await self._access(), rec))
# packages/ai-parrot-server/src/parrot/handlers/studio/agents/_db.py:39  agents = [self._studio_item_for(access, r) for r in visible]      (list: leave unchanged)
# packages/ai-parrot-server/src/parrot/handlers/studio/agents/_db.py:213 return self.json_response(self._studio_item_for(await self._access(), updated))
# packages/ai-parrot-server/src/parrot/handlers/studio/agents/_visibility.py:55 return self.json_response(self._studio_item_for(access, updated))
# storage/models.py:91 StudioAgentDefinition fields: schema_version, bot_class, llm, model_params, system_prompt, description, category, tools, config
```

### Does NOT Exist
- ~~`StudioAgentPatch.tools` / `POST /agents/{name}/tools` on a tenant (B3, out of scope)~~
- ~~`config` or `schema_version` in any readable response (deliberately not exposed)~~
- ~~`expected_version` support on the visibility PATCH routes (last-write-wins, B7)~~
- ~~`TenantToolingPolicy.tenant_toolkits`~~ before TASK-4098 lands (added by this feature)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/agents/_mixin.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/agents/_db.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/agents/_visibility.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_agent_definition_readable.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents/_mixin.py#_studio_item",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents/_mixin.py#_studio_item_for"
  ]
}
```

---

## Implementation Notes

- Additive only: no existing field, route or error code is renamed or removed. Async-first, Pydantic v2, `self.logger`, Google docstrings, type hints, 120 cols.
- Tests use a REAL aiohttp app (`aiohttp_client`) with the real Studio routes and the session middleware of `tests/studio/test_agents_db_mode.py` (Postgres via `TEST_STUDIO_PG_DSN`, skipped when absent) or `tests/studio/_tenant_agent.py::StudioAgentWorld` (in-memory repositories). No `make_mocked_request`, no patching of Studio handlers or policy objects.
- Viewers of a tenant-shared agent do NOT read `system_prompt` (Resolved 2026-10-05, Juan).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature or path the blueprint fixes. Re-run each `grep -c` before editing; a count other than the one stated means the anchor moved — stop and report.

### Steps (in order)
1. Add the three flat keys to the dict `_studio_item` returns — because the list cards show the LLM for every viewer.
2. Add `_studio_definition` as a `@staticmethod` next to `_studio_item` — because three call paths share it.
3. Add the `detail` kwarg to `_studio_item_for` and gate `definition` on `item.get('can_manage')` — because only managers may read prompt/params/tools.
4. Edit the three call sites; leave the list call alone — because list payloads must carry no system prompts.

### `packages/ai-parrot-server/src/parrot/handlers/studio/agents/_mixin.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def _studio_item(rec: Any) -> dict:' packages/ai-parrot-server/src/parrot/handlers/studio/agents/_mixin.py)
# EDIT inside the returned dict of `_studio_item` (verified: _mixin.py:173-194), before the closing brace add:
            "llm": rec.definition.llm,
            "description": rec.definition.description,
            "category": rec.definition.category,

# AFTER — insert below the end of `_studio_item` (before `async def _studio_authorize`, verified: _mixin.py:196):
    @staticmethod
    def _studio_definition(rec: Any) -> dict:
        """The readable definition of a Studio agent (managers only); excludes ``config`` and ``schema_version``."""
        d = rec.definition
        return {
            "bot_class": d.bot_class,
            "llm": d.llm,
            "description": d.description,
            "category": d.category,
            "model_params": d.model_params.model_dump(),
            "system_prompt": d.system_prompt,
            "tools": list(d.tools),
        }

# occurrences: 1 (verified: grep -c '    def _studio_item_for(self, access: Any, rec: Any) -> dict:' _mixin.py)
# REPLACE `_studio_item_for` (verified: _mixin.py:263-267) with:
    def _studio_item_for(self, access: Any, rec: Any, *, detail: bool = False) -> dict:
        """The Studio item with the visibility fields the caller's access decision yields (C14).

        With ``detail=True`` and ``can_manage``, the item also carries ``definition`` (B1).
        """
        item = self._studio_item(rec)
        item.update(access.visibility_fields(_store_record("agent", rec.agent_id, rec)))
        # FILL IN: attach item["definition"] = self._studio_definition(rec) when detail and item.get("can_manage") — bounded by AC2 (viewers get none)
        return item
```
**Why**: the flat keys are non-sensitive; `definition` is gated by the same `can_manage` the visibility fields already compute, so there is no second authorization path. Do not rename any existing key.


### `packages/ai-parrot-server/src/parrot/handlers/studio/agents/_db.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'return self.json_response(self._studio_item_for(await self._access(), rec))' packages/ai-parrot-server/src/parrot/handlers/studio/agents/_db.py)
# REPLACE at _db.py:35:
            return self.json_response(self._studio_item_for(await self._access(), rec, detail=True))
# occurrences: 1 (verified: grep -c 'self._studio_item_for(await self._access(), updated)' _db.py)
# REPLACE at _db.py:213:
        return self.json_response(self._studio_item_for(await self._access(), updated, detail=True))
```
**Why**: detail and PATCH are the two responses the General tab pre-fills from. The list at `:39` stays without `detail`.

### `packages/ai-parrot-server/src/parrot/handlers/studio/agents/_visibility.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'return self.json_response(self._studio_item_for(access, updated))' packages/ai-parrot-server/src/parrot/handlers/studio/agents/_visibility.py)
# REPLACE at _visibility.py:55:
        return self.json_response(self._studio_item_for(access, updated, detail=True))
```
**Why**: AC3 — the visibility PATCH returns the item with `definition` for managers.

### `packages/ai-parrot-server/tests/studio/test_agent_definition_readable.py` (CREATE)
```python
"""B1 — readable Studio agent definition (FEAT-634 AC1-AC4). Real aiohttp app, no mocks."""
from __future__ import annotations

import pytest

# FILL IN: import the session-middleware/app builders used by test_agents_db_mode.py:1-70 and StudioAgentWorld from ._tenant_agent — bounded by spec §4 (real app only)


class TestDefinitionReadable:
    async def test_owner_gets_definition(self, aiohttp_client):
        # FILL IN: POST /agents with llm, description, category, config.system_prompt, config.temperature; GET as owner; assert exact `definition` — bounded by AC1
        ...

    async def test_viewer_gets_flat_keys_without_definition(self, aiohttp_client):
        # FILL IN: tenant viewer without manage — flat llm/description/category, no `definition` key — bounded by AC2
        ...

    async def test_list_has_flat_keys_never_definition(self, aiohttp_client):
        # FILL IN: GET /agents items — flat keys present, no `definition` — bounded by AC3
        ...

    async def test_patch_and_visibility_return_definition_and_version(self, aiohttp_client):
        # FILL IN: PATCH and visibility PATCH as manager — `definition` updated, `version` bumped — bounded by AC3
        ...

    async def test_no_config_or_schema_version_and_no_key_lost(self, aiohttp_client):
        # FILL IN: no `config`/`schema_version` key; every pre-existing item key still present — bounded by AC4
        ...
```
**Why**: the file is the executable form of AC1-AC4; the `...` bodies are `FILL IN` stubs, replace every one with real assertions.

### FILL IN checklist
- [ ] `_mixin.py::_studio_item_for` — attach `definition` when `detail and item.get('can_manage')`; AC2
- [ ] `test_agent_definition_readable.py` — every test body; AC1-AC4

---

## Acceptance Criteria

- [ ] AC1-AC4 of the spec hold (manager `definition`, viewer flat keys only, list never `definition`, additive only)
- [ ] Validation Commands pass
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_agent_definition_readable.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_agent_definition_readable.py
class TestDefinitionReadable:
    async def test_owner_gets_definition(self, aiohttp_client): ...
    async def test_viewer_gets_flat_keys_without_definition(self, aiohttp_client): ...
```
Tests use a REAL aiohttp app (`aiohttp_client`) with the real Studio routes and the session middleware of `tests/studio/test_agents_db_mode.py` (Postgres via `TEST_STUDIO_PG_DSN`, skipped when absent) or `tests/studio/_tenant_agent.py::StudioAgentWorld` (in-memory repositories). No `make_mocked_request`, no patching of Studio handlers or policy objects.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agentstudio-ui-backend-gaps --feature-id FEAT-634`), never on `dev`.
2. Read the spec `sdd/specs/agentstudio-ui-backend-gaps.spec.md`; check every `Depends-on` task is `done` in `sdd/tasks/index/agentstudio-ui-backend-gaps.json`.
3. Verify the Codebase Contract before writing code; update it first if stale.
4. Mark `in-progress` in the index (set `started_at`), commit only that file.
5. Implement from the Blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
6. Commit only the files this task lists; close with `scripts/sdd/close_task.sh TASK-4096 agentstudio-ui-backend-gaps verified`; fill the Completion Note; commit SDD state.

---

## Completion Note

Implemented per blueprint: flat llm/description/category in _studio_item; _studio_definition; detail kwarg gated on can_manage; detail=True at GET/PATCH/visibility PATCH. 5 real-app tests (Postgres) pass. Seat: native (sdd-worker fallback, no coder MCP).
