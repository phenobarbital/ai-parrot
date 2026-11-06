---
feature_id: FEAT-821
type: feature
base_branch: dev
status: approved
projects: [ai-parrot-server, ai-parrot]
tags: [cleanup, oauth2, integrations]
---

# FEAT-821: Remove `/enable` compatibility route and `EnableResponse` model

## Problem Statement

The `/api/v1/agents/integrations/{agent_id}/{provider}/enable` endpoint is a
compatibility no-op left over from the original integrations implementation
(FEAT-144). It returns the current integration descriptor without mutating
state — identical to what `GET /api/v1/agents/integrations/{agent_id}` already
provides per-provider. TASK-5048 (FEAT-777) deferred removal pending
confirmation that external callers (TROC AgentChat repo) are gone. That
confirmation is complete; the route is unused.

**Discovered-from**: `issue:7ede49d4d598`

## Goals

1. Remove the `/enable` route registration from the server manager.
2. Remove the `_post_enable` handler method and its dispatch branch.
3. Remove the `EnableResponse` Pydantic model and its re-exports.
4. Update all affected tests and docstrings.

## Scope

### In scope
- Route registration in `parrot/manager/manager.py`
- Handler dispatch + `_post_enable` in `parrot/handlers/integrations.py`
- `EnableResponse` class in `parrot/auth/oauth2/models.py`
- Re-export in `parrot/auth/oauth2/__init__.py`
- Test adjustments in `ai-parrot-server/tests/`

### NOT in scope
- Any other integrations endpoints (`/connect`, `DELETE`, `GET`)
- The `IntegrationsService.status()` method (still used by other paths)
- The `enable_*` configuration flags in `manager.py` (unrelated)

## Design

Pure removal — no new code, no behavioral changes. The POST dispatcher's
404 error message is updated to reference only `/connect` (the sole
remaining POST sub-route).

## Acceptance Criteria

- AC-1: No Python file imports or references `EnableResponse`.
- AC-2: `grep -rn '/enable' packages/ai-parrot-server/src/` returns no route
  registration or handler branch for the integrations enable endpoint.
- AC-3: `ruff check` passes on all changed files.
- AC-4: Existing integrations tests pass (connect, disconnect, list).

## Open Questions

None.
