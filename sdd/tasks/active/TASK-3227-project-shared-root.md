# TASK-3227: Shared-root resolution and ledger project path

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Ledger and worktree consumers must resolve the main checkout, not a linked-worktree root, before opening shared `.parrot` state. TASK-3226 / FEAT-557 must be merged and verified first.

## Scope

- Add `resolve_git_common_dir`, `is_linked_worktree`, and failure-tolerant `find_shared_root`.
- Add `WikiProjectConfig.ledger_path(root)` returning `<shared-root>/.parrot/ledger`.
- Test plain checkout, `gitdir`/`commondir` worktree layout, and `PARROT_SHARED_ROOT` override.

**NOT in scope**: SQLite policy/config fields, ledger databases, hooks, or DevLoop consumers.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | Shared Git-root helpers and ledger path. |
| `tests/knowledge/wiki/test_project_shared_root.py` | CREATE | Root-resolution coverage. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.project import PARROT_DIR, WikiProjectConfig, find_project_root
```

### Existing Signatures to Use
```python
# project.py:365, 470-481, 640, 667
class WikiProjectConfig(BaseModel):
    def storage_path(self, root: Path) -> Path: ...
    def db_path(self, root: Path) -> Path: ...

def find_project_root(start: Path | None = None) -> Path | None: ...
def load_project_config(root: Path) -> WikiProjectConfig: ...
```

### Does NOT Exist
- ~~`find_shared_root` / `resolve_git_common_dir` / `is_linked_worktree`~~ — this task creates them.
- ~~a ledger-specific SQLite setting~~ — FEAT-557 owns SQLite configuration.

## Acceptance Criteria

- [ ] Plain and linked worktrees resolve the same main root without CWD assumptions.
- [ ] Environment override is honored only for an existing directory.
- [ ] `ledger_path()` is deterministic and creates no files.
- [ ] `pytest tests/knowledge/wiki/test_project_shared_root.py -q` passes.

## Test Specification

Use temporary Git metadata fixtures; never mutate the repository `.git` directory.

