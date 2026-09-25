# TASK-3693: `DatabaseAgent(schema_plane=…)`: open the plane, propagate `origin`, warm toolkits from it

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3691, TASK-3684
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (agent half). `DatabaseAgent` gains `schema_plane: SchemaPlaneService | Path | None`. A `Path` is opened with `SchemaPlaneService.from_dir(path, read_only=False)` (lazy import — AC13 keeps `bots/database` free of wiki imports at module level). In the toolkit loop (agent.py:205-224) the partition gets `plane`, `origin = tk.origin` (TASK-3691 default = database_type) and `plane_write=True`; `tk_id` stays exactly `f"{database_type}_{primary_schema}"`.

---

## Scope

- Modify `agent.py` `__init__`: new kwarg, `self._schema_plane` resolution.
- Modify the toolkit loop: after `create_partition`, set `partition.plane`, `partition.origin`, `partition.dialect`, `partition.plane_write`. Log once when a plane is configured; do nothing when None.
- Write `test_agent_schema_plane.py` (uses the existing `conftest.py` fixtures in tests/bots/database).

**NOT in scope**: Cache/toolkit internals (TASK-3691/3692), CLI, any `tk_id` change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | schema_plane kwarg + partition wiring |
| `packages/ai-parrot/tests/bots/database/test_agent_schema_plane.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.bots.database.agent import DatabaseAgent                       # verified: packages/ai-parrot/src/parrot/bots/database/agent.py:126 (__init__)
from parrot.bots.database.cache import CacheManager, CachePartitionConfig     # verified: cache.py:612, :33
# lazy, inside the method body only (AC13):
from parrot.knowledge.wiki.schema.service import SchemaPlaneService           # TASK-3684 (from_dir(plane_dir, config=None, read_only=True))
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/agent.py — class DatabaseAgent
    def __init__(self, ...)                                                   # :126
        self.cache_manager = CacheManager(redis_url=redis_url, vector_store=vector_store)   # :145 ← anchor; add self._schema_plane resolution after
        for tk in self.toolkits:                                              # :205
            tk_id = f"{tk.database_type}_{tk.primary_schema}"                 # :206 ← anchor (DO NOT CHANGE)
            ...
            if tk.cache_partition is None:                                    # :211
                partition = self.cache_manager.create_partition(CachePartitionConfig(**config_kwargs))   # :221
                tk.cache_partition = partition                                # :222 ← wire plane attrs right after
            self.query_router.register_database(tk.database_type, tk_id)      # :224
# TASK-3691: CachePartition.plane / plane_write / origin / dialect attributes; DatabaseToolkit.origin (defaults to database_type)
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py:111 DatabaseToolkit(..., cache_partition: Optional[CachePartition] = None, ...)
```

### Does NOT Exist
- ~~`DatabaseAgent.schema_plane` kwarg~~ — new here
- ~~module-level `from parrot.knowledge.wiki…` in agent.py~~ — forbidden (AC13); import inside the resolver method
- ~~renaming `tk_id` to the origin alias~~ — rejected in the brainstorm (router registration key)
- ~~`LedgerService.from_dir`~~ — FEAT-569, unrelated; use `SchemaPlaneService.from_dir` (TASK-3684)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/database/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/database/test_agent_schema_plane.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/database/agent.py#DatabaseAgent",
    "sym:packages/ai-parrot/src/parrot/bots/database/cache.py#CacheManager.create_partition"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
agent.py:205-230 — the toolkit start loop; `_cache_ttl_by_completeness` propagation for how optional agent config reaches partitions.

### Key Constraints
- `schema_plane=None` ⇒ zero behaviour change; existing `test_database_agent.py` green.
- When a toolkit already has a `cache_partition`, still set the plane attrs on it (they default to None).
- Log one info line when a plane is configured.

### References in Codebase
- packages/ai-parrot/src/parrot/bots/database/agent.py:126-230
- sdd/specs/sql-schema-plane.spec.md §3 Module 6, AC12

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Add the kwarg + `_resolve_schema_plane` — why: Path or service, opened rootless (AC12).
2. Wire partition attrs after `tk.cache_partition = partition` — why: the tier is per partition.
3. Tests with a fake service/Path over a temp plane.

