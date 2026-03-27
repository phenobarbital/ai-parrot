# TASK-409: Tests & Validation

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-398, TASK-399, TASK-400, TASK-401, TASK-402, TASK-403, TASK-404, TASK-405, TASK-406, TASK-407, TASK-408
**Assigned-to**: unassigned

---

## Context

Final validation: comprehensive tests verifying the entire monorepo migration works end-to-end. Tests proxy resolution, discovery, backward compat, core tool availability, error messages, and full install scenarios.

Implements: Spec Module 12 — Tests & Validation.

---

## Scope

- Create/update tests verifying:
  - `import parrot` works without `ai-parrot-tools` or `ai-parrot-loaders`
  - `from parrot.bots import Chatbot, Agent` works without tools/loaders packages
  - Core tools available without `ai-parrot-tools`: PythonREPLTool, VectorStoreSearchTool, MultiStoreSearchTool, OpenAPIToolkit, RESTTool, MCPToolManagerMixin, ToJsonTool, AgentTool
  - Proxy resolution: `from parrot.tools.jira import JiraToolkit` works (with tools installed)
  - Direct import: `from parrot_tools.jira.toolkit import JiraToolkit` works
  - Loader proxy: `from parrot.loaders.youtube import YoutubeLoader` works
  - Discovery: `ToolManager().available_tools()` returns all registered tools
  - Error messages: missing tool raises `ImportError` with `uv pip install ai-parrot-tools[X]`
  - Error messages: missing loader raises `ImportError` with `uv pip install ai-parrot-loaders`
- Run full existing test suite to verify no regressions
- Verify `uv sync --all-packages` + `pytest` from clean state

**NOT in scope**: CI pipeline changes (TASK-408).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_monorepo_imports.py` | CREATE | Proxy, discovery, backward compat tests |
| `tests/test_core_tools.py` | CREATE | Verify core tools always available |

---

## Acceptance Criteria

- [ ] All new tests pass
- [ ] Full existing test suite passes (no regressions)
- [ ] Core tools importable without ai-parrot-tools
- [ ] Proxy resolution verified for tools and loaders
- [ ] Error messages verified for missing packages
- [ ] Discovery verified via ToolManager

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
