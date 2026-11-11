---
id: FG-002
query_id: Q061
type: git_log
intent: "How sidemantic was replaced: commits mentioning sidemantic / native compiler (the premise that made FEAT-713 standalone)."
executed_at: 2026-11-11T22:36:00Z
duration_ms: 700
parent_id: null
depth: 0
---

# FG-002 — sidemantic was dropped at the proposal stage (FEAT-704 rev2, 2026-10-25); the shipped package was built on the native sqlglot compiler

## Summary

Only two commit messages mention sidemantic or the native compiler, both SDD documents of 2026-10-25:
the FEAT-704 rev2 proposal ("semantic layer without sidemantic — native sqlglot compiler, SemaFlow for the
Rust phase, BSL reserved for joins") and the rev 0.3 spec. A pickaxe for the string `sidemantic` under
`packages/` finds a first implementation attempt dated 2026-10-19 (TASK-4463..4478, including a "distribution
skeleton (M1)") and one 2026-10-26 commit; the implementation that reached `dev` is the 2026-10-26 rebuild
whose compiler is `engines/native.py` (TASK-4468). There is no "remove sidemantic" commit: the dependency
was designed out, not migrated away. FEAT-713 was written on 2026-10-21, between the two attempts — which
is why it describes FEAT-704 as paused on an AGPL dependency.

## Citations

- commit: `5620103b03` — 2026-10-25 — sdd: research-grounded proposal for FEAT-704 rev2 — semantic layer without sidemantic (native sqlglot compiler, SemaFlow for Rust phase, BSL reserved for joins)
- commit: `d7856cd3db` — 2026-10-25 — sdd: add spec for FEAT-704 — semantic-layer (rev 0.3)
- commit: `dcec17c959` — 2026-10-19 — feat(semantic-layer): TASK-4463 — ai-parrot-semantic distribution skeleton (M1) (first attempt; contains the string `sidemantic`)
- commit: `88abeb21fe` — 2026-10-19 — feat(semantic-layer): TASK-4468 — engine-committed coder deliverable (first attempt)
- commit: `2ff0bad372` — 2026-10-19 — feat(semantic-layer): TASK-4478 — End-to-end governed-query security suite on DuckDB (M10 gate) (first attempt)
- commit: `b03bf5889e` — 2026-10-26 — feat(semantic-layer): TASK-4474 — Signed audit ledger and optional Postgres sink (M8) (pickaxe hit on `sidemantic` in the rebuild)
- commit: `2882b6dbf7` — 2026-10-26 — feat(semantic-layer): TASK-4468 — engine-committed coder deliverable
  files: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`,
  `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`

## Notes

- The pickaxe ran with `--all`; whether the 2026-10-19 commits are ancestors of `origin/dev` was not checked
  (git budget). They are the "paused" branch state the old FEAT-713 spec mirrored.
- The `b03bf5889e` hit means the string `sidemantic` was added or removed in a file of the audit task on
  2026-10-26; what remains in the tree today is for the codebase lane.
- [cross-lane: type=grep, intent=does the string 'sidemantic' still occur anywhere under packages/ai-parrot-semantic (comment, README, test) on dev]
