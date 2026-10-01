# TASK-3935: StudioAgentService: create, create_from_bundle, patch, update_visibility, delete

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Agent/asset/tooling services (M5, part 3: StudioAgentService)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3931, TASK-3934
**Assigned-to**: unassigned

---

## Context

Spec §2.5 (`StudioAgentService` API), §2.5a (lock + guard; create relies on unique indexes), §2.5b (gate on create,
bundle create and patch — patch re-checks the current tooling), §2.5c (delete clean-up after commit: vault names in
the deleted rows' `secret_refs`, `ToolkitConfigService.purge_agent(ref)` and each `…_user` vault entry), §2.9a
(PATCH semantics), X6. Services validate data, never access.

---

## Scope

- `services/agents.py` `StudioAgentService(repos, *, limits, class_allowlist, tooling, tooling_gate)` with `create`
  (plain POST: no bundle), `create_from_bundle`, `patch` (lock → merge General fields → validate as create → gate on
  the current tooling → `update_definition`), `update_visibility` (FEAT-605 PATCH …/visibility), `delete`
  (guard; returns bool; best-effort clean-up after commit, logged, never failing), `get`, `get_version`, `list`.
- `_insert_with_children(conn, part, *, name, owner, definition, visibility, allowed_groups, toolkits, mcp_servers,
  assets) -> StudioAgentRecord` and `_replace_children(conn, agent_id, …)`: the in-transaction steps `create` uses,
  exposed for draft activation (TASK-3937) so that task never edits this module.
- One transaction for agent + tooling + assets on create; visibility domain and `tenant None ⇒ private`.

**NOT in scope**: HTTP mapping and the stale-authorisation retry (TASK-3944); deciding which visibility a caller may stamp (FEAT-605).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/agents.py` | CREATE | StudioAgentService |
| `packages/ai-parrot-server/tests/studio/storage/test_agent_service.py` | CREATE | fake-backed unit tests + real-PG integration tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.services._common import (StudioLimits, StudioClassAllowlist, StudioToolingGate,
    validate_definition_for, validate_asset_input, normalized_tooling_for)      # TASK-3933
from parrot.handlers.studio.storage.services.tooling import StudioToolingService  # TASK-3934
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories     # TASK-3931 (tests)
from parrot.handlers.toolkit_persistence import ToolkitConfigService             # purge_agent from TASK-3927
from parrot.security.vault_utils import delete_vault_credential                   # vault_utils.py:172
```

### Does NOT Exist
- ~~`parrot.tools.tooling_policy`~~ (`TenantToolingPolicy`, `enforce_tenant_tooling`, `ToolingSubject`,
  `TenantToolingRefused`, `get_tenant_tooling_policy`) — **not on `dev` @ 32b1a45d4**; provided by TOOLKITS Wave 1
  (M7 core). Verify the merged signatures before coding: `enforce_tenant_tooling(app, tooling, *, subject)`,
  `ToolingSubject(tenant, agent_id, actor, phase)`, refusal code `tooling_not_permitted`.
- ~~`StudioAgentService`~~ — created here. ~~A rename operation~~ — out of scope (§2.9a; name is immutable).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/agents.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_agent_service.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py#ToolkitConfigService"
  ]
}
```

---

## Implementation Notes

- Parallelism: constructor takes StudioToolingService from TASK-3934 (services/tooling.py) for bundle tooling validation; DB-free tests use InMemoryStudioRepositories from TASK-3931 (storage/testing.py); creates services/agents.py
- Cross-feature ordering: X16 "Cross-spec waits" — STORAGE W2 services need TOOLKITS Wave 1 (M7 core: `parrot/tools/tooling_policy.py` with `enforce_tenant_tooling`, `ToolingSubject`, `TenantToolingRefused`, `get_tenant_tooling_policy`) merged first. Do not start before it is on `dev`.
- FEAT-605 W2.1 consumes `create`, `patch`, `update_visibility`, `delete`, `get_version` exactly as X6 names them.
- `create(…, toolkits=(), mcp_servers=(), assets=())` must work with all three empty (`test_create_without_bundle`).
- Delete clean-up order (§2.5c): commit first; then for each deleted tooling row delete each vault name in
  `secret_refs` under `vault_owner`; then `purge_agent(ref)` and delete each returned override's `…_user` entries
  under its `user_id`. Exceptions logged at WARNING, swallowed.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### Steps (in order)
1. Constructor + read methods; 2. `create` / `create_from_bundle`; 3. `patch` / `update_visibility`; 4. `delete`
   with post-commit clean-up; 5. tests (fake first, PG second).

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/agents.py` (CREATE)
```python
"""StudioAgentService (spec §2.5). Validates data; never decides access."""
from __future__ import annotations

import logging

logger = logging.getLogger("Parrot.AgentStudio.Storage")


class StudioAgentService:
    def __init__(self, repos: StudioRepositories, *, limits: StudioLimits, class_allowlist: StudioClassAllowlist,
                 tooling: StudioToolingService, tooling_gate: StudioToolingGate) -> None:
        self._repos, self._limits, self._allow = repos, limits, class_allowlist
        self._tooling, self._gate = tooling, tooling_gate

    async def create(self, part: StudioPartition, *, name: str, owner: str, definition: StudioAgentDefinition,
                     visibility: str = "private", allowed_groups: Sequence[str] = (),
                     toolkits: Sequence[ToolkitSpec] = (), mcp_servers: Sequence[AgentMCPServerSpec] = (),
                     assets: Sequence[StudioAssetInput] = ()) -> StudioAgentRecord:
        # FILL IN: validate slug/definition/visibility; secret-free tooling; validate_asset_input each;
        #   gate.enforce(part, normalized_tooling_for(definition, …), agent_id=None, actor=owner, phase="write");
        #   ONE studio_transaction: agents.insert → tooling.replace → assets.replace_all — bounded by
        #   test_create_is_atomic.
        raise NotImplementedError
    # FILL IN: create_from_bundle, patch, update_visibility, delete, get, get_version, list (signatures §2.5).
```

