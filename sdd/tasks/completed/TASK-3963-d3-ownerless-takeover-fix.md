# TASK-3963: [W1.5] D3 fix — activation replace over an ownerless/foreign agent refused, codes normalised to name_taken (part of M7)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3959, TASK-3962
**Assigned-to**: unassigned
**Spec task label**: W1.5 (spec §3 "Task plan") — **early subset** (§3 "Early subset and release gate"; no sibling-spec dependency)

---

## Context

Spec §1 D3, C19, C4, §3 W1.5, AC11, AC29. `POST /drafts/{name}/activate` with `replace=true` over an
agent whose `created_by` is `None` succeeds for any user (`drafts.py:337-351`): the check
`existing_owner is not None and …` short-circuits for ownerless agents. Both 409 bodies
(`name_collision`, `not_owner`) also disclose ownership. Fix against the current code, no storage.

One of the three per-file-rule exemptions: merges **before** FEAT-621 W3.

---

## Scope

- In `StudioDraftActivateHandler.post`, when `registry.has(name)`:
  - `replace=false` ⇒ `self._name_taken(name)` (was `name_collision`);
  - `replace=true` and (`existing_owner is None` or ≠ caller) and caller not superuser ⇒ `self._name_taken(name)` (was `not_owner`, and ownerless now refused).
- Keep: owner (or superuser) with `replace=true` proceeds.
- Tests `test_replace_ownerless_refused`, `test_replace_foreign_refused`, body carries no owner.

**NOT in scope**: Tenant-path declarative activation (TASK-3967); D2 (unchanged on the legacy path); moving files / imports (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` | MODIFY | D3 refusal + normalised `name_taken` in `StudioDraftActivateHandler.post` |
| `packages/ai-parrot-server/tests/studio/test_drafts_d3.py` | CREATE | `test_replace_ownerless_refused`, `test_replace_foreign_refused`, owner replace still works |

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
# no new imports; uses self._name_taken (TASK-3959)
```

### Existing Signatures to Use
```python
# S/studio/drafts.py
class StudioDraftActivateHandler                          # :270
    async def post(self):                                 # :279
        user = await self._get_user()                     # :301
        if registry.has(name):                            # :337
            existing_owner = (existing_meta.bot_config.config or {}).get("created_by")   # :341
            if not activate_request.replace:              # :342
                return self._error(..., status=409, code="name_collision")             # :343-346
            if existing_owner is not None and str(existing_owner) != str(user.user_id) and not user.is_superuser:  # :347
                return self._error(..., status=409, code="not_owner")                  # :348-351
```

### Does NOT Exist
- ~~a refusal for ownerless agents on replace~~ — the `existing_owner is not None` short-circuit allows it today (D3)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_drafts_d3.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py#StudioDraftActivateHandler.post"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Same early-return shape as the current block; only the condition and the body change.

### Key Constraints
- No ownership disclosure: both refusals use the identical `_name_taken` body (C4, AC11).
- `existing_owner is None` must NOT short-circuit to "allowed".
- Plain-host behaviour change is documented by TASK-3974 (CHANGELOG: `name_taken` replaces `name_collision`/`not_owner`).

### Cross-feature ordering (package X16)
- Cross-feature ordering: early subset — no sibling dependency (X16).
- Cross-feature ordering: **merges before FEAT-621 W3** "Handler switch: drafts, catalogue, testing" (`drafts.py`); FEAT-621 W3 rebases on it (C33, AC29).

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_drafts.py` — existing activation tests (must stay green; none asserts `name_collision`/`not_owner`)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Replace the two error returns with `_name_taken` and drop the `existing_owner is not None` short-circuit — *why*: D3 + C4.
2. Write the tests with a registry holding an ownerless agent and a foreign-owned agent.

### `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if existing_owner is not None and str(existing_owner) != str(user.user_id) and not user.is_superuser:' drafts.py) — :347
# REPLACE drafts.py:342-351 (the `if not activate_request.replace:` block and the not_owner block) with:
            if not activate_request.replace:
                return self._name_taken(name)
            if not user.is_superuser and (existing_owner is None or str(existing_owner) != str(user.user_id)):
                return self._name_taken(name)
```
**Why**: D3: an ownerless agent is not 'free to take'. One non-enumerating body (AC11).

### `packages/ai-parrot-server/tests/studio/test_drafts_d3.py` (CREATE)
```python
"""FEAT-605 W1.5 — D3: replace over an ownerless or foreign agent is refused, without disclosure."""
from __future__ import annotations

async def test_replace_ownerless_refused(aiohttp_client, tmp_path): ...
    # FILL IN: registry has agent 'x' with created_by None; user B activates draft 'x' replace=true ⇒ 409 name_taken;
    #   mutation: restore the `existing_owner is not None` short-circuit ⇒ RED.
async def test_replace_foreign_refused(aiohttp_client, tmp_path): ...   # body has no owner/source/tenant
async def test_replace_without_flag_is_name_taken(aiohttp_client, tmp_path): ...
async def test_owner_replace_still_works(aiohttp_client, tmp_path): ...
```
**Why**: Spec §4 mutation row `D3 refusal` → `test_replace_ownerless_refused`.

### FILL IN checklist
- [ ] `test_drafts_d3.py` — registry fixture (pattern: `test_drafts.py` activate tests), real `SessionData`; bounded by AC29

---

## Acceptance Criteria

- [ ] AC29 (D3): `replace=true` over an agent whose owner is `None` or another user ⇒ 409 `name_taken`; `name_collision`/`not_owner` bodies normalised to `name_taken`
- [ ] AC11 (activation part): the 409 body carries no owner/source/tenant
- [ ] `test_drafts.py` green
- [ ] Mutation: restore the `existing_owner is not None` short-circuit ⇒ `test_replace_ownerless_refused` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_drafts_d3.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_drafts.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_drafts_d3.py
async def test_replace_ownerless_refused(aiohttp_client, tmp_path): ...
async def test_replace_foreign_refused(aiohttp_client, tmp_path): ...
async def test_replace_without_flag_is_name_taken(aiohttp_client, tmp_path): ...
async def test_owner_replace_still_works(aiohttp_client, tmp_path): ...
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3963 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5)
**Date**: 2026-09-30
**Notes**: Activation replace over ownerless/foreign agent refused; name_collision/not_owner normalised to name_taken. Mutation RED. test_drafts.py green.
**Mutation evidence**:

**Deviations from spec**: none
