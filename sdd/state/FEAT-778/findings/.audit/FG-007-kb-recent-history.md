---
id: FG-007
query_id: Q066
type: git_log
intent: "Recent activity on KB loading in bots (kb.py, abstract.py)."
executed_at: 2026-10-30T16:41:30Z
duration_ms: 250
parent_id: null
depth: 0
---

# FG-007 — bots/kb.py: zero commits in 180 days (file last modified 2026-06-15); the KB loader is dormant

## Summary

`git log --follow --since=180.days.ago -- packages/ai-parrot/src/parrot/bots/kb.py` returns no commits. The file exists (5,892 bytes, mtime 2026-06-15). Confirms the source's "Funcional, sin optimizar" assessment: nobody has touched the KB bot/loader in six months, so replacing it with a `KnowledgeResolver` has no in-flight work to collide with — but also no recent tests pinning its behaviour.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/kb.py`
  lines: n/a
  symbol: (whole file)
  excerpt: |
    git log --no-merges --follow --since=180.days.ago -- packages/ai-parrot/src/parrot/bots/kb.py  → (no output)
    ls -la → -rw-rw-r-- 5892 jun 15 01:22 packages/ai-parrot/src/parrot/bots/kb.py

## Notes

- Absence is the evidence here: low change velocity, low collision risk, likely low test coverage.
- [cross-lane: type=read, intent=bots/kb.py + AbstractBot.register_kb/configure_kb — what the current KB path loads, in what order, with what budget]
