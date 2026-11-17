---
id: F038
query_id: Q067
type: git_log
intent: "Recent activity on bookstore (catalog, carding, wiki export)."
executed_at: 2026-10-30T16:41:30Z
duration_ms: 300
parent_id: null
depth: 0
merged_from: [FG-008-bookstore-recent-history]
---

# F038 — knowledge/bookstore/: 10 commits in 90 days; re-index identity hotfixes (2026-09-30) + atomic-swap reindex (2026-10-01) — card identity/edit preservation is a solved concern

## Summary

10 commits (Jesus Lara, Jesus), 2026-09-06 → 2026-10-01. Four HOTFIX-bookstore-reindex-identity-1..4 commits on 2026-09-30 (path re-index identity + graph invalidation, title-collision guard, `update_card` + bookstore update, preserve manual card edits on in-place re-index — `library.py`), then FEAT bookstore-reindex-atomic-swap (TASK-3888/3889/3890 + non-blocking sweep, cancel-safe staging). Earlier TASK-3032 (contracts-card-ontology) added an async DOCX conversion helper. The bookstore already has a notion of document identity across re-index and card update semantics — the base for the source's "id + sha256 + source_revision → invalidate summary" DocumentKB contract, though whether a digest field exists is for the codebase lane.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py`
  lines: n/a
  symbol: card update / re-index
  excerpt: |
    5f29b8320d 2026-09-30 Jesus Lara fix(bookstore): HOTFIX-bookstore-reindex-identity-4 — preserve manual card edits on in-place re-index
     .../src/parrot/knowledge/bookstore/library.py | 17 ++++++--
     .../tests/knowledge/bookstore/test_library.py | 49 ++++++++++
    55ee7922f5 2026-09-30 fix(bookstore): HOTFIX-bookstore-reindex-identity-1 — path re-index identity + graph invalidation
    4340d14dd1 2026-09-30 fix(bookstore): HOTFIX-bookstore-reindex-identity-2 — title collision guard
    c3f716342b 2026-09-30 feat(bookstore): HOTFIX-bookstore-reindex-identity-3 — update_card + bookstore update

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/`
  lines: n/a
  symbol: commits
  excerpt: |
    caa7933263 2026-10-01 fix(bookstore-reindex-atomic-swap): non-blocking sweep, cancel-safe staging cleanup (issue:326280b50ee9)
    157f092cb4/8792343505 2026-10-01 feat(bookstore-reindex-atomic-swap): TASK-3888/3889
    34b7d2be64 2026-10-01 feat(bookstore-reindex-atomic-swap): TASK-3890 — CLI flags to clear authors and topics
    ae656276c8 2026-09-09 feat(contracts-card-ontology): TASK-3032 — public asynchronous DOCX conversion helper

## Notes

- [cross-lane: type=grep, intent=bookstore/models.py + library.py — is there a content hash / sha256 / revision on cards, and are tags/topics filterable for the expert scope]
