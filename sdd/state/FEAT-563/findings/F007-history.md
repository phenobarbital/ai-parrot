---
id: F007
query_id: Q006
type: git_log
intent: Multi-store code predates the recent dependency changes
executed_at: 2026-09-09T23:24:11.921Z
parent_id: null
depth: 1
---

# F007 — Multi-store code predates the recent dependency changes

## Summary

No commits touched the inspected multi-store directory in the last 30 days. Latest relevant commits: ba5e6fa4ea (2026-07-27, Jesus, TASK-1937 registry swap); a1842f60e7 (2026-07-27, Jesus, TASK-1937 clean-break migration); f04772da5e (2026-07-27, Jesus, TASK-1936 toolkit core). Satellite manifest commits within 30 days: 770ae94943 (2026-08-20, Jesus, changes for support codex-based agents); f1dda8ffd7 (2026-08-17, Jesus, new version of google-genai with support for 3.6 and 3.7 models).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/multistoresearch`
  lines: git history
  symbol: `MultiStoreSearchToolkit`
  excerpt: |
    f04772da5e 2026-07-27

- path: `packages/ai-parrot-embeddings/pyproject.toml`
  lines: git history
  symbol: `project.optional-dependencies`
  excerpt: |
    770ae94943 2026-08-20

## Notes

History supports reusing the established adapter surface; it does not establish runtime compatibility with LanceDB.
