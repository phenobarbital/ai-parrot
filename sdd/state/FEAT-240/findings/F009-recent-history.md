---
id: F009
query_id: Q012
type: git_log
intent: Recent development activity on graphindex paths
executed_at: 2026-06-16T00:00:00Z
duration_ms: 800
parent_id: null
depth: 0
---

# F009 — Intense recent activity; 3 features merged same day

## Summary

30 commits in last 60 days on graphindex paths. Three features merged on 2026-06-16:
FEAT-239 (OKF frontmatter projection), FEAT-215 (analytics insights), FEAT-217
(expanded retrieval). All are now stable on `dev`. The OKF shared module
(`parrot.knowledge.okf`) was extracted from PageIndex in FEAT-239 — this is the
module where RelationType.EXTENDS would be added.

## Citations

- commit: fd4b89ca2, 2026-06-16 — Merge feat-239-graphindex-frontmatter into dev
- commit: 6c9d34e44, 2026-06-16 — Merge feat-215-graphindex-analytics-insights into dev
- commit: 95bd7022b — Merge feat-217-graph-expanded-retrieval into dev

## Notes

Heavy recent activity means the codebase is fresh and patterns are well-established.
The FEAT-239 merge is especially relevant — it just extended both RelationType and
ConceptType enums, establishing the exact pattern this feature would follow.
