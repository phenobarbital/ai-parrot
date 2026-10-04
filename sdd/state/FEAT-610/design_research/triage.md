# FEAT-610 design research triage

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Compose a rooted A2UI tree, not a flat widget list (architecture) | CONFIRM | Already designed as root Column; made reachability an explicit rule and test. | §3 M2, §4 |
| S2 | Keep the 17k-row grid outside the normal linked-frame path (architecture) | CONFIRM | Paging is example-only (`fetchPage` in `static/linked.js`), not a wire-contract change; admin DataTable stays bounded. | §3 M8 |
| S3 | Typed dashboard helper; validate bindings before execution (api) | CONFIRM | `DashboardWidget` model already typed; added component-type limit and explicit KPI aggregate column. | §3 M2 |
| S4 | Refresh at the source boundary, ownership from bindings (api) | CONFIRM | Key resolved from the widget binding; browser never sends slug/conditions; in-flight dedup per key. | §3 M5 |
| S5 | Do not parallelize refresh-all across dependent sources (risk) | CONFIRM | `refreshAll` keeps dependency order; `refreshSource` re-runs transform dependents in order. | §3 M5 |
| S6 | Update every resolver and lock the QuerySource version (risk) | CONFIRM | Verified `uv.lock:13047` pins 5.1.1; M3 now regenerates the lock with `uv lock` (exclusive). | §3 M3, Worktree Strategy |
| S7 | Treat grid.js as an unresolved asset dependency (risk) | CONFIRM | Real sha384 SRI computed from the pinned files; catalog placeholders not copied. Vendoring rejected by the user's no-new-library constraint. | §3 M8 |
| S8 | Contract tests for pie slice shape and dashboard reachability (testing) | CONFIRM | Pie test already in §4 (M4); reachability test added. | §4 |
| S9 | Move course-slug creation out of application startup (risk) | CONFIRM | Premise already met (seed is a separate `--yes` command); added a read-only startup slug check that degrades the widget. | §3 M7 |
| S10 | Exact example whitelist and a tracked-file assertion (risk) | CONFIRM | Added `git check-ignore` validation to the whitelist. | §3 M9 |
