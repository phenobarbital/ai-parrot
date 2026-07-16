---
type: Wiki Overview
title: 'TASK-1365: Create ai-parrot-server package scaffold'
id: doc:sdd-tasks-completed-task-1365-package-scaffold-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 1 from the spec. Creates the empty satellite package structure
  following the FEAT-201 precedent. This is the foundation — all other tasks depend
  on this scaffold existing.
relates_to:
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.server
  rel: mentions
---

# TASK-1365: Create ai-parrot-server package scaffold

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context
Implements Module 1 from the spec. Creates the empty satellite package structure following the FEAT-201 precedent. This is the foundation — all other tasks depend on this scaffold existing.

## Scope
- Create `packages/ai-parrot-server/pyproject.toml` with:
  - `name = "ai-parrot-server"`, `dependencies = ["ai-parrot"]`
  - `[tool.setuptools.packages.find]` with `where = ["src"]`, `include = ["parrot*"]`, `namespaces = true`
  - `[tool.uv.sources] ai-parrot = { workspace = true }`
  - Optional extras: `scheduler` (apscheduler==3.11.2), `mcp`, `a2a`, `autonomous` (aiofiles), `all`
  - Dynamic version via `parrot.handlers.version`
- Create `packages/ai-parrot-server/README.md`
- Create empty namespace dirs with `.gitkeep` (NO `__init__.py`):
  `src/parrot/`, `src/parrot/mcp/`, `src/parrot/a2a/`, `src/parrot/handlers/`, `src/parrot/manager/`, `src/parrot/services/`, `src/parrot/scheduler/`, `src/parrot/autonomous/`
- Create `packages/ai-parrot-server/tests/` directory
- Verify `uv sync --all-packages` works

**NOT in scope**: Moving any source files (later tasks), modifying host pyproject.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/pyproject.toml` | CREATE | Package metadata, deps, extras |
| `packages/ai-parrot-server/README.md` | CREATE | Package description |
| `packages/ai-parrot-server/src/parrot/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-server/src/parrot/mcp/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-server/src/parrot/a2a/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-server/src/parrot/handlers/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-server/src/parrot/manager/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-server/src/parrot/services/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-server/src/parrot/scheduler/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-server/src/parrot/autonomous/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-server/tests/__init__.py` | CREATE | Test root |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Reference: packages/ai-parrot-embeddings/pyproject.toml (FEAT-201 precedent)
# [tool.setuptools.packages.find]
# where = ["src"]
# include = ["parrot*"]
# namespaces = true
```

### Existing Signatures to Use
```python
# Root pyproject.toml — workspace auto-discovery
# [tool.uv.workspace]
# members = ["packages/*"]   # line 46 — auto-includes new package
```

### Does NOT Exist
- ~~`packages/ai-parrot-server/`~~ — does not exist yet; this task creates it
- ~~`parrot.server`~~ — no top-level parrot.server module; satellite contributes to parrot.* namespaces
- ~~Any `__init__.py` in satellite namespace dirs~~ — PEP 420 forbids them

## Implementation Notes

### Pattern to Follow
Copy the structure from `packages/ai-parrot-embeddings/pyproject.toml` — same setuptools config, same workspace reference pattern, same `namespaces = true`.

### Key Constraints
- ZERO `__init__.py` files at namespace levels
- Use `.gitkeep` files to preserve empty directories in git
- The satellite depends on `ai-parrot` (core), not the other way around

### References in Codebase
- `packages/ai-parrot-embeddings/pyproject.toml` — proven satellite config
- `packages/ai-parrot-embeddings/src/parrot/.gitkeep` — namespace marker pattern

## Acceptance Criteria
- [ ] `packages/ai-parrot-server/pyproject.toml` exists with correct config
- [ ] No `__init__.py` files in any satellite `src/parrot/` directory
- [ ] `uv sync --all-packages` succeeds
- [ ] Package appears in `uv pip list` as editable install

## Test Specification
```python
# Verified manually: uv sync --all-packages
# No automated test needed for scaffold; TASK-1377 covers wheel tests
```

## Agent Instructions
(standard — see template)

## Completion Note
*(Agent fills this in when done)*
