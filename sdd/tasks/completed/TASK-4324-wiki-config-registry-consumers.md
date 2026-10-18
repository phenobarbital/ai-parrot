# TASK-4324: Wiki config validates backends against the registry; kind-driven is_built/storage_path

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4311, TASK-4323
**Assigned-to**: unassigned

---

## Context

Spec §3 M7. `Literal["sqlite","memory","arangodb"]` at models.py:114, project.py:605, :1063; `is_built` (:774-788) and `storage_path` branch on names; namespace validator (:263-267) coerces `database` entries to arangodb unconditionally.

---

## Scope

- Replace the three Literals with `str` + field validators calling `wiki_backend_names()` (lazy import to avoid cycles).
- `is_built`/`storage_path`: branch on `wiki_backend_spec(backend).kind` (+ optional is_built hook).
- Namespace validator: coerce to arangodb only when `backend` not in `model_fields_set`.
- Tests.

**NOT in scope**: CLI choices + literal audit (TASK-4325); sources.py (TASK-4326).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | MODIFY | registry-validated storage_backend |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | Literals, is_built, coercion |
| `packages/ai-parrot/tests/knowledge/wiki/test_wiki_config_registry.py` | CREATE | config tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.wiki.store import wiki_backend_names, wiki_backend_spec  # TASK-4323 (lazy inside validators)
```

### Existing Signatures to Use
```python
# models.py:114 storage_backend Literal; project.py: WikiNamespaceConfig :186 (backend free-form :224; coercion :263-267); WikiProjectConfig.backend :605; is_built :774; storage_path branches :785-787; WikiEnvOverlay.backend :1063
```

### Does NOT Exist
- ~~registry validation in config today~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/project.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_wiki_config_registry.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiNamespaceConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#WikiConfig"
  ]
}
```

---

## Implementation Notes

`wiki.store` imports `wiki.project`? Check for cycles — import the registry inside validators/functions.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Literals → validated str.
2. kind-driven is_built/storage_path.
3. Coercion fix.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'storage_backend: Literal["sqlite", "memory", "arangodb"] = Field(' parrot/knowledge/wiki/models.py)
# AFTER/AT — anchor `storage_backend: Literal["sqlite", "memory", "arangodb"] = Field(` (verified: models.py:114)
# REPLACE with `storage_backend: str = Field(`; ADD a field_validator checking wiki_backend_names() (lazy import)
```
**Why**: Registry is the source of truth.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")' parrot/knowledge/wiki/project.py)
# AFTER/AT — anchor `backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")` (verified: project.py:605)
# REPLACE with `backend: str = Field(default="sqlite")` + validator
```
**Why**: Same.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'backend: Literal["sqlite", "memory", "arangodb"] | None = None' parrot/knowledge/wiki/project.py)
# AFTER/AT — anchor `backend: Literal["sqlite", "memory", "arangodb"] | None = None` (verified: project.py:1063)
# REPLACE with `backend: str | None = None` + validator (None allowed)
```
**Why**: Same.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'object.__setattr__(self, "backend", "arangodb")' parrot/knowledge/wiki/project.py)
# AFTER/AT — anchor `object.__setattr__(self, "backend", "arangodb")` (verified: project.py:267)
# GUARD with: if "backend" not in self.model_fields_set:
```
**Why**: Explicit backends survive.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def is_built(self, root: Path) -> bool:' parrot/knowledge/wiki/project.py)
# AFTER/AT — anchor `def is_built(self, root: Path) -> bool:` (verified: project.py:774)
# FILL IN: body -> spec = wiki_backend_spec(self.backend); hook if spec.is_built; server -> True; sqlite -> db_path exists; else pages dir
```
**Why**: kind-driven.

### `packages/ai-parrot/tests/knowledge/wiki/test_wiki_config_registry.py` (CREATE)
```python
"""Config validated by the wiki registry (FEAT-540 M7)."""
import pytest

# FILL IN: unknown backend -> ValidationError naming known; registered satellite accepted in all three models; server spec is_built True; namespace database+explicit backend not coerced
```
**Why**: Spec §4 test_wiki_backend_kind / test_namespace_dispatch_backend_neutral.

### FILL IN checklist
- [ ] validators
- [ ] is_built/storage_path
- [ ] tests

---

## Acceptance Criteria

- [ ] no backend `Literal` left in models.py/project.py
- [ ] existing project/remote-config tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_config_registry.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_remote_config.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4324 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: native sonnet (attempt 2aabb379), consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: WikiConfig.storage_backend, WikiProjectConfig.backend and WikiEnvOverlay.backend are now `str` validated against wiki_backend_names() (lazy import); namespace validator coerces a `database` entry to arangodb only when `backend` was not explicitly set; is_built() branches on wiki_backend_spec(backend).kind with an optional spec.is_built hook. storage_path left unchanged (never branched on backend names). 8 tests in test_wiki_config_registry.py. Verification `partial`: tests/knowledge/wiki = 1020 passed; the only failures (53 failed + 38 errors) are Postgres ConnectionRefused (no DB here) and the pre-existing non-Postgres set verified against clean c57431a06. No review corrections.

**Deviations from spec**: none.
