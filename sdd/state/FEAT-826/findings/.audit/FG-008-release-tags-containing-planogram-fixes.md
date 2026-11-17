---
id: FG-008
query_id: Q031
type: git_log
intent: "Which release tags contain the planogram-cycle fixes the Epson endcap rows depend on."
executed_at: 2026-11-06T16:04:38Z
duration_ms: 500
parent_id: FG-003
depth: 1
---

# FG-008 — Release tags containing the planogram-cycle fixes

## Summary

`git tag --contains e168ddc9f2 --sort=creatordate` lists 8 tags, the earliest being **1.2.3 (2026-10-16)**,
then 1.2.4 (2026-10-22), 1.2.5 (2026-10-27), …; so every 2026-10-15 fix (text features, appearance rule,
out-of-vocabulary coercion — all ancestors of that commit's line on main per FG-003) shipped in release
1.2.3, five days before the ticket was reopened. The optional-zone scoring fix `dda9a3ed2a` is first tagged
in **1.2.5 (2026-10-27)** and is also in 1.2.6 (2026-10-29), 2.0.0 (2026-11-03) and 2.1.0 (2026-11-05).
Release 1.2.4 was cut on 2026-10-22, the day after the reopen, and does not contain `dda9a3ed2a`.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  commit: `e168ddc9f2` 2026-10-15 — tags (earliest 4 of 8): `1.2.3` 2026-10-16, `1.2.4` 2026-10-22,
  `task-4664-parallel-impl` 2026-10-23, `1.2.5` 2026-10-27
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py`
  commit: `dda9a3ed2a` 2026-10-27 — tags (earliest 4 of 5): `1.2.5` 2026-10-27, `1.2.6` 2026-10-29,
  `2.0.0` 2026-11-03, `2.1.0` 2026-11-05

## Notes

- Tag dates are tag creator dates. `1.2.3` containing `e168ddc9f2` was verified; that it also contains
  `dd059bfa79` and `b1d8d506dc` is inferred from the same-day linear history on `dev` (FG-001 order), not
  checked tag by tag.
- A worker on a release older than 1.2.5 scores a promotional display with an optional, unbound zone as a
  failure (see the hunk in FG-001). Which release the Epson360 FlowTask worker runs is unknown from git.
- Whether these tags map 1:1 to published `ai-parrot-pipelines` versions on PyPI was not checked here.
