# TASK-405: Tools Migration — Batch 3 (Complex/Heavy Tools)

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-404
**Assigned-to**: unassigned

---

## Context

Final tools batch: complex tools with heavy external dependencies and cross-imports. These include DB tools, financial analysis, scraping, code interpreter, sandbox, sitesearch, flowtask wrapper, etc. Most complex migration due to external deps and potential cross-tool imports.

Implements: Spec Module 8 — Tools Migration (Batch 3).

---

## Scope

- Move remaining tools to `parrot_tools/`:
  - DB tools (db, querytoolkit, qsource, databasequery, dataset_manager, nextstop, products)
  - Financial tools (technical_analysis, etc.)
  - Scraping tools (scraping/, seleniumwire-based)
  - Code interpreter, sandbox
  - Sitesearch
  - Flowtask wrapper
  - Analysis tools
  - Excel, MS Word tools
  - All remaining tools not in Batch 1/2 and not in the core exclusion list
- Update per-tool extras in `packages/ai-parrot-tools/pyproject.toml` with correct dependency lists
- Update `TOOL_REGISTRY` with all moved tools
- Verify all backward-compat imports via proxy
- Test thoroughly — these tools have the most external deps

**NOT in scope**: Core tools stay in core. Loaders (TASK-406).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/...` | CREATE (via git mv) | All remaining tool directories |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Final TOOL_REGISTRY |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | Per-tool extras with correct deps |

---

## Implementation Notes

### Cross-tool imports

Some tools import from other tools (e.g., dataset_manager may import from db). After migration, these become intra-package imports: `from parrot_tools.db import ...` — which is fine since they're in the same package.

### External dependency mapping

Each tool's external deps must be mapped to the correct extras group in `pyproject.toml`. Use FEAT-056's lazy import pattern — tools already use `lazy_import()` from `parrot._imports`.

### Key Constraints
- This is the largest task — consider splitting into sub-batches during implementation
- Run tests after each sub-batch
- Watch for circular imports between tools

---

## Acceptance Criteria

- [ ] ALL non-core tools moved to `parrot_tools/`
- [ ] `TOOL_REGISTRY` contains all migrated tools
- [ ] Per-tool extras in pyproject.toml match actual dependencies
- [ ] All backward-compat imports work via proxy
- [ ] No tool code remains in `packages/ai-parrot/src/parrot/tools/` except proxy, base classes, and 8 core tools
- [ ] All existing tests pass with `ai-parrot-tools[all]` installed

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
