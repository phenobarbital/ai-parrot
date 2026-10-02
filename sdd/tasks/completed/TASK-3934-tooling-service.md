# TASK-3934: StudioToolingService and the AgentToolingStore studio branch

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Agent/asset/tooling services (M5, part 2: StudioToolingService + tooling_store extraction)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3927, TASK-3933
**Assigned-to**: unassigned

---

## Context

Spec §2.5 (`StudioToolingService`: load / put_toolkit / delete_toolkit / put_mcp_servers with guard), §2.5a (vault
writes after the lock, before the DB write), §2.5b (gate on every tooling write), §2.5c (vault names from
`record.tooling_ref`), §2.8 row `tooling_store.py`, §3 M5, X3. FEAT-593's validation, masking and secret split are
reused, not rewritten.

---

## Scope

- `tooling_store.py`: extract the validation/masking/secret-split bodies into module-level functions reusable by the
  service (`validate_toolkit_params`, `reject_server_managed`, `split_toolkit_secrets`, `split_mcp_secrets`), keeping
  the `AgentToolingStore` methods as thin callers (behaviour unchanged).
- `ToolingState.source` gains `"studio"`; `AgentToolingStore.load(name)` first branch: a Studio row in the request's
  partition → `ToolingState(source="studio", tooling_ref=record.tooling_ref, owner=record.owner, editable=True)`;
  `_persist` on the studio source delegates to `StudioToolingService`.
- `services/tooling.py` `StudioToolingService`: `load`, `put_toolkit`, `delete_toolkit`, `put_mcp_servers`
  (guard=). Each: `studio_transaction` → `agents.lock(guard)` → build final normalised tooling → gate
  (`phase="write"`) → vault writes under `record.tooling_ref` → `tooling.replace` → commit; return post-commit version.

**NOT in scope**: Handler `expected_version` parsing and error mapping (TASK-3946); per-user overrides (TASK-3927/25).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | extract reusable functions; studio source branch; _persist delegation |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/tooling.py` | CREATE | StudioToolingService |
| `packages/ai-parrot-server/tests/studio/storage/test_tooling_service.py` | CREATE | real-PG + fake service tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.tooling_store import AgentToolingStore, ToolingState   # tooling_store.py:47,78
from parrot.security.vault_utils import store_vault_credential, delete_vault_credential   # tooling_store.py:16-20
from parrot.tools.spec import (toolkit_vault_name, mcp_vault_name, SECRET_MASK, MCP_SECRET_FIELDS,
                               normalize_tooling, NormalizedTooling)               # tooling_store.py:23-33
from parrot.tools.config_schema import secret_paths                                # config_schema.py:162
from parrot.handlers.studio.storage.services._common import StudioToolingGate, normalized_tooling_for  # TASK-3933
from parrot.handlers.studio.storage.repositories import StudioRepositories, studio_transaction        # TASK-3925/09
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py (line numbers before TASK-3927 shifted them by a few lines)
class AgentToolingStore:
    async def load(self, name: str) -> ToolingState                                   # :84
    def schema_for(self, slug: str) -> tuple[type, dict[str, Any]]                     # :138
    @staticmethod
    def _validate(cls: type, schema: dict[str, Any], params: dict[str, Any]) -> None   # :147
    @staticmethod
    def _reject_server_managed(schema: dict[str, Any], params: dict[str, Any]) -> None # :167
    async def put_toolkit(self, name, slug, params, user_overridable) -> ToolkitSpec   # :177
    async def delete_toolkit(self, name: str, slug: str) -> None                       # :193
    async def put_mcp_servers(self, name, servers) -> list[AgentMCPServerSpec]         # :204
    async def _split_secrets(...)                                                      # :250
    async def _persist(self, name: str, state: ToolingState) -> None                   # :292 (occurrences: 1)
```

### Does NOT Exist
- ~~`parrot.tools.tooling_policy`~~ (`TenantToolingPolicy`, `enforce_tenant_tooling`, `ToolingSubject`,
  `TenantToolingRefused`, `get_tenant_tooling_policy`) — **not on `dev` @ 32b1a45d4**; provided by TOOLKITS Wave 1
  (M7 core). Verify the merged signatures before coding: `enforce_tenant_tooling(app, tooling, *, subject)`,
  `ToolingSubject(tenant, agent_id, actor, phase)`, refusal code `tooling_not_permitted`.
