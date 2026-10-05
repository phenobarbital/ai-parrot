# TASK-4097: Catalogues: models per provider and base-class allowance (B2, B13)

**Feature**: FEAT-634 — Agent Studio — UI Backend Gaps
**Spec**: `sdd/specs/agentstudio-ui-backend-gaps.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 2 / G2 (B2) / G9 (B13) / AC5, AC15. The model picker lists a provider's models; the base-class picker shows what the caller's partition may use.

---

## Scope

- Add `_provider_models(provider) -> tuple[list[str], list[str]]` = `(active, deprecated)` from `LLMFactory.list_models`; `([], [])` on any failure.
- Add `models` and `deprecated_models` to every available `llm-clients` row inside `_build_llm_clients_catalog` (cache policy unchanged).
- Add instance method `_base_classes_for_caller` returning a per-request COPY of the cached `base-classes` rows with `allowed` (`StudioClassAllowlist.from_app(app).allows(part, name)`), plus host-extra rows `{name, available: True, allowed: True, host: True, module: None, docstring: None, params: {}, lazy: False}` for names in `StudioClassAllowlist.names()` not exported by `parrot.bots.__all__`; route the `base-classes` branch of `get` through it. Never write `allowed` back into `_BASE_CLASSES_CACHE`.
- Extend `tests/studio/test_catalogs.py` (AC5, AC15).

**NOT in scope**: tools-catalogue filtering (TASK-4098/4099), narrowing the tenant allow-list, docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py` | MODIFY | `_provider_models`, `models` rows, per-caller base-classes |
| `packages/ai-parrot-server/tests/studio/test_catalogs.py` | MODIFY | extend: models, allowed, host extras |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `e840b4b44` (2026-10-05). Use these VERBATIM; verify anything else with grep first.

### Verified Imports
```python
from parrot.clients.factory import LLMFactory  # already imported in catalog.py; list_models at clients/factory.py:224
from parrot.handlers.studio.storage.services._common import StudioClassAllowlist  # _common.py:101
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py
def _build_llm_clients_catalog() -> list[dict]:   # :136  row: provider,class_name,lazy,available,default_model (:166-173)
    async def get(self):                          # base-classes branch: `return self.json_response(await self._get_base_classes())` (:206)
    @staticmethod
    async def _get_base_classes() -> list[dict]:  # :216 (cached in _BASE_CLASSES_CACHE)
# packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/_common.py:101 class StudioClassAllowlist: from_app(app) :108, names() :112, allows(part, bot_class) :118
# `self._studio_partition()` returns the caller's StudioPartition (used in _tools_for_caller, catalog.py:~229); raises StudioTenantRequired -> `self._tenant_required()`
# LLMFactory.list_models(provider) -> dict with keys "active" / "deprecated"; reads `client_class.models` (an Enum type)
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
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_catalogs.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py#_build_llm_clients_catalog",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/_common.py#StudioClassAllowlist"
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
1. Add `_provider_models` above `_build_llm_clients_catalog` — because it must never raise into the catalogue.
2. Add the two keys to the available-row dict — because AC5 needs `models` on every available row.
3. Add `_base_classes_for_caller` and call it from `get` — because `allowed` is per caller and the cache must stay shared.

### `packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py` (MODIFY)
```python
# AFTER — insert above `def _build_llm_clients_catalog() -> list[dict]:` (verified: catalog.py:136, occurrences: 1)
def _provider_models(provider: str) -> tuple[list[str], list[str]]:
    """``(active, deprecated)`` model ids of ``provider`` via ``LLMFactory.list_models``; ``([], [])`` on any failure."""
    # FILL IN: call LLMFactory.list_models(provider), read "active"/"deprecated", coerce to list[str]; broad except -> ([], []) — bounded by AC5 (request still succeeds)

# EDIT the available row (verified: catalog.py:166-173) — after the "default_model" key add:
                "models": _provider_models(provider)[0],
                "deprecated_models": _provider_models(provider)[1],
