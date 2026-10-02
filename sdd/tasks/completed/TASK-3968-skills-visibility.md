# TASK-3968: [W3.3] Skills visibility — list/GET/publish/PUT/DELETE/import per route table, skill PATCH handler (M8)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3964, TASK-3961
**Assigned-to**: unassigned
**Spec task label**: W3.3 (spec §3 "Task plan")

---

## Context

Spec §2 route rows for `/skills*` and `POST /agents/{name}/skills/import/{id}`, Module 8, C4, C11, C27,
A4. The catalogue is the existing `navigator.ai_skills_catalog` extended in place by FEAT-621
(content column `body`). The Redis `<org_id>/_shared` namespace is never an authorization source.

---

## Scope

- List/GET: filter + identical 404 + visibility fields.
- `POST /skills`: `_require_author`; reserved keys; `validate_visibility`; stamp; `StudioNameConflict` ⇒ `_name_taken` (was `duplicate`, `skills_catalog.py:361-362`).
- `PUT`/`DELETE /skills/{id}`: 404 check BEFORE today's `_require_owner` (`:411`, `:456`), then 403.
- `POST /agents/{name}/skills/import/{id}`: skill must be visible (else 404); agent must be visible (404) and manageable (403).
- New `StudioSkillVisibilityHandler.patch`. Route registration is TASK-3972.
- Update `test_skills_catalog.py:240` (`duplicate` → `name_taken`).

**NOT in scope**: `/skills/resync` (TASK-3961); catalogue service/index semantics (FEAT-621).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py` | MODIFY | Visibility filter, 404-before-403, publish gate/stamp/name_taken, import rule, `StudioSkillVisibilityHandler` |
| `packages/ai-parrot-server/tests/studio/test_skills_visibility.py` | CREATE | Skills route matrix incl. PUT/DELETE 404-before-403 and import rule |
| `packages/ai-parrot-server/tests/studio/test_skills_catalog.py` | MODIFY | `duplicate` → `name_taken` (:240) |

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
from .access import StudioAccess  # TASK-3964
from .models import SkillPublishRequest, VisibilityUpdateRequest  # verified SkillPublishRequest models.py:78; VisibilityUpdateRequest TASK-3964

# --- Created by FEAT-621 (agentstudio-db-storage); NOT on dev at 32b1a45d4. Verify each name after the
# --- FEAT-621 task named in "Cross-feature ordering" merges; if a name differs, FEAT-621's wins (package rule).

from .storage.models import StudioNameConflict, StudioWriteGuard  # FEAT-621 W0 ; StudioSkillCatalogService (W2)
```

### Existing Signatures to Use
```python
# S/studio/skills_catalog.py (verified at 32b1a45d4; FEAT-621 W3 rewrites; re-anchor)
class StudioSkillsCatalogHandler           # :268 ; get :276 ; entries = await self._list_entries(**filters) :303 ;
                                           #   _get_one :316 ; post :333 ; owner=user.user_id, :374 ; "duplicate" :362 ;
                                           #   put :397 ; _require_owner :411 ; delete :442 ; _require_owner :456
class StudioSkillsImportHandler            # :515 ; post :527 ; exists, owner = await self._resolve_agent(agent_name) :541
```

### Does NOT Exist
- ~~authorization from the Redis `<org_id>/_shared` namespace~~ — never
- ~~`StudioSkillVisibilityHandler`~~ — created here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_skills_visibility.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_skills_catalog.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py#StudioSkillsCatalogHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py#StudioSkillsImportHandler"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Same check order as TASK-3966.

