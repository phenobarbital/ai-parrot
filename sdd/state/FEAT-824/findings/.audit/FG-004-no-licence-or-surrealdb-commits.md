---
id: FG-004
query_id: Q104
type: git_log
intent: "Any commit recording the ArangoDB licence decision or a prior removal attempt"
executed_at: 2026-11-06T13:39:00Z
duration_ms: 600
parent_id: null
depth: 0
---

# FG-004 — No commit on origin/dev records the ArangoDB licence decision, a removal attempt, or any SurrealDB work

## Summary

`git log origin/dev -i -E --grep="BUSL|licen[sc]|remove arango|drop arango|surreal"` returns 9
commits, **none** about ArangoDB licensing, ArangoDB removal or SurrealDB. The hits are unrelated
uses of "license" (PEP 639 metadata migration, a vendored-map-assets licence manifest, a README
licence section) or incidental body matches. The licence-driven removal is therefore a decision
that so far exists only in the untracked draft
`sdd/proposals/SPEC_ontology_backend_postgres_surrealdb.md`; there is no prior removal attempt to
build on and no SurrealDB code or dependency in history. `git branch -r` also lists no
`surreal*` branch (see FG-005).

## Citations

- commit: `d4f2fa6202` — 2026-06-08 — Jesus Lara — `build: migrate package metadata to PEP 639 and fix redis extra`
  note: only licence-related packaging commit; relevant because the draft's motivation is MIT-distribution compatibility

- commit: `aaaf6d4d46` — 2025-10-07 — phenobarbital — `Revise license and documentation sections in README`
  path: `README.md`

- commit: `dc9d86ec07` — 2026-09-03 — Jesus — `feat(interactive-html-map-tailwind): TASK-2785 — Vendor offline map assets + license manifest`
  note: unrelated (vendored map assets)

- commit: `dc1c847cb8` — 2026-08-23 — Jesus Lara — `sdd: research-grounded proposal for FEAT-449 — legal LLM wiki (Spanish + EU law)`
  note: matched on body text only; unrelated to the ArangoDB decision

- absent: no commit subject or body on `origin/dev` matches `BUSL`, `remove arango`, `drop arango` or `surreal` in an ArangoDB/SurrealDB sense (remaining hits: `dfb3493238`, `6a8a23dd1d`, `345871903c`, `e499f17734`, `c01257b2dd` — dependency bumps, examples, sdd-insight, embeddings catalog)

## Notes

- The claim "ArangoDB Community moved to BUSL-1.1 + Community License (100 GiB cap, no commercial
  production use)" in the draft §1 is **not verifiable from the repository**; it is an external
  fact the proposal must cite as user-supplied, not as codebase evidence.
- Same for the draft's SurrealDB claims (3.3.x server, SDK 3.x in beta, BSL 1.1): no in-repo
  evidence either way.
- `[cross-lane: type=wiki_query, intent=any recorded decision/ADR page about the ArangoDB licence or graph-backend choice (the wiki decision plane, not git)]`
