# TASK-3972: [W4.1] Routes and request models — three visibility PATCH routes and route ordering (M11)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3960, TASK-3966, TASK-3967, TASK-3968, TASK-3971
**Assigned-to**: unassigned
**Spec task label**: W4.1 (spec §3 "Task plan")

---

## Context

Spec §3 W4.1 / Module 11, X13, AC9. Wires the three visibility PATCH handlers into
`setup_studio_routes` with correct ordering (`/skills/resync` and `/skills/{id}/visibility` before
`/skills/{id}`), and validates the request models end to end.

Relocation note: the spec lists `models.py` and `drafts.py` (request models) under W4.1, but
`StudioCapabilities` is needed by W1.2 and `VisibilityUpdateRequest` + the create-model fields by
W3.1–W3.3; those landed in TASK-3960, TASK-3964 and TASK-3967. This task keeps the routes
and the model-validation tests.

Unblocks: **U-SV** (real PATCH).

---

## Scope

- Register `PATCH {prefix}/agents/{name}/visibility` (`StudioAgentVisibilityHandler`), `/drafts/{name}/visibility` (`StudioDraftVisibilityHandler`), `/skills/{id}/visibility` (`StudioSkillVisibilityHandler`) through the TASK-3957 registrar (wrapper applied, prefix honoured).
- Ordering: `/skills/resync` and `/skills/{id}/visibility` before `/skills/{id}`.
- Tests: route-order test; request-model validation (`VisibilityUpdateRequest`, `CreateAgentRequest`/`SkillPublishRequest`/`SaveDraftRequest` visibility fields).

**NOT in scope**: Handler logic (TASK-3966..13); new models (already landed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | Register the three visibility PATCH routes with correct ordering |
| `packages/ai-parrot-server/tests/studio/test_visibility_routes.py` | CREATE | Route-order test + request-model validation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified for this task at `32b1a45d4`, `dev`). The implementing agent MUST use these
> exact imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed, VERIFY it
> exists first with `grep` or `read`. Paths are relative to the repo root unless a line says
> otherwise; `S/` = `packages/ai-parrot-server/src/parrot/handlers/`.

### Verified Imports
```python
from .agents import StudioAgentVisibilityHandler          # TASK-3966
from .drafts import StudioDraftVisibilityHandler          # TASK-3967
from .skills_catalog import StudioSkillVisibilityHandler  # TASK-3968
from parrot.handlers.studio.models import VisibilityUpdateRequest, CreateAgentRequest, SkillPublishRequest  # TASK-3964
```

### Existing Signatures to Use
```python
# S/studio/__init__.py (after TASK-3957/05/16): _Registrar.add(path, view); _register_* helpers;
#   existing skills ordering comment :77-82 (literal /skills/resync before dynamic /skills/{id})
```

### Does NOT Exist
- ~~`PATCH …/visibility` routes~~ today — added here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_visibility_routes.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py#setup_studio_routes"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Add the routes inside the existing per-area helpers (`_register_agents`, `_register_drafts`, `_register_skills`).

### Key Constraints
- aiohttp matches in registration order: literal/longer skill routes before `/skills/{id}`.
- Through `reg.add(...)` only, so `view_wrapper` and `prefix` apply (AC16).

### Cross-feature ordering (package X16)
- Cross-feature ordering: none beyond its dependencies (FEAT-621 W3 already precedes TASK-3966..13). `studio/__init__.py` — serialise with any FEAT-621 edit still pending on that file.

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_scaffold.py` — route listing helper `_route_paths`

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the three `reg.add(..., <Kind>VisibilityHandler)` lines in the right helpers and order.
2. Write the route-order and model-validation tests.

### `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` (MODIFY)
```python
# in _register_agents (after "/agents/{name}/reload"):
    reg.add("/agents/{name}/visibility", StudioAgentVisibilityHandler)
# in _register_drafts (after "/drafts/{name}/activate"):
    reg.add("/drafts/{name}/visibility", StudioDraftVisibilityHandler)
# in _register_skills: AFTER "/skills/resync" and BEFORE "/skills/{id}":
    reg.add("/skills/{id}/visibility", StudioSkillVisibilityHandler)
# FILL IN: lazy imports inside each helper, as today — bounded by "a not-yet-implemented area never breaks startup"
```
**Why**: X13 routes; ordering per spec M11.

### `packages/ai-parrot-server/tests/studio/test_visibility_routes.py` (CREATE)
```python
"""FEAT-605 M11 — visibility routes and request models."""
from __future__ import annotations

def test_skill_route_order(): ...            # /skills/resync and /skills/{id}/visibility before /skills/{id}
def test_visibility_routes_under_prefix(): ...
def test_visibility_update_request_validation(): ...   # unknown level ⇒ ValidationError; default allowed_groups []
def test_create_models_default_private(): ...
```
**Why**: Spec W4.1 tests column.

### FILL IN checklist
- [ ] route lines + four tests; bounded by X13 and route-order rule

---

## Acceptance Criteria

- [ ] AC9 (wiring): `PATCH …/visibility` exists for agents, drafts and skills under the mount prefix
- [ ] Route-order test green; model validation tests green

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_visibility_routes.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_scaffold.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_visibility_routes.py — 4 tests (see blueprint)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-tenant-visibility --feature-id FEAT-605`)
2. **Read the spec** at the path listed above for full context (§2 is normative; §3 has the task table)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-tenant-visibility.json`, AND every
   "Cross-feature ordering" item in Implementation Notes must hold (sibling feature tasks merged)
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Re-run each blueprint `grep -c` anchor; a count of `0` means drift — stop and report
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-tenant-visibility.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands, and run each
   listed mutation check (revert the guard, see the named test go RED, restore by re-applying
   the edit — never with `git checkout` of the file)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3972 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
