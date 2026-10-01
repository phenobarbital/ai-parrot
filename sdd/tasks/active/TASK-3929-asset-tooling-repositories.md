# TASK-3929: StudioAssetRepository and StudioToolingRepository

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W1 — Repositories (M3, part 3: StudioAssetRepository, StudioToolingRepository)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3928
**Assigned-to**: unassigned

---

## Context

Spec §2.5 (`StudioAssetRepository`, `StudioToolingRepository`), §2.5a (child writes only under the agent lock),
§2.3 (child tables + touch-parent trigger). Methods taking `agent_id` receive it ONLY from `lock()`/`insert()` in the
same transaction or from `load_snapshot()`.

---

## Scope

- `StudioAssetRepository`: `list(part, agent_name, kind=None)` (content omitted), `get(part, agent_name, kind, name)`,
  `total_size(conn, agent_id)`, `put(conn, agent_id, asset, *, sha256)`, `delete(conn, agent_id, kind, name)`,
  `replace_all(conn, agent_id, assets)`.
- `StudioToolingRepository`: `list(part, agent_name)`, `list_locked(conn, agent_id)`,
  `replace(conn, agent_id, *, toolkits, mcp_servers)` (delete + insert in position order).
- Partitioned methods join `ai_agents` with the partition predicate.

**NOT in scope**: Size/quota/content-type validation (service, TASK-3936); secret split (TASK-3934).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py` | MODIFY | asset and tooling repositories |
| `packages/ai-parrot-server/tests/studio/storage/test_child_repositories.py` | CREATE | real-PG child repository tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.models import StudioAssetInput, StudioAssetRecord, StudioToolingRecord  # TASK-3922
from parrot.handlers.studio.storage.repositories import StudioAgentRepository  # TASK-3928
```

### Existing Signatures to Use
- `0002_ai_agents.sql`: `ai_agent_assets` PK `(agent_id, kind, name)`, `size = octet_length(content)`,
  `sha256` hex CHECK, 1 MiB hard cap; `ai_agent_tooling` PK `(agent_id, kind, slug)`, `position`, `config`,
  `secret_refs`, `vault_owner`; both have the AFTER touch trigger bumping the parent `version`.

### Does NOT Exist
- ~~A repository method that accepts an `agent_id` from a caller-supplied value~~ — forbidden by construction.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_child_repositories.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: extends storage/repositories.py after TASK-3928 (same file; joins through StudioAgentRepository's partition predicate and row mappers)
- Cross-feature ordering: none (X16 early subset).
- `put` = `INSERT … ON CONFLICT (agent_id, kind, name) DO UPDATE`; compute `size` as `octet_length($content)` in SQL
  so it always matches the CHECK.
- `replace` deletes rows of each kind then inserts the new ones with `position = index` — ordering by
  `(kind, position)` is what the builder relies on.

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
1. Append both classes — *why*: §2.5 method list is fixed.
2. Tests: child writes bump the parent version (trigger), partition isolation on child reads, `total_size`.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py` (MODIFY — append)
```python
class StudioAssetRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def list(self, part: StudioPartition, agent_name: str, kind: str | None = None) -> list[StudioAssetRecord]:
        """Content omitted (content=None)."""
        # FILL IN: JOIN navigator.ai_agents a USING (agent_id) WHERE a.tenant IS NOT DISTINCT FROM $1 AND a.name = $2
        raise NotImplementedError
    # FILL IN: get, total_size, put, delete, replace_all (signatures exactly §2.5).


class StudioToolingRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool
    # FILL IN: list, list_locked, replace (signatures exactly §2.5).
```

### `packages/ai-parrot-server/tests/studio/storage/test_child_repositories.py` (CREATE)
```python
"""FEAT-621 M3 — child repositories (AC7, version bump)."""
# FILL IN: test_partition_isolation_children (beta partition cannot list/get acme assets/tooling);
#   test_version_bumps_on_child_write (asset put, tooling replace each bump ai_agents.version);
#   test_total_size_and_replace_all; test_tooling_replace_keeps_position_order.
```

### FILL IN checklist
- [ ] nine methods; four tests.

---

## Acceptance Criteria

- [ ] Child rows are unreachable from another partition (`test_partition_isolation_children`, AC7).
- [ ] Asset put and tooling replace bump the parent `version` (`test_version_bumps_on_child_write`, repository half).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_child_repositories.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_partition_isolation_children` | AC7 |
| `test_version_bumps_on_child_write` | §2.6 |
| `test_total_size_and_replace_all` | §2.5 |
| `test_tooling_replace_keeps_position_order` | §2.7 map (order) |

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
   `feat(agentstudio-db-storage): TASK-3929 — StudioAssetRepository and StudioToolingRepository`.
8. Close with `scripts/sdd/close_task.sh TASK-3929 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
