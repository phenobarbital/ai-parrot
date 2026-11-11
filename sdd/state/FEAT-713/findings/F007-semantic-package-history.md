---
id: F007
query_id: Q060
type: git_log
intent: "History of the semantic package: when it landed, what changed after the FEAT-704 merge."
executed_at: 2026-11-11T22:36:00Z
duration_ms: 900
parent_id: null
depth: 0
lane_ids: [FG-001]
---

# F007 — ai-parrot-semantic landed on dev 2026-10-27 (PR #1821); only FEAT-769 examples and fixes since

## Summary

The package on `dev` was built in one day (2026-10-26, FEAT-704 tasks TASK-4463..4481 and TASK-4702..4710)
and merged with PR #1821 on 2026-10-27. Follow-ups: PR #1824 (CI registration), PR #1841 (packaging
test), PR #1865 (`ci/release-semantic`), and FEAT-769 `semantic-layer-example` (PR #1877, 2026-10-30).
After 2026-10-30 the only commits under `packages/ai-parrot-semantic/` are release bumps (v2.0.0 → v2.1.3)
and a docs move (TASK-5172); no source change. The skeleton, CI job and release entry that the old
FEAT-713 M1 wanted to create were added by TASK-4463.

## Citations



## Notes

- The old spec pinned `version.py` to `1.3.0` (AC2); the package has since been released up to v2.1.3 and
  `07adb66f01` "unpinned" the version in the packaging test — AC2 cannot hold as written.
- Six post-merge review fixes landed the same day (`0ac263168b`, `32a7762eee`, `c3e2049de4`, `ae7e21f16a`,
  `ef85c50353`, `9a953146d2`), each closing a ledger issue.
- [cross-lane: type=read, intent=confirm in .github/workflows/ci.yml and scripts/release.py what TASK-4463 / PR #1824 / PR #1865 registered for ai-parrot-semantic]
