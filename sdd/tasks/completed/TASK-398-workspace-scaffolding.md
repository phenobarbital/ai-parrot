# TASK-398: Workspace Scaffolding

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task for FEAT-057. Creates the `uv` workspace structure, transforms the root `pyproject.toml` into a workspace root, moves existing `parrot/` into `packages/ai-parrot/src/parrot/`, and creates empty sub-package scaffolds. No code logic changes — purely structural.

Implements: Spec Module 1 — Workspace Scaffolding.

---

## Scope

- Create `packages/` directory with 3 sub-packages:
  - `packages/ai-parrot/` — core package
  - `packages/ai-parrot-tools/` — tools package (empty initially)
  - `packages/ai-parrot-loaders/` — loaders package (empty initially)
- Each sub-package uses `src/` layout: `packages/<pkg>/src/<import_name>/`
- Transform root `pyproject.toml` into workspace root:
  - Add `[tool.uv.workspace] members = ["packages/*"]`
  - Move shared dev-dependencies to root
  - Move shared tool configs (pytest, ruff, mypy) to root
  - Root is NOT a package — no `[project]` with actual package name
- Create `packages/ai-parrot/pyproject.toml`:
  - `name = "ai-parrot"`, inherits current version, all current core dependencies
  - `[tool.setuptools.packages.find] where = ["src"]`
  - Keep optional-dependencies groups from current pyproject (post-FEAT-056)
  - Keep Cython/Maturin build config
- Move `parrot/` to `packages/ai-parrot/src/parrot/`
- Create `packages/ai-parrot-tools/pyproject.toml`:
  - `name = "ai-parrot-tools"`, depends on `ai-parrot`
  - `[tool.uv.sources] ai-parrot = { workspace = true }`
  - Empty `src/parrot_tools/__init__.py`
- Create `packages/ai-parrot-loaders/pyproject.toml`:
  - `name = "ai-parrot-loaders"`, depends on `ai-parrot`
  - `[tool.uv.sources] ai-parrot = { workspace = true }`
  - Empty `src/parrot_loaders/__init__.py`
- Verify `uv sync --all-packages` works
- Run existing tests to verify nothing breaks

**NOT in scope**: Moving any tool/loader code. Proxy modules. Discovery system.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | Transform into workspace root |
| `packages/ai-parrot/pyproject.toml` | CREATE | Core package config |
| `packages/ai-parrot/src/parrot/` | MOVE | Move existing `parrot/` here |
| `packages/ai-parrot-tools/pyproject.toml` | CREATE | Tools package config |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | CREATE | Empty with TOOL_REGISTRY = {} |
| `packages/ai-parrot-loaders/pyproject.toml` | CREATE | Loaders package config |
| `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` | CREATE | Empty with LOADER_REGISTRY = {} |
| `tests/` | KEEP | Stays at root (shared fixtures) |

---

## Implementation Notes

### Critical: Preserve git history

Use `git mv parrot/ packages/ai-parrot/src/parrot/` to preserve file history.

### Root pyproject.toml structure

```toml
[project]
name = "ai-parrot-workspace"
version = "0.0.0"
requires-python = ">=3.10.1"

[tool.uv.workspace]
members = ["packages/*"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
# ... existing pytest config
```

### Key Constraints
- `uv sync --all-packages` must succeed after restructure
- All existing imports must still work (paths haven't changed inside `parrot/`)
- Tests must pass — this is a non-breaking structural move
- `.venv/` stays at repo root
- `sdd/`, `tests/`, `plugins/`, `examples/` stay at repo root

### References in Codebase
- Current `pyproject.toml` — source of all dependency/config info
- `sdd/proposals/monorepo-migration.brainstorm.md` §3 — detailed pyproject configs

---

## Acceptance Criteria

- [ ] `packages/` directory exists with 3 sub-packages
- [ ] Each sub-package has `pyproject.toml` and `src/` layout
- [ ] Root `pyproject.toml` has `[tool.uv.workspace]`
- [ ] `uv sync --all-packages` completes successfully
- [ ] `python -c "import parrot"` works
- [ ] `pytest tests/ -x` passes (at least smoke tests)
- [ ] `git log --follow packages/ai-parrot/src/parrot/__init__.py` shows history

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** and brainstorm for full context
2. **Update status** in `tasks/.index.json` → `"in-progress"`
3. **Create directory structure** before moving files
4. **Use `git mv`** to preserve history
5. **Verify `uv sync`** works before committing
6. **Run tests** to verify nothing breaks
7. **Move this file** to `tasks/completed/TASK-398-workspace-scaffolding.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