### `packages/ai-parrot-server/tests/studio/storage/test_agent_service.py` (CREATE)
```python
"""FEAT-621 M5 — agent service (AC6, AC8, AC12, AC13)."""
# FILL IN: test_create_without_bundle; test_create_is_atomic (invalid asset → no agent, no tooling rows);
#   test_patch_merges_general_fields (model_params field-wise; version bumped); test_patch_stale_expected_version;
#   test_update_visibility_guarded; test_stale_authorization_signal (authorized_version moved →
#   StudioStaleAuthorization, nothing written); test_delete_cleans_vault_and_overrides_after_commit (boundary-patched
#   vault + ToolkitConfigService); test_create_tooling_policy_refusal (bundle with stdio MCP → StudioToolingRefused).
```

### FILL IN checklist
- [ ] eight methods; eight tests.

---

## Acceptance Criteria

- [ ] `create` works without a bundle and stores name/owner/definition/visibility/groups (`test_create_without_bundle`, AC8).
- [ ] Create is atomic (`test_create_is_atomic`, AC8).
- [ ] `patch`/`update_visibility`/`delete` apply the guard under the row lock; stale expected → `StudioVersionConflict`; stale authorized → `StudioStaleAuthorization` (AC8).
- [ ] Delete clean-up removes ref-derived vault entries and override documents after commit, best-effort (AC12).
- [ ] Gate runs on create/bundle/patch before any write (AC13).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_agent_service.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_create_without_bundle` | AC8 |
| `test_create_is_atomic` | AC8 |
| `test_patch_merges_general_fields` | §2.9a |
| `test_patch_stale_expected_version` | AC8 |
| `test_update_visibility_guarded` | X13 |
| `test_stale_authorization_signal` | §2.5a step 3 |
| `test_delete_cleans_vault_and_overrides_after_commit` | §2.5c |
| `test_create_tooling_policy_refusal` | AC13 |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3935 — StudioAgentService: create, create_from_bundle, patch, update_visibility, delete`.
8. Close with `scripts/sdd/close_task.sh TASK-3935 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sonnet)
**Date**: 2026-10-01
**Notes**: services/agents.py: create/create_from_bundle/patch/update_visibility/delete/get/get_version/list + _insert_with_children/_replace_children (+ public validate_new/validate_assets for TASK-3937). Gate runs before any write on create/bundle and on the current tooling at patch; guard applied under the row lock; post-commit best-effort clean-up (stored vault names under vault_owner, purge_agent, per-user …_user entries). 15 tests x {in-memory, real PG} = 30 pass. 13 mutations RED (gate on create/patch, guard on patch/visibility/delete, body expected_version, quota, duplicate assets, name check, secrets check, cleanup call/names/swallow). Renamed tooling.py _toolkit_row/_mcp_row to public toolkit_row/mcp_row so agents.py can reuse them.

**Deviations from spec**: patch/delete get optional actor kwarg (patch only) for the gate subject; body expected_version merged into the guard
