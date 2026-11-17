---
id: FG-009
query_id: Q068
type: git_log
intent: "Recent activity on human-in-the-loop gates (parrot/human)."
executed_at: 2026-10-30T16:41:30Z
duration_ms: 250
parent_id: null
depth: 0
---

# FG-009 — parrot/human/: zero commits in 90 days; the HITL gate package is stable

## Summary

`git log --since=90.days.ago -- packages/ai-parrot/src/parrot/human/` returns nothing; the directory exists (actions/, channels/, cli_companion.py, escalation_intent.py, events.py, manager.py, models.py, node.py, tool.py — ~156 KB). The human-in-the-loop gate primitives (manager, node, models) have not moved in a quarter: a stage gate built on them inherits a settled API with no in-flight collisions.

## Citations

- path: `packages/ai-parrot/src/parrot/human/`
  lines: n/a
  symbol: package
  excerpt: |
    git log --no-merges --since=90.days.ago -- packages/ai-parrot/src/parrot/human/  → (no output)
    ls packages/ai-parrot/src/parrot/human/ → actions channels cli_companion.py escalation_intent.py events.py manager.py models.py node.py tool.py

## Notes

- The AHP session gates (TTL fail-closed) the source mentions live in `flows/dev_loop/session_state.py`, not here — two gate mechanisms exist (parrot/human HITL node vs dev_loop AHP session state).
- [cross-lane: type=read, intent=human/models.py + human/node.py — gate request/decision models; compare with dev_loop/session_state.py fail-closed TTL]
