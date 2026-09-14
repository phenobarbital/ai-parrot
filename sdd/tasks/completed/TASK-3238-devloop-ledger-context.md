# TASK-3238: DevLoop shared wiki and ledger research context

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226, TASK-3227, TASK-3232
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11. Dev-loop research currently gives up inside linked worktrees. It must use the shared plane and append bounded relevant ledger context without becoming fatal.

## Scope

- Make `DevLoopWikiSearch.from_project` resolve shared root before config/store lookup.
- Extend research context with `LedgerService.get_context` for task file/symbol scope when available.
- Keep wiki/ledger context best-effort, bounded, and logged on failure.
- Test linked-root resolution, relevant context, empty context, and degradation.

**NOT in scope**: dev-loop graph changes, ledger event creation, or requiring a built ledger index.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py` | MODIFY | Shared root/context enrichment. |
| `tests/knowledge/wiki/test_devloop_ledger_context.py` | CREATE | Worktree/best-effort tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`DevLoopWikiSearch` is in `wiki_search.py:26`; `find_shared_root` and `LedgerService` are produced by TASK-3227 and TASK-3232.

### Existing Signatures to Use
`DevLoopWikiSearch.from_project(root: Path | None = None)` is at `wiki_search.py:38`; `build_research_context(query, budget_tokens=4000)` is at line 91 and already degrades to `None` on failure.

### Does NOT Exist
- ~~worktree-shared root lookup in DevLoopWikiSearch~~ — this task adds it.
- ~~a fatal ledger dependency for research~~ — prohibited.

## Acceptance Criteria

- [ ] Linked worktree opens main checkout's wiki plane.
- [ ] Relevant ledger context is appended within budget; unavailable ledger leaves research usable.
- [ ] `pytest tests/knowledge/wiki/test_devloop_ledger_context.py -q` passes.

## Test Specification

Mock root/service boundaries and retain a temporary SQLite integration case.
