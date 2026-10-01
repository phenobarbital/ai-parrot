# TASK-3961: [W1.3] Scope-only route gates — /tools/{slug}/execute authoring gate, /skills/resync superuser from scope (part of M8/M9)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3959
**Assigned-to**: unassigned
**Spec task label**: W1.3 (spec §3 "Task plan") — **early subset** (§3 "Early subset and release gate"; no sibling-spec dependency)

---

## Context

Spec §2 route rows `POST /tools/{slug}/execute` and `POST /skills/resync`, C13, §3 W1.3, AC7, AC13.
PBAC is fail-open in FieldSync, so today any authenticated user can run any registered tool with
arbitrary args (`testing.py:344-346`). In an opted-in host the execute endpoint must require
`may_author` (`authoring_denied`) **before** the PBAC gate. `/skills/resync` must take
`is_superuser` from the scope only — `may_administer` alone is not enough.

This is a scope-only change against the CURRENT `testing.py` / `skills_catalog.py` with no storage
types. It is one of the three exemptions to the per-file rule: it merges **before** FEAT-621 W3,
which rebases on it.

Unblocks: **U-FS** (authoring gate on execute). The TOOLKITS scope enforcement and fail-closed host
writes on execute are still required before a tenant release (TASK-3969, release gate).

---

## Scope

- `StudioToolExecuteHandler.post`: when opted in, `if (denied := await self._require_author()) is not None: return denied`
  **before** the PBAC gate at `testing.py:346`. Plain host unchanged.
- `StudioSkillsResyncHandler.post`: when opted in, decide on `(await self._scope()).is_superuser`
  (never `may_administer`); plain host keeps `user.is_superuser` from the session. Keep the existing
  403 body `admin_required`.
- Tests: opted-in + `may_author=False` ⇒ 403 `authoring_denied` on execute; plain host unchanged;
  `may_administer` alone ⇒ resync 403; scope superuser ⇒ resync proceeds.

**NOT in scope**: TOOLKITS mandatory scope check, host-write fail-closed and `studio_scope` binding on execute (TASK-3969 / FEAT-622); any other route in these files; the skill visibility work (TASK-3968).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | Execute only: `_require_author` before the PBAC gate in opted-in hosts |
| `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py` | MODIFY | Resync only: superuser decision from the scope when opted in |
| `packages/ai-parrot-server/tests/studio/test_scope_route_gates.py` | CREATE | Execute authoring gate + resync superuser-from-scope tests |

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
from parrot.handlers.scope import RequestScope  # TASK-3956 (tests build scopes)
# handlers already import StudioBaseView from ._base (testing.py, skills_catalog.py)
```

### Existing Signatures to Use
```python
# S/studio/testing.py
class StudioToolExecuteHandler(_StudioTestingMixin, StudioBaseView):   # :341
    async def post(self):                                              # :344
        if (denied := await self._pbac_gate("testing", "astudio:testing:execute")) is not None:  # :346
# S/studio/skills_catalog.py
class StudioSkillsResyncHandler(_StudioSkillsMixin, StudioBaseView):   # :593
    async def post(self):                                              # :602 ; PBAC :604-605
        user = await self._get_user()                                  # :607
        if not user.is_superuser:                                      # :608
            return self._error("Admin privileges required.", status=403, code="admin_required")  # :609
