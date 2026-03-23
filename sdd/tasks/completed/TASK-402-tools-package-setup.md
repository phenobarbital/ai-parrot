# TASK-402: Tools Package Setup

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-398
**Assigned-to**: unassigned

---

## Context

Creates the `ai-parrot-tools` package structure with proper `pyproject.toml`, per-tool optional extras groups, and the `TOOL_REGISTRY` dict in `__init__.py`. This is the target package where tools will be migrated to.

Implements: Spec Module 5 — Tools Package Setup.

---

## Scope

- Create `packages/ai-parrot-tools/pyproject.toml`:
  - `name = "ai-parrot-tools"`, same version as core
  - `dependencies = ["ai-parrot>=<version>"]`
  - Per-tool optional extras: `jira`, `slack`, `aws`, `docker`, `git`, `openapi`, `analysis`, `excel`, `sandbox`, `codeinterpreter`, `pulumi`, `sitesearch`, `office365`, `finance`, `db`, `scraping`, `flowtask`, `all`
  - `[tool.setuptools.packages.find] where = ["src"]`
  - `[tool.uv.sources] ai-parrot = { workspace = true }`
- Create `packages/ai-parrot-tools/src/parrot_tools/__init__.py`:
  - Module docstring explaining the package
  - `TOOL_REGISTRY: dict[str, str] = {}` (empty initially, populated as tools migrate)
- Verify `uv sync --all-packages` still works with new package

**NOT in scope**: Moving any tool code. That's TASK-403/404/405.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/pyproject.toml` | CREATE | Full package config with extras |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Add TOOL_REGISTRY + docstring |

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-tools/pyproject.toml` exists with per-tool extras
- [ ] `uv sync --all-packages` includes ai-parrot-tools
- [ ] `from parrot_tools import TOOL_REGISTRY` works (returns empty dict)
- [ ] `ai-parrot-tools` depends on `ai-parrot`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
