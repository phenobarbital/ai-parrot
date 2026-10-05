# TASK-4099: Toolkit allow-list through Studio routes + refusal details (B4, B5)

**Feature**: FEAT-634 — Agent Studio — UI Backend Gaps
**Spec**: `sdd/specs/agentstudio-ui-backend-gaps.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4098
**Assigned-to**: unassigned

---

## Context

Implements spec Module 4 (B5 half) and the route half of G3 / AC6, AC7, AC8, AC11. The catalogue and every write path already run `check_tool`; this task adds `details` to the 422 body and proves the end-to-end behaviour.

---

## Scope

- `_json_error(message, code, details=None)`: include `details` in the `StudioError` when given.
- `_studio_error`: for `StudioToolingRefused` add `details={'reason': exc.reason, 'item': exc.item}` when present (`_common.py:147-152` already stamps them on the exception). Existing mappings and bodies without details stay byte-identical.
- Create `tests/studio/test_toolkit_allowlist_routes.py` covering AC6, AC7 (PUT toolkit, POST /agents, PATCH, draft save/activation, execute -> 403), AC8 (agent with a since-disabled toolkit still builds), AC11 (`details` on create/draft/activation). Register the real policy with `set_tenant_tooling_policy`.

**NOT in scope**: the policy seam itself (TASK-4098), `test_shapes_db_mode.py` (TASK-4100), docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/_base/__init__.py` | MODIFY | `_json_error` optional `details` |
| `packages/ai-parrot-server/src/parrot/handlers/studio/_base/_storage.py` | MODIFY | `details` on the tooling_not_permitted mapping |
| `packages/ai-parrot-server/tests/studio/test_toolkit_allowlist_routes.py` | CREATE | real-app allow-list route tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `e840b4b44` (2026-10-05). Use these VERBATIM; verify anything else with grep first.

### Verified Imports
```python
from parrot.tools.tooling_policy import TenantToolingPolicy, set_tenant_tooling_policy  # tooling_policy.py:102,241
from parrot.handlers.studio.models import StudioError  # models.py:23 (message, code, details)
from parrot.handlers.studio.storage.models import StudioToolingRefused  # storage/models.py:81
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/_base/__init__.py:111
    @staticmethod
    def _json_error(message: str, code: str) -> dict:   # body: StudioError(message=message, code=code).model_dump()
# packages/ai-parrot-server/src/parrot/handlers/studio/_base/_storage.py:154 def _studio_error(self, exc) -> web.Response ; table row :165 (m.StudioToolingRefused, 422, "tooling_not_permitted"); loop :174-178 builds self._json_error(message, code)
# packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/_common.py:129 StudioToolingGate.enforce (stamps code/reason/item on the exception :147-152)
# tests: packages/ai-parrot-server/tests/studio/_tenant_agent.py::StudioAgentWorld ; packages/ai-parrot-server/tests/studio/test_host_toolkit_paths.py (host-toolkit registration helper for fs_* fixtures)
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
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/_base/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/_base/_storage.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_toolkit_allowlist_routes.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base/__init__.py#_json_error",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base/_storage.py#_studio_error"
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
1. Add the optional `details` argument to `_json_error` — because `StudioError` already has the field.
2. Add the `details` branch in `_studio_error` for `StudioToolingRefused` only — because other codes have no details.
3. Write the new test file against the real app and a real `TenantToolingPolicy`.

### `packages/ai-parrot-server/src/parrot/handlers/studio/_base/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def _json_error(message: str, code: str) -> dict:' _base/__init__.py)
# REPLACE `_json_error` (verified: _base/__init__.py:111-115) with:
    def _json_error(message: str, code: str, details: dict | None = None) -> dict:
        from ..models import StudioError  # lazy: models imports the manager

        return StudioError(message=message, code=code, details=details).model_dump()
