---
type: Wiki Overview
title: 'TASK-403: Tools Migration — Batch 1 (Simple Tools)'
id: doc:sdd-tasks-completed-task-403-tools-migration-batch1-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'First batch of tool migrations: simple, self-contained tools with few/no
  external dependencies. This validates the migration pattern and proxy resolution
  before tackling complex tools.'
relates_to:
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.zipcode
  rel: mentions
---

# TASK-403: Tools Migration — Batch 1 (Simple Tools)

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-399, TASK-402
**Assigned-to**: unassigned

---

## Context

First batch of tool migrations: simple, self-contained tools with few/no external dependencies. This validates the migration pattern and proxy resolution before tackling complex tools.

Implements: Spec Module 6 — Tools Migration (Batch 1).

---

## Scope

- Move simple tools from `packages/ai-parrot/src/parrot/tools/` to `packages/ai-parrot-tools/src/parrot_tools/`:
  - Identify all tools that are self-contained with zero or minimal external deps
  - Candidates: zipcode, wikipedia, weather, calculator, file_reader, ddg_search, youtube_search, and similar simple tools
- For each moved tool:
  - Use `git mv` to preserve history
  - Update internal imports: `from parrot.tools.abstract import AbstractTool` stays (core dep)
  - Add entry to `TOOL_REGISTRY` in `parrot_tools/__init__.py`
- Verify backward-compat imports via proxy: `from parrot.tools.X import Y` still works
- Run tests after each batch of moves

**EXCLUDED from migration (stays in core)**: `PythonREPLTool`, `VectorStoreSearchTool`, `MultiStoreSearchTool`, `OpenAPIToolkit`, `RESTTool`, `MCPToolManagerMixin`, `ToJsonTool`, `AgentTool`, and all base classes (`abstract.py`, `toolkit.py`, `manager.py`, `discovery.py`).

**NOT in scope**: Toolkit-based tools (TASK-404). Complex/heavy tools (TASK-405).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/<tool>/` | CREATE (via git mv) | Migrated tool directories |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Update TOOL_REGISTRY |
| `packages/ai-parrot/src/parrot/tools/<tool>/` | DELETE (via git mv) | Removed from core |

---

## Implementation Notes

### Migration pattern per tool

```bash
# Move the tool
git mv packages/ai-parrot/src/parrot/tools/zipcode/ packages/ai-parrot-tools/src/parrot_tools/zipcode/

# In the moved tool, imports FROM core stay the same:
# from parrot.tools.abstract import AbstractTool  ← this still works (core dep)
# from parrot.tools.toolkit import AbstractToolkit  ← still works

# Add to TOOL_REGISTRY:
# "zipcode": "parrot_tools.zipcode.toolkit.ZipcodeAPIToolkit",
```

### Key Constraints
- Tool internal logic must NOT change — only the file location and registry entry
- All `from parrot.tools.X import Y` backward-compat imports must work via proxy
- Run tests after each tool move to catch issues early

---

## Acceptance Criteria

- [ ] All simple tools moved to `parrot_tools/`
- [ ] `TOOL_REGISTRY` updated with all moved tools
- [ ] `from parrot.tools.<tool> import <Class>` works via proxy for each moved tool
- [ ] `from parrot_tools.<tool> import <Class>` works as direct import
- [ ] Core tools (PythonREPLTool, etc.) still importable from `parrot.tools`
- [ ] All existing tests pass

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
