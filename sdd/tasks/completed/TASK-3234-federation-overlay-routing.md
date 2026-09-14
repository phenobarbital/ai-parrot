# TASK-3234: Federated overlay namespace routing for ledger IDs

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3226, TASK-3227
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13. Ledger is an overlay namespace: bare ledger IDs route there, code-plane destinations remain local, and local seeds receive inbound ledger links without changing normal namespace behavior.

## Scope

- Add validated `WikiNamespaceConfig.overlay_prefixes` and ledger kinds to context ID parsing.
- Extend construction/routing for unique overlay-prefix ownership and bare-ID routing.
- Extend neighbors for overlay-to-local hydration and local-to-overlay incoming edges.
- Preserve non-overlay behavior and add collision/regression tests.

**NOT in scope**: ledger write tools, FEAT-557 foreign-store policy plumbing, or `store.py` changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | Overlay config validation. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/context.py` | MODIFY | Ledger ID kinds. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | Overlay routing/neighbors. |
| `tests/knowledge/wiki/test_federation_overlay.py` | CREATE | Overlay and collision tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`qualify_id` and `split_namespaced_id` are in `context.py`; `FederatedWikiStore` and `NamespaceHandle` are in `federation.py:599,85`; `WikiNamespaceConfig` is in `project.py:175`.

### Existing Signatures to Use
`FederatedWikiStore._route(page_id)` is at `federation.py:849`; `get_page` and `neighbors` are at lines 897 and 913. `neighbors` currently qualifies every row with the seed namespace, so destination homing needs focused regression coverage.

### Does NOT Exist
- ~~`overlay_prefixes`~~ — this task creates it.
- ~~bare `issue:`/`task:` foreign routing~~ — currently routes local.
- ~~a `wikitoolkit ledger related` command~~ — intentionally absent.

## Acceptance Criteria

- [x] Bare overlay IDs route to exactly one overlay and returned ledger rows stay qualified.
- [x] Ledger-to-code neighbors are local/unqualified and local inbound lookup includes qualified ledger sources.
- [x] Prefix collisions fail construction and federation tests pass unchanged without overlays.
- [x] `pytest tests/knowledge/wiki/test_federation_overlay.py tests/knowledge/wiki/test_federation.py -q` passes.

## Test Specification

Use in-memory fake namespace stores; no ledger database is required.

### Completion Note

Implemented bare-id overlay routing, outgoing-neighbor re-qualification
(overlay → code plane returns unqualified), and incoming-edge folding
(local seeds see qualified inbound ledger edges) in `federation.py`, plus
`overlay_prefixes` on `WikiNamespaceConfig` (`project.py`) and the `issue`/
`task`/`spec`/`insight` id kinds in `context.py`.

**Consolidation fixes** (native haiku dispatch, orchestrator-applied
after the fact — see git log for both commits):
1. The sub-worktree's branch ref was reset to an earlier commit by
   unrelated pool cleanup after the agent finished; its actual commit
   (`5394d603f`) was recovered by SHA and merged with `git merge --no-ff`
   directly (clean auto-merge on `project.py`, no conflicts).
2. `tests/knowledge/wiki/test_federation_overlay.py` had been created at
   `packages/ai-parrot/tests/knowledge/wiki/` instead of the declared
   repo-root `tests/knowledge/wiki/` path — relocated.
3. `TestOverlayPrefixCollisions`'s three tests opened a read-only
   `SQLiteWikiStore` right after `upsert_pages([])` (empty), which never
   creates the underlying file, so the read-only open raised
   `FileNotFoundError` before the collision check under test ever ran —
   fixed by giving each store one placeholder page.

Verified: `pytest tests/knowledge/wiki/test_federation_overlay.py
tests/knowledge/wiki/test_federation.py -q` → 56 passed. `ruff check`
clean on all four files. Only the four listed files were touched (after
the path-relocation fix).

Seat: haiku (native) · Attempts: 1 (dispatch) + orchestrator consolidation
fixes · Duration: ~9m42s (agent) · Tokens: 135296 total (subagent-reported)