- ~~`ToolingState.source == "studio"`~~, ~~`StudioToolingService`~~ — created here.
- ~~Secret values in `ai_agent_tooling.config`~~ — never; only `secret_refs` hold ref-derived vault names.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/tooling.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_tooling_service.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#ToolingState"
  ]
}
```

---

## Implementation Notes

- Parallelism: modifies studio/tooling_store.py after TASK-3927 (ToolingState.tooling_ref); uses StudioToolingGate/normalized_tooling_for from TASK-3933 (services/_common.py) and the tooling repository from TASK-3929 (transitive)
- Cross-feature ordering: X16 "Cross-spec waits" — STORAGE W2 services need TOOLKITS Wave 1 (M7 core: `parrot/tools/tooling_policy.py` with `enforce_tenant_tooling`, `ToolingSubject`, `TenantToolingRefused`, `get_tenant_tooling_policy`) merged first. Do not start before it is on `dev`.
- Cross-feature ordering (per-file rule, X16): every FEAT-605 or TOOLKITS task editing `studio/tooling_store.py`
  merges **after** this task and rebases on it (TOOLKITS M9 edits it only after STORAGE W3).
- The extraction must be a pure move (diff reviewable as such); no behaviour change for `database`/`registry` sources.
- How `load(name)` learns the partition: `await self._handler._studio_partition()` (the handler passed to
  `AgentToolingStore.__init__`, `tooling_store.py:81`) and `self._handler._studio_storage()` — only when the backend
  is `database`.
- `vault_owner` = row owner; client- or bundle-supplied `secret_refs`/`vault_owner` are refused (X18).

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
1. Move the bodies of `_validate`, `_reject_server_managed`, `_split_secrets` (and the MCP secret split inside
   `put_mcp_servers`) into module-level functions; methods call them — *why*: one implementation for both stores.
2. Add the studio branch to `load` and `_persist`. 3. Write `services/tooling.py`. 4. Tests.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/tooling.py` (CREATE)
```python
"""StudioToolingService (spec §2.5): FEAT-593 validation + secret split, persisted to ai_agent_tooling."""
from __future__ import annotations

import logging

logger = logging.getLogger("Parrot.AgentStudio.Storage")


class StudioToolingService:
    def __init__(self, repos: StudioRepositories, *, gate: StudioToolingGate, store_factory=AgentToolingStore) -> None:
        self._repos = repos
        self._gate = gate

    async def put_toolkit(self, part: StudioPartition, name: str, slug: str, params: dict, user_overridable: list[str],
                          *, actor: str | None, guard: StudioWriteGuard) -> int:
        """Lock → final tooling → gate(write) → vault (ref-derived names) → replace → commit. Returns version."""
        async with studio_transaction(self._repos.pool) as conn:
            head = await self._repos.agents.lock(conn, part, name, guard)
            # FILL IN: current rows = list_locked; validate via extracted functions; split secrets with
            #   toolkit_vault_name(slug, f"studio-agent:{head.agent_id}"); gate.enforce(... phase="write") BEFORE any
            #   vault write; replace(); read back version — bounded by test_tooling_policy_on_tooling_writes.
            raise NotImplementedError
    # FILL IN: load, delete_toolkit, put_mcp_servers with the same skeleton.
```
**Why this shape**: the gate runs after the lock and before any vault or row write (§2.5b), so a refusal writes nothing.

### `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _persist(self, name: str, state: ToolingState) -> None:' tooling_store.py)
# FILL IN: first statement of _persist: `if state.source == "studio": return await <service>.replace_from_state(...)`
#   — bounded by §2.8 row tooling_store.py; Literal widened to ["database", "registry", "studio"].
```

### `packages/ai-parrot-server/tests/studio/storage/test_tooling_service.py` (CREATE)
```python
"""FEAT-621 M5 — tooling service (AC12, AC13)."""
# FILL IN: test_toolkit_secrets_never_in_db (config has no secret value; secret_refs holds
#   toolkit_<slug>_studio-agent:<uuid>); test_tooling_policy_on_tooling_writes (tenant: PUT mcp transport stdio;
#   http + params {transport: stdio, command: /bin/sh} → StudioToolingRefused, no row, no vault write, no subprocess
#   — use the no_subprocess fixture; mutation: check only top-level transport ⇒ RED); test_stale_expected_version
#   (StudioVersionConflict, vault untouched); test_legacy_sources_unchanged (database/registry paths still pass
#   tests/studio/test_tooling_store.py).
```

### FILL IN checklist
- [ ] extraction (pure move); studio branch; `_persist` delegation.
- [ ] four service methods; four tests.

---

## Acceptance Criteria

- [ ] Toolkit secrets never reach `ai_agent_tooling.config`; `secret_refs` carry `studio-agent:<agent_id>`-derived names (`test_toolkit_secrets_never_in_db`, AC12).
- [ ] Tenant stdio/command MCP config (incl. inside `params`) refused before any row or vault write, no process started (AC13, tooling-write half).
- [ ] Stale `expected_version` → `StudioVersionConflict`, nothing written (AC8).
- [ ] Existing `tests/studio/test_tooling_store.py` passes unmodified (legacy sources unchanged).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_tooling_service.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_store.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_toolkit_secrets_never_in_db` | AC12, X3 |
| `test_tooling_policy_on_tooling_writes` | AC13 (`test_tooling_policy_on_write_and_build`, tooling-route half) |
| `test_stale_expected_version` | AC8 |
| `test_legacy_sources_unchanged` | regression |

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
   `feat(agentstudio-db-storage): TASK-3934 — StudioToolingService and the AgentToolingStore studio branch`.
8. Close with `scripts/sdd/close_task.sh TASK-3934 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sonnet)
**Date**: 2026-10-01
**Notes**: tooling_store.py: pure extraction of validate_toolkit_params/reject_server_managed/toolkit_schema_for and PURE split_toolkit_secrets/split_mcp_secrets (return spec + VaultWrite list) with flush_vault_writes, so the service can gate BEFORE any vault write; AgentToolingStore methods are thin callers; studio source in load/_persist (authorized_version guard). services/tooling.py: load/put_toolkit/delete_toolkit/put_mcp_servers/replace_from_state (lock→final tooling→gate(write)→vault→replace→commit, returns in-txn version). vault_owner is persisted only when a spec has secret_refs, because TenantToolingPolicy refuses vault_owner/secret_refs in the write phase. 8 real-PG tests; existing tests/studio suite has no new failures vs baseline. Mutations RED: gate removed, gate after vault write, guard dropped, vault_owner-only-with-refs. Tenant secrets are refused by the policy in write phase (policy-owned behaviour, not tested further). Fixed my TASK-3933 factory call to StudioToolingService(gate=).

**Deviations from spec**: put_toolkit etc. return int version (blueprint); added replace_from_state() for the _persist bridge; _common.py touched only to fix the factory kwarg
