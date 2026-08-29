---
id: F006
query_id: Q007
type: git_log
intent: Recent dependency edits on core pyproject
executed_at: 2026-08-28T20:15:30Z
depth: 0
---
# F006 — Recent history: extras were patched before (networkx/pymupdf), rustworkx never promoted

## Summary
8 recent commits touch `packages/ai-parrot/pyproject.toml`. `e7f1dfccf fix(deps): add networkx and pymupdf to wiki/graphindex extras` is a precedent for exactly this class of bug (missing wiki dep), fixed by editing extras rather than core. Latest: `b07e7fbea chore: bump flowtask>=5.12.14, remove gemma4 extra, clean resolver overrides`.

## Citations
- path: `packages/ai-parrot/pyproject.toml`
  symbol: git log
  excerpt: |
    b07e7fbea chore: bump flowtask>=5.12.14, remove gemma4 extra, clean resolver overrides
    cf46342fd fix issue with flowtask dependency
    e7f1dfccf fix(deps): add networkx and pymupdf to wiki/graphindex extras
    880eff184 feat(jira-extractor-llmwiki): TASK-2406 — jira host extra + operator runbook