### `packages/ai-parrot/src/parrot/bots/database/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self.cache_manager = CacheManager(redis_url=redis_url, vector_store=vector_store)' packages/ai-parrot/src/parrot/bots/database/agent.py) → agent.py:145
# AFTER — insert below:
        self._schema_plane = self._resolve_schema_plane(schema_plane)  # FEAT-600 (kwarg added to __init__ signature: `schema_plane: Any = None`)

# NEW METHOD on DatabaseAgent (place after __init__):
    def _resolve_schema_plane(self, schema_plane: Any) -> Any:
        """Accept a SchemaPlaneService, a plane directory Path, or None. Lazy import keeps bots/database wiki-free (AC13)."""
        if schema_plane is None:
            return None
        if isinstance(schema_plane, (str, Path)):
            from parrot.knowledge.wiki.schema.service import SchemaPlaneService  # TASK-3684

            schema_plane = SchemaPlaneService.from_dir(Path(schema_plane), read_only=False)
        self.logger.info("DatabaseAgent: schema plane enabled (%s)", getattr(schema_plane, "plane_dir", schema_plane))
        return schema_plane

# occurrences: 1 (verified: grep -c '            tk_id = f"{tk.database_type}_{tk.primary_schema}"' …/agent.py) → agent.py:206  — DO NOT MODIFY this line
# AFTER `                tk.cache_partition = partition` (:222) and ALSO for the pre-existing-partition branch, insert (dedented to the loop body):
            if self._schema_plane is not None and tk.cache_partition is not None:
                tk.cache_partition.plane = self._schema_plane
                tk.cache_partition.origin = getattr(tk, "origin", None) or tk.database_type   # TASK-3691 default
                tk.cache_partition.dialect = tk.database_type
                tk.cache_partition.plane_write = True
```
**Why**: Origin comes from the toolkit (brainstorm decision), `tk_id` is untouched so `query_router.register_database` keeps working; the lazy import satisfies AC13.

### FILL IN checklist
- [ ] exact `__init__` signature placement of `schema_plane` (keyword-only, default None)
- [ ] tests: `schema_plane=None` leaves partitions without plane attrs; Path → `from_dir` called and `plane_write` True; origin propagated from `tk.origin`

---

## Acceptance Criteria

- [ ] `DatabaseAgent(...)` without `schema_plane` behaves as before; `test_database_agent.py` green
- [ ] `DatabaseAgent(schema_plane=Path)` opens the plane rootless and every partition has `plane`, `origin`, `plane_write=True` (AC12)
- [ ] `tk_id` unchanged
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/database/test_agent_schema_plane.py -q`
- `pytest packages/ai-parrot/tests/bots/database/test_database_agent.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/database/test_agent_schema_plane.py
# Uses the fixtures in packages/ai-parrot/tests/bots/database/conftest.py (fake toolkits / llm) — read them first.
import pytest

async def test_plane_path_wires_partitions(tmp_path, agent_factory):   # FILL IN: fixture name per conftest.py
    agent = agent_factory(schema_plane=tmp_path / "schema")
    tk = agent.toolkits[0]
    assert tk.cache_partition.plane is not None and tk.cache_partition.plane_write is True
    assert tk.cache_partition.origin == tk.database_type

async def test_no_plane_no_change(agent_factory):
    agent = agent_factory()
    assert getattr(agent.toolkits[0].cache_partition, "plane", None) is None
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3691, TASK-3684` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (seat: gpt-5.6-terra, backend: codex, attempt_uid 320d3cdc18044f539b7bfdc90bfaf716)
**Date**: 2026-09-24
**Notes**: Implementation commit `0bf172f26` (merge `3a41e768a`; no lint-autofix needed). `DatabaseAgent(schema_plane=…)`: opens the plane, propagates `origin`, warms toolkits from it. Engine-side merge fidelity check passed (`unexpected_files: []`).
**Merge validation**: pending as part of the final feature-wide integration test task (TASK-3696).

**Deviations from spec**: none
