# TASK-3937: StudioDraftService: declarative drafts, Python gate, atomic activation

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Draft + catalogue services (M6, part 1: StudioDraftService)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3935
**Assigned-to**: unassigned

---

## Context

Spec §2.5 (`StudioDraftService`), §2.5a "Draft activation" (one transaction; lock draft → validate bundle → policy
`phase="activate"` → insert or `replace=true` atomic bundle replacement → mark activated → commit; vault clean-up of
removed slugs after commit), §2.8 "Python drafts gate", §3 Module 6 skeleton, decision 3.

---

## Scope

- `services/drafts.py` `StudioDraftService`: `python_drafts_allowed(part)` (tenant None AND `STUDIO_PYTHON_DRAFTS`,
  default true — the single decision point), `save_bundle(part, *, owner, bundle, visibility, allowed_groups, guard)`
  (create or update; bundle validation = Pydantic + allowlist + tooling schema + policy `phase="write"`), `get`,
  `list`, `delete(guard=)`, `update_visibility(guard=)`, `activate(part, name, *, owner, replace=False, guard,
  target_guard=None) -> StudioAgentRecord`.
- Activation status rule: draft must be `draft`/`validated`, else `StudioVersionConflict` (409 `version_conflict`).

**NOT in scope**: HTTP (TASK-3947); legacy Python drafts (unchanged, handler `_legacy_*`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/drafts.py` | CREATE | StudioDraftService |
| `packages/ai-parrot-server/tests/studio/storage/test_draft_service.py` | CREATE | fake + real-PG tests incl. concurrent activation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.services.agents import StudioAgentService     # TASK-3935
from parrot.handlers.studio.storage.models import StudioAgentBundle, StudioDraftRecord, StudioWriteGuard  # TASK-3922
from navconfig import config                                                       # STUDIO_PYTHON_DRAFTS
```

### Does NOT Exist
- ~~`parrot.tools.tooling_policy`~~ (`TenantToolingPolicy`, `enforce_tenant_tooling`, `ToolingSubject`,
  `TenantToolingRefused`, `get_tenant_tooling_policy`) — **not on `dev` @ 32b1a45d4**; provided by TOOLKITS Wave 1
  (M7 core). Verify the merged signatures before coding: `enforce_tenant_tooling(app, tooling, *, subject)`,
  `ToolingSubject(tenant, agent_id, actor, phase)`, refusal code `tooling_not_permitted`.
- ~~`STUDIO_PYTHON_DRAFTS`~~ config key — new (default `true`, Q10).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/drafts.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_draft_service.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: activation reuses StudioAgentService's create/validation path from TASK-3935 (services/agents.py); creates services/drafts.py
- Cross-feature ordering: X16 "Cross-spec waits" — STORAGE W2 services need TOOLKITS Wave 1 (M7 core: `parrot/tools/tooling_policy.py` with `enforce_tenant_tooling`, `ToolingSubject`, `TenantToolingRefused`, `get_tenant_tooling_policy`) merged first. Do not start before it is on `dev`.
- Lock order: draft row, then (replace=true) the target agent row (§2.5a deadlock rule).
- Activation reuses `StudioAgentService._insert_with_children(conn, …)` (replace=false) and `_replace_children`
  (replace=true) from TASK-3935 inside its own transaction; do not edit `services/agents.py` here.

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
1. `python_drafts_allowed`, `save_bundle`, reads; 2. `activate` (one transaction, §2.5a 1–5); 3. tests.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/drafts.py` (CREATE)
```python
"""StudioDraftService (spec §2.5, §2.5a): declarative drafts and atomic activation."""
from __future__ import annotations

import logging

logger = logging.getLogger("Parrot.AgentStudio.Storage")


class StudioDraftService:
    def __init__(self, repos: StudioRepositories, *, agents: StudioAgentService, tooling_gate: StudioToolingGate) -> None:
        self._repos, self._agents, self._gate = repos, agents, tooling_gate

    def python_drafts_allowed(self, part: StudioPartition) -> bool:
        """part.tenant is None and STUDIO_PYTHON_DRAFTS is true. Single decision point."""
        return part.tenant is None and config.getboolean("STUDIO_PYTHON_DRAFTS", fallback=True)

    async def activate(self, part: StudioPartition, name: str, *, owner: str, replace: bool = False,
                       guard: StudioWriteGuard, target_guard: StudioWriteGuard | None = None) -> StudioAgentRecord:
        """One transaction over draft + agent (§2.5a)."""
        # FILL IN: steps 1–5 of §2.5a "Draft activation"; replace=true → agents.lock(target_guard),
        #   update_definition, assets.replace_all, tooling.replace with exactly the bundle's rows; post-commit
        #   best-effort vault delete for removed slugs — bounded by test_activation_replace_is_atomic.
        raise NotImplementedError
    # FILL IN: save_bundle, get, list, delete, update_visibility.
```

### `packages/ai-parrot-server/tests/studio/storage/test_draft_service.py` (CREATE)
```python
"""FEAT-621 M6 — drafts (AC8, AC13, AC15)."""
# FILL IN: test_python_drafts_gate (tenant → False regardless; GLOBAL + setting false → False);
#   test_bundle_rejects_secret_fields (service half); test_save_bundle_policy_refusal;
#   test_concurrent_activation (two connections → one success, one StudioVersionConflict; one agent; children ==
#   bundle; draft activated once); test_activation_replace_is_atomic (asset over the DB cap mid-transaction →
#   target definition/assets/tooling and draft status unchanged); test_stale_draft_update.
```

### FILL IN checklist
- [ ] seven methods; six tests.

---

## Acceptance Criteria

- [ ] `python_drafts_allowed` is false on any tenant partition and when `STUDIO_PYTHON_DRAFTS` is false (`test_python_drafts_gate`, AC15).
- [ ] Activation is one transaction: concurrent activations → exactly one success and one `version_conflict`; `replace=true` failure leaves agent and draft unchanged (AC8).
- [ ] Bundle save and activation run the tooling policy (`phase=write`/`activate`) before any write (AC13).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_draft_service.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_python_drafts_gate` | AC15 |
| `test_bundle_rejects_secret_fields` | §2.4 (service half) |
| `test_save_bundle_policy_refusal` | AC13 |
| `test_concurrent_activation` | AC8 |
| `test_activation_replace_is_atomic` | AC8 |
| `test_stale_draft_update` | AC8 |

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
   `feat(agentstudio-db-storage): TASK-3937 — StudioDraftService: declarative drafts, Python gate, atomic activation`.
8. Close with `scripts/sdd/close_task.sh TASK-3937 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sonnet)
**Date**: 2026-10-01
**Notes**: services/drafts.py StudioDraftService: python_drafts_allowed (tenant None AND STUDIO_PYTHON_DRAFTS), save_bundle (validate_new phase=write; create or guarded update), get/list/delete/update_visibility, activate (one tx: lock draft -> status draft/validated else StudioVersionConflict -> validate_new phase=activate -> insert via _insert_with_children or replace: lock target with target_guard, update_definition + _replace_children -> set_status activated -> post-commit best-effort vault clean-up of removed slugs). 14 tests x memory/postgres where parametrised + concurrent activation on PG (one success, one version_conflict): 29 pass; storage suite 216 pass. Mutations RED: status check, python-drafts tenant clause, target_guard, activate phase (via phase-spy test), cleanup call, draft lock/guard, post-children version.

**Deviations from spec**: none