# S/studio/_base.py (after TASK-3959): _opted_in(), _scope(), _require_author()
```

### Does NOT Exist
- ~~an authoring gate on `/tools/{slug}/execute`~~ — PBAC only today (`testing.py:346`)
- ~~`ToolScopeUnavailable` / `ensure_tool_scope` / host-write confirmation on execute~~ — FEAT-622 (TOOLKITS); not here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/testing.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_scope_route_gates.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#StudioToolExecuteHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py#StudioSkillsResyncHandler.post"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Walrus early-return shape already used for PBAC (`testing.py:346`): `if (denied := await self._require_author()) is not None: return denied`.

### Key Constraints
- Order on execute: `_studio_gate` (automatic, TASK-3959) → `_require_author` → PBAC → existing body (spec route row; C13).
- Resync: global `is_superuser` from the scope ONLY (spec route row); a tenant admin (`may_administer`) is refused.
- Plain host (no resolver): byte-identical behaviour (G9).

### Cross-feature ordering (package X16)
- Cross-feature ordering: early subset — no sibling dependency (X16).
- Cross-feature ordering: **merges before FEAT-621 W3** "Handler switch: drafts, catalogue, testing" (edits `testing.py` and `skills_catalog.py`); FEAT-621 W3 rebases on this task (C33, X16 — one of the three per-file-rule exemptions).

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_testing_surface.py`, `test_skills_catalog.py` — existing suites that must stay green

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Insert the authoring gate above the PBAC line in `StudioToolExecuteHandler.post` — *why*: C13 ordering.
2. Replace the resync superuser decision with a scope-sourced one when opted in — *why*: spec route row (global superuser only).
3. Write the tests with a real resolver + real `SessionData` (no `_get_user` patch).

### `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if (denied := await self._pbac_gate("testing", "astudio:testing:execute")) is not None:' testing.py) — :346
# BEFORE — insert above that line (inside StudioToolExecuteHandler.post)
        if (denied := await self._require_author()) is not None:
            return denied
```
**Why**: `_require_author` already returns None when not opted in, so plain hosts are unchanged (G9).

### `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if not user.is_superuser:' skills_catalog.py) — :608
# REPLACE `        if not user.is_superuser:` with:
        is_superuser = (await self._scope()).is_superuser if self._opted_in() else user.is_superuser
        if not is_superuser:
```
**Why**: Spec: `/skills/resync` requires the global `is_superuser` from the scope only (AC7).

### `packages/ai-parrot-server/tests/studio/test_scope_route_gates.py` (CREATE)
```python
"""FEAT-605 W1.3 — execute authoring gate and resync superuser-from-scope."""
from __future__ import annotations

async def test_execute_authoring_denied_when_opted_in(aiohttp_client): ...   # 403 authoring_denied before PBAC
                                                                             #   (mutation: remove the gate ⇒ RED)
async def test_execute_plain_host_unchanged(aiohttp_client): ...
async def test_resync_may_administer_alone_403(aiohttp_client): ...          # (mutation: accept may_administer ⇒ RED)
async def test_resync_scope_superuser_allowed(aiohttp_client): ...           # FILL IN: no DB ⇒ the 503 branch proves the gate passed
```
**Why**: Covers `test_authoring_denied[execute]` from the spec §4 mutation table.

### FILL IN checklist
- [ ] `test_scope_route_gates.py` — four routed tests (prefix `/api/v1/{tenant}/astudio`, real resolver, real `SessionData`); bounded by AC7/AC13

---

## Acceptance Criteria

- [ ] AC13 (execute part): opted-in + `may_author=False` ⇒ `POST /tools/{slug}/execute` 403 `authoring_denied`, before PBAC
- [ ] AC7 (resync part): `/skills/resync` requires `is_superuser` from the scope; `may_administer` alone ⇒ 403
- [ ] Plain host: `test_testing_surface.py` and `test_skills_catalog.py` green unchanged
- [ ] Mutation: delete the execute gate ⇒ `test_execute_authoring_denied_when_opted_in` RED; read `may_administer` in resync ⇒ `test_resync_may_administer_alone_403` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_scope_route_gates.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_testing_surface.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_skills_catalog.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_scope_route_gates.py
async def test_execute_authoring_denied_when_opted_in(aiohttp_client): ...
async def test_execute_plain_host_unchanged(aiohttp_client): ...
async def test_resync_may_administer_alone_403(aiohttp_client): ...
async def test_resync_scope_superuser_allowed(aiohttp_client): ...
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3961 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5)
**Date**: 2026-09-30
**Notes**: Execute authoring gate before PBAC; resync superuser from scope when opted in. Mutation (remove gate) RED. Existing testing/skills suites green.
**Mutation evidence**:

**Deviations from spec**: none
