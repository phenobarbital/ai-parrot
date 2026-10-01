# TASK-3936: StudioAssetService: put/delete/get/list with quota under the agent lock

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Agent/asset/tooling services (M5, part 4: StudioAssetService)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3931, TASK-3933
**Assigned-to**: unassigned

---

## Context

Spec §2.5 (`StudioAssetService`: quota = total_size + new − old under the agent lock, text-only 415, identity
filenames, kb `.md`/`.txt`, skills paths + `parse_skill_file`; every write re-checks the agent's tooling with the
policy), §2.5a (lock order), §2.9 files rows (`version` and `sha256` added to responses).

---

## Scope

- `services/assets.py` `StudioAssetService(repos, *, limits, tooling_gate)`: `put(part, agent_name, asset, *, actor,
  guard) -> (StudioAssetRecord, version)`, `delete(part, agent_name, kind, name, *, actor, guard) -> (bool, version)`,
  `get`, `list`.
- Under one transaction: lock agent → gate on current tooling (`phase="write"`) → validate → quota check
  (`total_size(conn, agent_id) + new − old > agent_total_max` ⇒ `StudioAssetTooLarge(code="agent_assets_quota")`) →
  `put` with sha256 → commit.

**NOT in scope**: HTTP shape (TASK-3945); catalogue import (TASK-3938 calls this service).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/assets.py` | CREATE | StudioAssetService |
| `packages/ai-parrot-server/tests/studio/storage/test_asset_service.py` | CREATE | fake + real-PG tests incl. concurrent quota |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.services._common import (StudioLimits, StudioToolingGate,
    validate_asset_input, normalized_tooling_for)                               # TASK-3933
from parrot.handlers.studio.storage.repositories import StudioRepositories, studio_transaction   # TASK-3925/09
import hashlib                                                                  # sha256 of content.encode("utf-8")
```

### Does NOT Exist
- ~~`parrot.tools.tooling_policy`~~ (`TenantToolingPolicy`, `enforce_tenant_tooling`, `ToolingSubject`,
  `TenantToolingRefused`, `get_tenant_tooling_policy`) — **not on `dev` @ 32b1a45d4**; provided by TOOLKITS Wave 1
  (M7 core). Verify the merged signatures before coding: `enforce_tenant_tooling(app, tooling, *, subject)`,
  `ToolingSubject(tenant, agent_id, actor, phase)`, refusal code `tooling_not_permitted`.
- ~~`StudioAssetService`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/assets.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_asset_service.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: uses validate_asset_input/normalized_tooling_for/StudioToolingGate from TASK-3933 (services/_common.py) and InMemoryStudioRepositories from TASK-3931 for DB-free tests; creates services/assets.py only (runs alongside TASK-3934/14)
- Cross-feature ordering: X16 "Cross-spec waits" — STORAGE W2 services need TOOLKITS Wave 1 (M7 core: `parrot/tools/tooling_policy.py` with `enforce_tenant_tooling`, `ToolingSubject`, `TenantToolingRefused`, `get_tenant_tooling_policy`) merged first. Do not start before it is on `dev`.
- Quota check MUST happen after the lock (mutation in `test_concurrent_quota`: check before the lock ⇒ RED).
- An agent a tightened policy now refuses cannot be edited around it: the gate on the current tooling runs on every
  put/delete (§2.5b).

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
1. Service class (block below); 2. tests: fake for validation paths, PG for the concurrency test.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/assets.py` (CREATE)
```python
"""StudioAssetService (spec §2.5): text assets in Postgres with per-file caps and a per-agent quota."""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger("Parrot.AgentStudio.Storage")


class StudioAssetService:
    def __init__(self, repos: StudioRepositories, *, limits: StudioLimits, tooling_gate: StudioToolingGate) -> None:
        self._repos, self._limits, self._gate = repos, limits, tooling_gate

    async def put(self, part: StudioPartition, agent_name: str, asset: StudioAssetInput, *, actor: str | None,
                  guard: StudioWriteGuard) -> tuple[StudioAssetRecord, int]:
        validate_asset_input(self._limits, asset)          # cheap checks first; quota needs the lock
        digest = hashlib.sha256(asset.content.encode("utf-8")).hexdigest()
        async with studio_transaction(self._repos.pool) as conn:
            head = await self._repos.agents.lock(conn, part, agent_name, guard)
            # FILL IN: gate on current tooling (list_locked + definition); old size of (kind, name); quota under the
            #   lock; assets.put(...); read back version — bounded by test_concurrent_quota.
            raise NotImplementedError
    # FILL IN: delete, get, list.
```

### `packages/ai-parrot-server/tests/studio/storage/test_asset_service.py` (CREATE)
```python
"""FEAT-621 M5 — asset service (AC4, AC8, AC13)."""
# FILL IN: test_put_validates_kind_and_filename; test_skill_frontmatter_required; test_concurrent_quota (two
#   connections, each under the per-file cap, together over the agent quota → exactly one agent_assets_quota);
#   test_version_bumps_on_asset_write; test_asset_write_rechecks_tooling (raw-SQL stdio MCP row → refused);
#   test_stale_expected_version_assets; test_nothing_under_agents_dir (AGENTS_DIR snapshot unchanged).
```

### FILL IN checklist
- [ ] put/delete/get/list; seven tests.

---

## Acceptance Criteria

- [ ] Quota enforced under the agent row lock; two concurrent PUTs over quota → exactly one 413 `agent_assets_quota` (`test_concurrent_quota`, AC8).
- [ ] Each write bumps the agent `version`; stale `expected_version` refused (AC8).
- [ ] An asset write on an agent whose stored tooling the policy refuses is refused (AC13, asset half).
- [ ] Nothing is written under `AGENTS_DIR` (AC4).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_asset_service.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_put_validates_kind_and_filename` | §2.5 |
| `test_skill_frontmatter_required` | §2.5 |
| `test_concurrent_quota` | AC8 |
| `test_version_bumps_on_asset_write` | §2.6 |
| `test_asset_write_rechecks_tooling` | AC13 |
| `test_stale_expected_version_assets` | AC8 |
| `test_nothing_under_agents_dir` | AC4 |

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
   `feat(agentstudio-db-storage): TASK-3936 — StudioAssetService: put/delete/get/list with quota under the agent lock`.
8. Close with `scripts/sdd/close_task.sh TASK-3936 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
