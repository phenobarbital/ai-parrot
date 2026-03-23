# TASK-407: Registry Generation Script

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-403
**Assigned-to**: unassigned

---

## Context

Creates `scripts/generate_tool_registry.py` that scans `parrot_tools/` and `parrot_loaders/` for tool/loader classes and generates/updates the `TOOL_REGISTRY` and `LOADER_REGISTRY` dicts. Includes `--check` mode for CI.

Implements: Spec Module 10 — Registry Generation Script.

---

## Scope

- Create `scripts/generate_tool_registry.py`:
  - Scans `parrot_tools/` for `AbstractTool` and `AbstractToolkit` subclasses
  - Scans `parrot_loaders/` for `BaseLoader` subclasses
  - Generates/updates `TOOL_REGISTRY` dict in `parrot_tools/__init__.py`
  - Generates/updates `LOADER_REGISTRY` dict in `parrot_loaders/__init__.py`
  - Modes: `--dry-run`, `--verbose`, `--check` (CI — exit 1 if stale)
  - Separates toolkits and individual tools in output
  - Preserves manual entries (marked with comments)
- Create optional git pre-commit hook `.githooks/pre-commit` (documented, not auto-installed)

**NOT in scope**: CI pipeline changes (TASK-408).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/generate_tool_registry.py` | CREATE | Registry generation/validation script |
| `.githooks/pre-commit` | CREATE | Optional hook for registry staleness check |

---

## Implementation Notes

### Reference in brainstorm §6.2

Follow the `scan_tools()`, `format_registry()`, `update_init_file()` pattern.

### Key Constraints
- Must work from workspace root: `uv run python scripts/generate_tool_registry.py`
- Must handle both `parrot_tools` and `parrot_loaders`
- `--check` mode must not modify files — only report staleness

---

## Acceptance Criteria

- [ ] `scripts/generate_tool_registry.py` exists and runs
- [ ] `--dry-run` shows what would change without writing
- [ ] `--check` exits 0 when registry is current, 1 when stale
- [ ] Generated registry matches actual tool classes in package
- [ ] Works for both TOOL_REGISTRY and LOADER_REGISTRY

---

## Completion Note

**Completed by**: Claude Opus 4.6
**Date**: 2026-03-23
**Notes**: AST-based scanner finds 136 tool classes and 22 loader classes. Supports --dry-run, --check (CI, exits 1 if stale), --verbose, --tools-only, --loaders-only. Preserves manually curated registry entries. Pre-commit hook created at .githooks/pre-commit (opt-in via `git config core.hooksPath .githooks`).

**Deviations from spec**: none
