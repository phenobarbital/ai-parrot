# TASK-5511: Unset `CREW_RESULT_STORAGE` follows `PARROT_USER_STORE`

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5495
**Assigned-to**: unassigned

---

## Context

Spec §2 "Crew/flow results", §3 Module 14, §8 Q2 (resolved), AC18. `get_result_storage()` falls back to
`CREW_RESULT_STORAGE`, whose `parrot.conf` default is `"documentdb"`, so a fresh MongoDB-free install still
tries DocumentDB when a crew/flow saves results. With this task an unset `CREW_RESULT_STORAGE` resolves
through `default_result_storage()` (the global switch, else `redis`); explicit values are unchanged.

---

## Scope

- `parrot/conf.py:313`: `CREW_RESULT_STORAGE = config.get("CREW_RESULT_STORAGE", fallback=None)`.
- `factory.py:58`: `name = name_or_instance or CREW_RESULT_STORAGE or default_result_storage()`; update the
  docstring precedence (line 42).
- Update `test_factory.py::test_factory_defaults_to_documentdb` to the new default and add tests.

**NOT in scope**: `RedisResultStorage` (URL, TTL unchanged), the implicit-default guard (TASK-5495/5508 already count `CREW_RESULT_STORAGE`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `CREW_RESULT_STORAGE` fallback `None` |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py` | MODIFY | default via `default_result_storage()` |
| `tests/bots/flows/core/storage/test_factory.py` | MODIFY | new default + global-switch test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import CREW_RESULT_STORAGE                 # verified: factory.py:7 (only reader of the constant)
from parrot.userstore import default_result_storage         # TASK-5495
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py
CREW_RESULT_STORAGE = config.get("CREW_RESULT_STORAGE", fallback="documentdb")   # line 313 (1 occurrence)

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py
_REGISTRY: dict[str, str] = {"redis": ..., "postgres": ..., "documentdb": ...}  # lines 12-16
def get_result_storage(name_or_instance: Union[str, "ResultStorage", None] = None) -> "ResultStorage":  # line 34
    # docstring step 3 (line 42): "``None`` → falls back to env var ``CREW_RESULT_STORAGE``, then defaults to ``"documentdb"``."
    name = name_or_instance or CREW_RESULT_STORAGE or "documentdb"              # line 58 (1 occurrence)

# tests/bots/flows/core/storage/test_factory.py
def test_factory_defaults_to_documentdb(monkeypatch):                            # line 48 — sets factory.CREW_RESULT_STORAGE = ""
```

### Does NOT Exist
- ~~Other readers of `parrot.conf.CREW_RESULT_STORAGE`~~ — only `factory.py` (verified by grep across `packages/*/src`).
- ~~`postgres` as a `PARROT_USER_STORE` value~~ — the global switch is `redis | documentdb`; `postgres` stays reachable through an explicit `CREW_RESULT_STORAGE`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/conf.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py", "action": "MODIFY"},
    {"path": "tests/bots/flows/core/storage/test_factory.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py#get_result_storage"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Change the conf fallback — *why*: "unset" must be distinguishable from "documentdb".
2. Change the factory default and docstring — *why*: AC18.
3. Update/add tests.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'CREW_RESULT_STORAGE = config.get("CREW_RESULT_STORAGE", fallback="documentdb")' packages/ai-parrot/src/parrot/conf.py)
# REPLACE line 313 with:
CREW_RESULT_STORAGE = config.get("CREW_RESULT_STORAGE", fallback=None)  # FEAT-878: None → follows PARROT_USER_STORE
```

### `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'name = name_or_instance or CREW_RESULT_STORAGE or "documentdb"' .../backends/factory.py)
# REPLACE line 58 with:
    name = name_or_instance or CREW_RESULT_STORAGE or default_result_storage()
# and add near the top imports (after `from parrot.conf import CREW_RESULT_STORAGE`, line 7):
from parrot.userstore import default_result_storage
# FILL IN: docstring step 3 (line 42-43) → "``None`` → env var ``CREW_RESULT_STORAGE``; when unset,
#   ``PARROT_USER_STORE`` (redis | documentdb), else ``"redis"`` (FEAT-878)."
```

### `tests/bots/flows/core/storage/test_factory.py` (MODIFY)
```python
# REPLACE test_factory_defaults_to_documentdb (line 48) with:
def test_factory_default_follows_global(monkeypatch):
    """No name, no CREW_RESULT_STORAGE → PARROT_USER_STORE, else redis (FEAT-878)."""
    monkeypatch.setattr("parrot.bots.flows.core.storage.backends.factory.CREW_RESULT_STORAGE", None)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    # FILL IN: patch _import_class as the old test did; assert "redis" in the imported path;
    #   then setenv PARROT_USER_STORE=documentdb and assert "documentdb".
```

### FILL IN checklist
- [ ] docstring update
- [ ] test body + explicit-value-wins test

---

## Acceptance Criteria

- [ ] `CREW_RESULT_STORAGE` unset → `RedisResultStorage`; `PARROT_USER_STORE=documentdb` → `DocumentDbResultStorage`; explicit `CREW_RESULT_STORAGE=postgres` → `PostgresResultStorage` (AC18)
- [ ] All `tests/bots/flows/core/storage/` modules listed below pass
- [ ] `ruff check` clean on both source files

---

## Validation Commands
- `pytest tests/bots/flows/core/storage/test_factory.py -q`
- `pytest tests/bots/flows/core/storage/test_persistence_mixin.py -q`
- `pytest tests/bots/flows/core/storage/test_agentcrew_lifecycle.py -q`
- `pytest tests/bots/flows/core/storage/test_agentsflow_lifecycle.py -q`

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_factory.py — additions
def test_result_storage_explicit_value_wins(monkeypatch):
    monkeypatch.setattr("parrot.bots.flows.core.storage.backends.factory.CREW_RESULT_STORAGE", "postgres")
    monkeypatch.setenv("PARROT_USER_STORE", "documentdb")
    # FILL IN: patch _import_class; assert "postgres" in the imported path
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Crew/flow results, §3 M14, AC18)
3. **Check dependencies** — TASK-5495 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5511 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
