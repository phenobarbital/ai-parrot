# TASK-5234: Remove `/enable` route, handler, and `EnableResponse` model

- **Feature**: FEAT-821 remove-enable-route
- **Spec**: `sdd/specs/remove-enable-route.spec.md`
- **Status**: pending
- **Priority**: high
- **Estimated effort**: small (1–2 hours)
- **Depends-on**: none
- **Assigned-to**: agent
- **Discovered-from**: `issue:7ede49d4d598`

## Context

The `/enable` integrations endpoint is a compatibility no-op that returns the
current integration descriptor without mutating state. External callers (TROC
AgentChat) have been confirmed gone. Remove all traces of this dead route.

## Scope

Remove the `/enable` route registration, handler method, dispatch branch,
`EnableResponse` model, and its re-exports. Update docstrings and tests.

### NOT in scope
- Other integrations endpoints (`/connect`, `DELETE`, `GET`)
- `IntegrationsService.status()` (still used elsewhere)
- `enable_*` config flags in manager.py (unrelated boolean params)

## Files to Modify

1. `packages/ai-parrot-server/src/parrot/manager/manager.py` — remove route registration (lines 2487–2490)
2. `packages/ai-parrot-server/src/parrot/handlers/integrations.py` — remove docstring refs, dispatch branch, `_post_enable` method
3. `packages/ai-parrot/src/parrot/auth/oauth2/models.py` — remove `EnableResponse` class
4. `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` — remove import and `__all__` entry

## Codebase Contract

### Verified Imports
- `from parrot.auth.oauth2.models import EnableResponse` — exists at `models.py:100`
- `EnableResponse` in `__init__.py` import (line 39) and `__all__` (line 72)

### Existing Signatures
- `IntegrationsHandler._post_enable(self) -> web.Response` at `integrations.py:170`
- `IntegrationsHandler.post(self) -> web.Response` at `integrations.py:91` — dispatch logic at lines 104–107

### Does NOT Exist
- No external consumer of `EnableResponse` outside these files (verified by grep)
- No test file directly tests the `/enable` endpoint

## Implementation Blueprint

1. **manager.py**: Delete the 4-line `router.add_view(…/enable…)` block.
2. **integrations.py**:
   a. Module docstring: remove line 9–10 (the `/enable` bullet).
   b. Class docstring: remove line 40 (the `/enable` bullet).
   c. `post()` docstring: remove line 96 referencing `_post_enable`.
   d. `post()` body: remove lines 104–105 (`if path.endswith("/enable"): return …`).
   e. `post()` 404 error message: change `"Use /connect or /enable."` → `"Use /connect."`.
   f. Delete the entire `_post_enable` method (lines 170–197).
3. **models.py**: Delete the `EnableResponse` class (lines 100–107).
4. **__init__.py**: Remove `EnableResponse` from the import tuple (line 39) and from `__all__` (line 72).

## Acceptance Criteria

- AC-1: `grep -rn 'EnableResponse' packages/ai-parrot/src/ packages/ai-parrot-server/src/` returns nothing.
- AC-2: `grep -rn '/enable' packages/ai-parrot-server/src/parrot/handlers/integrations.py packages/ai-parrot-server/src/parrot/manager/manager.py` returns nothing related to the integrations enable endpoint.
- AC-3: `ruff check packages/ai-parrot-server/src/parrot/handlers/integrations.py packages/ai-parrot-server/src/parrot/manager/manager.py packages/ai-parrot/src/parrot/auth/oauth2/models.py packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` passes.
- AC-4: Existing integrations tests pass.

## Validation Commands

```bash
ruff check packages/ai-parrot-server/src/parrot/handlers/integrations.py packages/ai-parrot-server/src/parrot/manager/manager.py packages/ai-parrot/src/parrot/auth/oauth2/models.py packages/ai-parrot/src/parrot/auth/oauth2/__init__.py
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src pytest packages/ai-parrot-server/tests/test_ts_codegen.py -x -q
```

## Completion Note

Removed all traces of the `/enable` compatibility route:
- Deleted route registration in manager.py (4 lines)
- Removed `_post_enable` method + dispatch branch in integrations.py (31 lines)
- Deleted `EnableResponse` model class (8 lines)
- Cleaned up re-exports in `__init__.py`
- Updated docstrings (route count, dispatch docs)
- All 4 changed files pass ruff; test_ts_codegen passes (4/4)
- grep confirms zero remaining references to EnableResponse or /enable route