### Key Constraints
- **Request fields (TASK-3964 review)**: TASK-3964 deliberately does NOT add `visibility`/`allowed_groups` to `SkillPublishRequest` (no handler read them, they would have been silently dropped). THIS task adds `visibility: Literal["private", "tenant", "groups"] = "private"` and `allowed_groups: list[str] = Field(default_factory=list)` to `SkillPublishRequest` in `models.py` together with the skills publish handler code that reads and stamps them (add `models.py` to this task's files if missing).
- `_require_owner(entry.owner, user)` occurs twice (`:411`, `:456`): quote the preceding lookup per site to disambiguate (spec Edit Sites).
- Skill import copies into the agent's assets; un-sharing does not revoke copies (FEAT-467 design).
- Anchors below were verified at `32b1a45d4` (before FEAT-621 W3). FEAT-621 W3 rewrites these handler bodies (`_legacy_*` + store paths): re-run every `grep -c` after rebasing on it and re-locate each anchor; a count of `0` means drift — stop and report (spec §6 Edit Sites note).

### Cross-feature ordering (package X16)
- Cross-feature ordering: needs **FEAT-621 W3** "Handler switch: drafts, catalogue, testing" merged first on `studio/skills_catalog.py` (per-file rule) plus FEAT-621 W2 "Draft + catalogue services" (`StudioSkillCatalogService`).
- Cross-feature ordering: TASK-3961 merged before FEAT-621 W3 on this file — confirm its resync gate survived the rebase.

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_skills_catalog.py` — legacy suite

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Rebase on FEAT-621 W3; re-anchor (two `_require_owner` sites need context).
2. Apply 404-first and the publish gate; add the import rule; add the visibility handler.
3. Update the legacy assertion; write the matrix.

### `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '        self._require_owner(entry.owner, user)  # raises 403 on denial' skills_catalog.py) — :411, :456
# FILL IN: disambiguate — quote the lookup lines preceding each site (PUT :397-411, DELETE :442-456) and insert
#   `if not access.can_see(rec): return self._not_found("skill", skill_id)` ABOVE each.
# occurrences: 1 (verified: grep -c '            owner=user.user_id,' skills_catalog.py) — :374 → stamp via access.stamp(...)
# occurrences: 1 (verified: grep -c '        exists, owner = await self._resolve_agent(agent_name)' skills_catalog.py) — :541 → import rule


@is_authenticated()
@user_session()
class StudioSkillVisibilityHandler(_StudioSkillsMixin, StudioBaseView):
    """``PATCH {prefix}/skills/{id}/visibility``."""

    async def patch(self):
        # FILL IN: same contract as agents, via StudioSkillCatalogService.update_visibility
        raise NotImplementedError
```
**Why**: Spec M8 skeleton.

### `packages/ai-parrot-server/tests/studio/test_skills_catalog.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert (await _decode(response))["code"] == "duplicate"' test_skills_catalog.py) — :240
        assert (await _decode(response))["code"] == "name_taken"
```
**Why**: AC3 documented change.

### `packages/ai-parrot-server/tests/studio/test_skills_visibility.py` (CREATE)
```python
"""FEAT-605 M8 — skills route matrix."""
from __future__ import annotations

async def test_skill_list_and_get_visibility(aiohttp_client): ...
async def test_skill_put_delete_404_before_403(aiohttp_client): ...
async def test_skill_publish_gate_and_name_taken(aiohttp_client): ...
async def test_skill_import_needs_visible_skill_and_manageable_agent(aiohttp_client): ...
async def test_skill_visibility_patch(aiohttp_client): ...
```
**Why**: Spec W3.3 tests column.

### FILL IN checklist
- [ ] four `skills_catalog.py` sites + handler; bounded by spec §2 skill rows
- [ ] five tests

---

## Acceptance Criteria

- [ ] AC5/AC6 (skills): PUT/DELETE answer 404 for an invisible skill before 403
- [ ] AC9/AC10/AC11/AC13 (skills): visibility PATCH; GET fields; per-tenant `name_taken`; `authoring_denied` on publish
- [ ] Import requires a visible skill and a manageable agent
- [ ] AC3: `test_skills_catalog.py` green with the documented change

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_skills_visibility.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_skills_catalog.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_scope_route_gates.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_skills_visibility.py — see blueprint (5 tests)
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3968 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback loop, tramo B2)
**Date**: 2026-10-02
**Notes**: Skills catalogue visibility. List/GET filtered by `StudioAccess` and carry the visibility fields; legacy items get the
additive fields (`access: "global"`); tenantless opted-in list is empty. Publish: `_require_author` → reserved keys (400 `owner`,
`created_by`, `tenant`) → `validate_visibility` (422 codes) → stamp → `StudioNameConflict` ⇒ `name_taken` (legacy duplicate → `name_taken`
too). `SkillPublishRequest` gains `visibility`/`allowed_groups` with this reading code; PUT refuses them (400, change via `/visibility`).
PUT/DELETE: 404 (invisible) → 403 (not manageable) via `_db_skill`; import: skill must be visible (404), agent visible (404) and
manageable (403). `StudioSkillVisibilityHandler` (`skills_catalog/_visibility.py`); route registration is TASK-3972.
Mutations RED (restored): list filter; name_taken mapping; reserved keys; visibility handler manage; visibility refusal; tenantless
list; PUT manage; legacy view fields; import skill-visibility.
Tests: `test_skills_visibility.py` (5); `test_skills_catalog.py` (+legacy additive assertions, `duplicate`→`name_taken`),
`test_skills_catalog_db_mode.py:96` `duplicate`→`name_taken`.

**Deviations from spec**: package modules instead of `skills_catalog.py`; `test_skills_catalog_db_mode.py` and `models.py` touched.