# FILL IN: confirm StudioError.details defaults to None and how model_dump renders it so bodies WITHOUT details do not change shape — bounded by AC17 (additive only)
```
**Why**: keep the staticmethod signature backwards compatible; only the new kwarg is added.

### `packages/ai-parrot-server/src/parrot/handlers/studio/_base/_storage.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '(m.StudioToolingRefused, 422, "tooling_not_permitted"),' _base/_storage.py)
# In the loop (verified: _storage.py:174-178), when `isinstance(exc, m.StudioToolingRefused)` build the body with details:
                # FILL IN: details = {"reason": exc.reason, "item": exc.item} when both attributes are present; pass to self._json_error(message, code, details) — bounded by AC11 and the refusal-shape table (spec §2)
```
**Why**: `reason`/`item` are stamped on the exception by `StudioToolingGate.enforce`; the mapper just surfaces them.

### `packages/ai-parrot-server/tests/studio/test_toolkit_allowlist_routes.py` (CREATE)
```python
"""B4/B5 — host-toolkit allow-list through the Studio routes (FEAT-634 AC6-AC8, AC11). Real app, real policy."""
from __future__ import annotations

# FILL IN: imports from ._tenant_agent / .test_host_toolkit_paths helpers and session middleware — bounded by spec §4 Test Data

POLICY_FACTORY = lambda: None  # FILL IN: TenantToolingPolicy(tenant_toolkits=lambda t: {"fs_events"} if t == "t1" else None) registered via set_tenant_tooling_policy


class TestToolkitAllowlistRoutes:
    async def test_catalog_tools_filtered_for_t1(self, aiohttp_client): ...   # AC6 (+ unrestricted tenant unchanged)
    async def test_put_toolkit_disabled_is_422_with_details(self, aiohttp_client): ...   # AC7/AC11 details == {"reason":"toolkit_unavailable","item":"fs_stores"}
    async def test_create_and_patch_with_disabled_toolkit_422(self, aiohttp_client): ...   # AC7
    async def test_draft_save_and_activation_422_with_details(self, aiohttp_client): ...   # AC7/AC11
    async def test_execute_disabled_toolkit_is_403_same_shape(self, aiohttp_client): ...   # AC7
    async def test_existing_agent_with_disabled_toolkit_still_builds(self, aiohttp_client): ...   # AC8
# FILL IN: replace the placeholder factory and every `...` with real requests/assertions — bounded by AC6, AC7, AC8, AC11
```
**Why**: the file is the executable form of the spec's route-level acceptance criteria.

### FILL IN checklist
- [ ] `_json_error` — details rendering; AC17
- [ ] `_studio_error` — details for StudioToolingRefused; AC11
- [ ] `test_toolkit_allowlist_routes.py` — fixtures and six bodies

---

## Acceptance Criteria

- [ ] AC6, AC7, AC8, AC11 hold; refusal shape = 422 `tooling_not_permitted` with `details {reason:'toolkit_unavailable', item}` (403 on execute)
- [ ] Responses without details are unchanged
- [ ] Validation Commands pass
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_allowlist_routes.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tenant_tooling_writes.py -q`

---

## Test Specification

```python
class TestToolkitAllowlistRoutes:
    async def test_put_toolkit_disabled_is_422_with_details(self, aiohttp_client): ...
```
Tests use a REAL aiohttp app (`aiohttp_client`) with the real Studio routes and the session middleware of `tests/studio/test_agents_db_mode.py` (Postgres via `TEST_STUDIO_PG_DSN`, skipped when absent) or `tests/studio/_tenant_agent.py::StudioAgentWorld` (in-memory repositories). No `make_mocked_request`, no patching of Studio handlers or policy objects.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agentstudio-ui-backend-gaps --feature-id FEAT-634`), never on `dev`.
2. Read the spec `sdd/specs/agentstudio-ui-backend-gaps.spec.md`; check every `Depends-on` task is `done` in `sdd/tasks/index/agentstudio-ui-backend-gaps.json`.
3. Verify the Codebase Contract before writing code; update it first if stale.
4. Mark `in-progress` in the index (set `started_at`), commit only that file.
5. Implement from the Blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
6. Commit only the files this task lists; close with `scripts/sdd/close_task.sh TASK-4099 agentstudio-ui-backend-gaps verified`; fill the Completion Note; commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*


## Completion Note

Implemented by seat codex and merged by the orchestrator (chunk 1). Task tests pass (test_toolkit_allowlist_routes, test_shapes_db_mode, test_testing_db_mode: exit 0).
