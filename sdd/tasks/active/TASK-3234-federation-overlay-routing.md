# TASK-3234: Federated overlay namespace routing for ledger IDs

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
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

- [ ] Bare overlay IDs route to exactly one overlay and returned ledger rows stay qualified.
- [ ] Ledger-to-code neighbors are local/unqualified and local inbound lookup includes qualified ledger sources.
- [ ] Prefix collisions fail construction and federation tests pass unchanged without overlays.
- [ ] `pytest tests/knowledge/wiki/test_federation_overlay.py tests/knowledge/wiki/test_federation.py -q` passes.

## Test Specification

Use in-memory fake namespace stores; no ledger database is required.