# FILL IN: call _provider_models once and unpack — bounded by AC5

# occurrences: 1 (verified: grep -c '            return self.json_response(await self._get_base_classes())' catalog.py)
# REPLACE at catalog.py:206:
            return self.json_response(await self._base_classes_for_caller())

# AFTER — insert below `_get_base_classes` (verified: catalog.py:216-220):
    async def _base_classes_for_caller(self) -> list[dict]:
        """Cached rows copied with ``allowed`` for the caller's partition, plus host-extra rows (B13)."""
        # FILL IN: part = await self._studio_partition() (StudioTenantRequired -> self._tenant_required()); allow = StudioClassAllowlist.from_app(self.request.app); copy each cached row with allowed=allow.allows(part, row["name"]); append host rows for allow.names() - exported names — bounded by AC15; never mutate _BASE_CLASSES_CACHE
        raise NotImplementedError
```
**Why**: B2 is data-only on a process-cached row; B13 must be a per-request copy because the allowance depends on the caller. `_get_base_classes` stays as is (staticmethod, cached).

### `packages/ai-parrot-server/tests/studio/test_catalogs.py` (MODIFY)
```python
# AFTER — append at end of file
async def test_llm_clients_rows_carry_models(aiohttp_client):
    # FILL IN: GET /catalog/llm-clients; each available row has list[str] `models` == LLMFactory.list_models(p)["active"] and `deprecated_models`; a provider without an enum -> [] — bounded by AC5
    ...

async def test_base_classes_rows_carry_allowed_and_host_extras(aiohttp_client):
    # FILL IN: tenant caller with app["studio_class_allowlist"]={"HostBot"}; rows have `allowed`; HostBot row has host True/allowed True — bounded by AC15
    ...
```
**Why**: reuse the existing app fixture of this file; real app, no patching.

### FILL IN checklist
- [ ] `catalog.py::_provider_models` — safe extraction; AC5
- [ ] `catalog.py::_base_classes_for_caller` — copy + host rows; AC15
- [ ] `test_catalogs.py` — both test bodies

---

## Acceptance Criteria

- [ ] AC5 and AC15 hold; `_BASE_CLASSES_CACHE` is never mutated; existing catalogue tests pass
- [ ] Validation Commands pass
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_catalogs.py -q`

---

## Test Specification

```python
async def test_llm_clients_rows_carry_models(aiohttp_client): ...
async def test_base_classes_rows_carry_allowed_and_host_extras(aiohttp_client): ...
```
Tests use a REAL aiohttp app (`aiohttp_client`) with the real Studio routes and the session middleware of `tests/studio/test_agents_db_mode.py` (Postgres via `TEST_STUDIO_PG_DSN`, skipped when absent) or `tests/studio/_tenant_agent.py::StudioAgentWorld` (in-memory repositories). No `make_mocked_request`, no patching of Studio handlers or policy objects.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agentstudio-ui-backend-gaps --feature-id FEAT-634`), never on `dev`.
2. Read the spec `sdd/specs/agentstudio-ui-backend-gaps.spec.md`; check every `Depends-on` task is `done` in `sdd/tasks/index/agentstudio-ui-backend-gaps.json`.
3. Verify the Codebase Contract before writing code; update it first if stale.
4. Mark `in-progress` in the index (set `started_at`), commit only that file.
5. Implement from the Blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
6. Commit only the files this task lists; close with `scripts/sdd/close_task.sh TASK-4097 agentstudio-ui-backend-gaps verified`; fill the Completion Note; commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*


## Completion Note

Implemented and merged by the orchestrator (chunk 0). Own tests pass (studio: test_agent_definition_readable + test_catalogs; tooling policy: 23 passed per coder). Merge-tier sweep red only on pre-existing environmental failures (Cython parrot.utils.types absent in worktree; studio test_byok stale vs byok.py; test_tools_catalog_shape plugins dotted_path) — none touch this feature. TASK-4097 review fix: test_llm_clients_rows_carry_models now tolerates providers whose list_models raises (commit d37ce5e27).
