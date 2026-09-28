---
id: F008
query_id: Q008
type: git_log
intent: Inventory tests, recorded limitations/open items, doc drift and commit history for FEAT-598
executed_at: 2026-09-28T18:22:18Z
parent_id: null
depth: 0
---
# F008 — Tests, open items, doc drift and git history of FEAT-598
## Summary
Tests: core `packages/ai-parrot/tests/outputs/a2ui/linked/` (14 files incl. test_build_linked_surface, test_contract_envelopes,
test_executor, test_service, test_dsl_golden), tools `packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py`,
server `tests/handlers/test_ui_surfaces_linked_{handler,store}.py`, `tests/integration/test_linked_surfaces_e2e.py`
(real toolkit+service+store+handler; Postgres, QuerySource, catalog and guard are FAKED — asserts `querylimit == 5000`;
excluded from the merge tier as `integration`, needs PYTHONPATH over three packages). No test runs against a real
QuerySource slug, and no test builds a KPI/pie/grid dashboard. Open items from completion notes: `ensure_snapshot`
does not re-check owner access (TASK-3781 judgement call); Svelte lane never ran real vitest/svelte-check
(TASK-3795); Python executor skips `transform.ref` (logs a warning). Doc drift: the wire doc §3 says requests go to
`/api/v1/{tenant}/queries/{slug}` with `querylimit: 500`, but code uses `/api/v3/queries/{slug}` when tenant is null and
a 5000 fetch cap (500 is the snapshot cap).
## Citations
- path: `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py`
  lines: 1-6, 326-358
  symbol: `test_linked_surface_end_to_end`
  excerpt: |
    The real toolkit, linked service, UI-surface store, mixin, and handler are
    exercised.  Only the Postgres connection, QuerySource, catalog row, and
    data-plane authorization boundary are replaced.
    ...
    assert all(kwargs["conditions"]["querylimit"] == 5000 for kwargs in fake_core_qs.kwargs)
- path: `docs/outputs/a2ui-linked-surfaces.md`
  lines: 39-52
  symbol: `-`
  excerpt: |
    POST /api/v1/{tenant}/queries/{slug}
    ...
    - `refresh: true` (never false)
    - `querylimit: 500` (capped by toolkit)
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py`
  lines: 212-213
  symbol: `execute_sources`
  excerpt: |
    if src.transform is not None and src.transform.ref is not None:
        logger.warning("linked source %r: ref transform %s skipped in Python", key, src.transform.ref.name)
- path: `sdd/tasks/completed/TASK-3781-linked-surface-service.md`
  lines: -
  symbol: `LinkedSurfaceService.ensure_snapshot`
  excerpt: |
    | flagged_judgment_call | Coder followed the literal code skeleton: ensure_snapshot() does not re-call
    _assert_sources_allowed (only validate_for_persistence and refresh do) ...
- path: `git log --oneline -15 origin/dev -- <linked paths>`
  lines: -
  symbol: `-`
  excerpt: |
    ff066c3ae4 fix(a2ui-linked-surfaces): TASK-3796 review fixes
    2ff0666921 feat(a2ui-linked-surfaces): TASK-3796 — Docs — wire doc, a2ui-v1 extension table, dashboard reference §6.5...
    3b7fc2e665 feat(a2ui-linked-surfaces): TASK-3795 — stateful A2UISurface lane + FilterBar parrot_param branch
    00f79d3c90 feat(a2ui-linked-surfaces): TASK-3785 — engine-committed coder deliverable
    517ffd5bb5 feat(a2ui-linked-surfaces): TASK-3794 — QuerySource client, fetchSource, RefreshScheduler, loadRef
    5c8c987769 feat(a2ui-linked-surfaces): TASK-3793 — dsl.ts + conditions.ts against shared contract fixtures
    79b7bf5b45 feat(a2ui-linked-surfaces): TASK-3781 — LinkedSurfaceService
## Implications
- FEAT-610's example would be the first exercise against a REAL slug (`polestar_graduates_directory`); expect first-contact bugs in QuerySlugSource/tenant/dtype paths.
- Fix or note the wire-doc drift (route + querylimit) when documenting the example.
- The example should avoid `transform.ref` (JS-only, needs signed manifest + `PARROT_A2UI_MANIFEST_KEY`) and use inline `ops` or none.
