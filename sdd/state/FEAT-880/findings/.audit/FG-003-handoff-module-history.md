---
id: FG-003
query_id: Q035
type: git_log
intent: "History of the hand-off module (why the sink direction exists)."
executed_at: 2026-11-11T22:05:20Z
duration_ms: 0
parent_id: null
depth: 0
---

# FG-003 — handoff.py was born in one task (TASK-4709, 2026-10-26) as a guarded sink with read-time authorization, then hardened twice the same day

## Summary

`handoff.py` has 4 commits, all on 2026-10-26. It was created by TASK-4709 "guarded dataset sink and read-time authorization" (216 lines + a reusable `sink_conformance.py` suite + `test_handoff_contract.py`, 544 insertions). Two same-day fixes followed: TASK-4479 review fixes, and a security fix adding a read-time usage recheck. The hand-off exists so governed semantic results can enter a DatasetManager **without** escaping governance: the sink is a guarded adapter and authorization is re-evaluated when the dataset is read, not only when it is published.

## Citations

- sha: `9986ac7c49`  date: 2026-10-26
  message: "feat(semantic-layer): TASK-4709 — guarded dataset sink and read-time authorization"
  files: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py` (+216), `packages/ai-parrot-semantic/tests/sink_conformance.py` (+126), `packages/ai-parrot-semantic/tests/test_handoff_contract.py` (+202)
- sha: `61dc2355f2`  date: 2026-10-26
  message: "style(semantic-layer): TASK-4709 — engine lint autofix"
  files: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py` (+4/-1)
- sha: `ef2de1e298`  date: 2026-10-26
  message: "fix(semantic-layer): TASK-4479 review fixes"
  files: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py` (+24/-6)
- sha: `c3e2049de4`  date: 2026-10-26
  message: "fix(semantic-layer): metric-only column masks, exact truncation, precise audit pbac, read-time usage recheck (issue:7e1d9700c5c1)"
  files: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py` (+14/-4)

## Notes

- Design precedent that bears directly on the governance question of this proposal: the project already decided that data leaving the semantic layer into a DatasetManager must stay guarded and be re-authorized at read time. An `add_semantic` source that compiles SQL and lets DatasetManager execute it ungoverned would contradict that precedent.
- `sink_conformance.py` is a reusable conformance suite — a candidate to reuse for whatever DatasetManager-side object holds semantic-sourced data.
- [cross-lane: type=read, intent=read packages/ai-parrot-semantic/tests/sink_conformance.py to list the guarantees a governed sink must satisfy]
