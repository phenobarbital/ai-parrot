# TASK-404: Tools Migration — Batch 2 (Toolkit-Based Tools)

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-403
**Assigned-to**: unassigned

---

## Context

Second batch: toolkit-based tools that extend `AbstractToolkit`. These are more complex than simple tools but still well-structured. `OpenAPIToolkit` stays in core (it's a generic dynamic tool generator, not service-specific).

Implements: Spec Module 7 — Tools Migration (Batch 2).

---

## Scope

- Move toolkit-based tools to `parrot_tools/`:
  - JiraToolkit, DockerToolkit, GitToolkit, SlackToolkit, PulumiToolkit, and other `AbstractToolkit` subclasses
- For each: `git mv`, update `TOOL_REGISTRY`, verify proxy resolution
- **OpenAPIToolkit stays in core** — it's a generic dynamic tool generator

**NOT in scope**: Simple tools (TASK-403). Heavy tools (TASK-405).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/<toolkit>/` | CREATE (via git mv) | Migrated toolkit directories |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Update TOOL_REGISTRY |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | Add per-toolkit extras if needed |

---

## Acceptance Criteria

- [ ] All toolkit-based tools (except OpenAPIToolkit) moved to `parrot_tools/`
- [ ] Toolkit registration and discovery work via `ToolManager`
- [ ] `from parrot.tools.jira import JiraToolkit` works via proxy
- [ ] `from parrot.tools.openapi import OpenAPIToolkit` works directly (core)
- [ ] All existing tests pass

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
