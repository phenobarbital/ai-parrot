# TASK-3962: [W1.4] D1 fix — draft overwrite refused before the file write (part of M7)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3959
**Assigned-to**: unassigned
**Spec task label**: W1.4 (spec §3 "Task plan") — **early subset** (§3 "Early subset and release gate"; no sibling-spec dependency)

---

## Context

Spec §1 D1, C19, §3 W1.4, AC29. `POST /astudio/drafts` writes the draft file at `drafts.py:216`
**before** any row lookup, and `_upsert_draft_row` (`:93-117`) updates an existing row by name
without checking its owner. Any caller can overwrite another user's draft file and row. This is a
bug in every host, so it is fixed on the FEAT-467 path too, against the current `drafts.py`, with no
storage types.

One of the three per-file-rule exemptions: merges **before** FEAT-621 W3, whose `_legacy_*` bodies
carry the guard.

---

## Scope

- In `StudioDraftsHandler.post`, after slug validation and BEFORE `file_path.write_text(...)` (`:216`):
  resolve the caller (`user = await self._get_user()`, moved up), look up the existing row
  (`await self._get_draft_row(save_request.name)`); if it exists, its `owner_user_id` differs from the
  caller and the caller is not a superuser ⇒ return `self._name_taken(save_request.name)` (409, no
  owner disclosed). Nothing is written (file bytes and row unchanged).
- The caller's own draft stays overwritable; superuser behaviour unchanged.
- Test `test_draft_overwrite_refused` (+ own-draft still overwritable).

**NOT in scope**: D3 / activation (TASK-3963); the tenant-path declarative save (TASK-3967); D2 (moot on the tenant path, unchanged on the legacy path); changing `_upsert_draft_row` itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` | MODIFY | D1 guard in `StudioDraftsHandler.post` before the file write |
| `packages/ai-parrot-server/tests/studio/test_drafts_d1.py` | CREATE | `test_draft_overwrite_refused`, `test_own_draft_still_overwritable` |

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
# drafts.py already imports everything it needs; the guard uses only self._get_draft_row, self._get_user, self._name_taken
```

### Existing Signatures to Use
```python
# S/studio/drafts.py
class SaveDraftRequest(BaseModel)                         # :32 (name, source)
class _StudioDraftsMixin                                  # :45
    async def _get_draft_row(self, name: str) -> StudioDraft | None   # :65
    async def _upsert_draft_row(self, **fields) -> StudioDraft | None # :93 (D1: updates by name, no owner check)
class StudioDraftsHandler                                 # :155
    async def post(self):                                 # :181
        file_path = resolve_safe_path(self._drafts_dir(), f"{save_request.name}.py")   # :212
        file_path.write_text(save_request.source)         # :216  <- guard goes ABOVE this
        report = validate_draft(save_request.source)      # :219
        user = await self._get_user()                     # :223 (move above the guard)
# StudioDraft row: owner_user_id attribute (used at drafts.py:229, :302)
# S/studio/_base.py (after TASK-3959): _name_taken(slug) -> 409 {"code": "name_taken", ...}
```

### Does NOT Exist
- ~~an owner check in `_upsert_draft_row`~~ (D1) — do not add it there; the guard lives in `post` before the write
- ~~`name_taken` anywhere in drafts.py today~~ — introduced via `_name_taken` (TASK-3959)

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
      "path": "packages/ai-parrot-server/tests/studio/test_drafts_d1.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py#StudioDraftsHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py#_StudioDraftsMixin._get_draft_row",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py#_StudioDraftsMixin._upsert_draft_row"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Early-return error responses in the same handler (`return self._error(...)`, `drafts.py:187-210`).

### Key Constraints
- The guard must precede BOTH the file write (`:216`) and `_upsert_draft_row` (spec W1.4).
- 409 body comes from `_name_taken` (identical for agents/drafts/skills/activation, AC11) — no owner, no source.
- Superuser bypass uses `user.is_superuser` (scope-sourced in opted-in hosts after TASK-3959).
- Tests may replace the DB row helpers with an in-memory dict (data layer you cannot run); NEVER patch `_get_user` / `_resolve_session` (Rule 6) — install a real `SessionData`.

### Cross-feature ordering (package X16)
- Cross-feature ordering: early subset — no sibling dependency (X16).
- Cross-feature ordering: **merges before FEAT-621 W3** "Handler switch: drafts, catalogue, testing" (`drafts.py`); FEAT-621 W3 rebases and carries the guard into its `_legacy_*` bodies (C33, AC29).

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_drafts.py` — existing suite (must stay green)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Move `user = await self._get_user()` above the write — *why*: the guard needs the caller.
2. Insert the guard right above `file_path.write_text(save_request.source)` — *why*: D1 "file write precedes the lookup".
3. Write the tests asserting the on-disk bytes AND the row are unchanged after a refused save.

### `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'file_path.write_text(save_request.source)' drafts.py) — :216
# BEFORE — insert above `        file_path.write_text(save_request.source)` (verified: drafts.py:216)
        user = await self._get_user()
        existing = await self._get_draft_row(save_request.name)
        if (
            existing is not None
            and str(existing.owner_user_id) != str(user.user_id)
            and not user.is_superuser
        ):
            return self._name_taken(save_request.name)
# and DELETE the later `        user = await self._get_user()` (:223) — it is now resolved above.
```
**Why**: D1: refuse before anything is written. Same 409 body as every other `name_taken` (AC11).

### `packages/ai-parrot-server/tests/studio/test_drafts_d1.py` (CREATE)
```python
"""FEAT-605 W1.4 — D1: POST /drafts never overwrites another user's draft."""
from __future__ import annotations

async def test_draft_overwrite_refused(aiohttp_client, tmp_path): ...
    # FILL IN: user A saves 'x'; user B saves 'x' ⇒ 409 name_taken, body has no owner;
    #   file bytes on disk == A's source; row owner == A.
    #   Mutation: move the guard below the write ⇒ RED (bytes changed).
async def test_own_draft_still_overwritable(aiohttp_client, tmp_path): ...
```
**Why**: Spec §4 mutation row `D1 guard before write` → `test_draft_overwrite_refused`.

### FILL IN checklist
- [ ] `test_drafts_d1.py` — routed app, real `SessionData` per user, in-memory row helpers; bounded by AC29 and the mutation row

---

## Acceptance Criteria

- [ ] AC29 (D1): `POST /drafts` on a name whose existing row belongs to someone else ⇒ 409 `name_taken` before the file write and before `_upsert_draft_row`; file bytes and row unchanged
- [ ] Own draft still overwritable; superuser behaviour unchanged
- [ ] `test_drafts.py` green
- [ ] Mutation: move the guard after `write_text` ⇒ `test_draft_overwrite_refused` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_drafts_d1.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_drafts.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_drafts_d1.py
async def test_draft_overwrite_refused(aiohttp_client, tmp_path): ...
async def test_own_draft_still_overwritable(aiohttp_client, tmp_path): ...
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3962 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5)
**Date**: 2026-09-30
**Notes**: Guard before write_text in StudioDraftsHandler.post; 409 name_taken. Mutation (neutralise guard) RED; test_drafts.py green.
**Mutation evidence**:

**Deviations from spec**: none
