---
id: FG-001
query_id: Q060
type: git_log
intent: "History of the semantic package: when it landed, what changed after the FEAT-704 merge."
executed_at: 2026-11-11T22:36:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FG-001 — ai-parrot-semantic landed on dev 2026-10-27 (PR #1821); only FEAT-769 examples and fixes since

## Summary

The package on `dev` was built in one day (2026-10-26, FEAT-704 tasks TASK-4463..4481 and TASK-4702..4710)
and merged with PR #1821 on 2026-10-27. Follow-ups: PR #1824 (CI registration), PR #1841 (packaging
test), PR #1865 (`ci/release-semantic`), and FEAT-769 `semantic-layer-example` (PR #1877, 2026-10-30).
After 2026-10-30 the only commits under `packages/ai-parrot-semantic/` are release bumps (v2.0.0 → v2.1.3)
and a docs move (TASK-5172); no source change. The skeleton, CI job and release entry that the old
FEAT-713 M1 wanted to create were added by TASK-4463.

## Citations

- commit: `f098303029` — 2026-10-26 — feat(semantic-layer): TASK-4463 — engine-committed coder deliverable
  files: `packages/ai-parrot-semantic/pyproject.toml`, `packages/ai-parrot-semantic/README.md`,
  `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py`,
  `packages/ai-parrot-semantic/src/parrot/semantic/version.py`,
  `packages/ai-parrot-semantic/tests/test_packaging.py`, `.github/workflows/ci.yml`, `pyproject.toml`,
  `scripts/release.py`, `ruff.toml`, `uv.lock`
- commit: `2882b6dbf7` — 2026-10-26 — feat(semantic-layer): TASK-4468 — engine-committed coder deliverable
  files: `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`,
  `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`,
  `packages/ai-parrot-semantic/tests/test_native_compiler.py`
- commit: `9986ac7c49` — 2026-10-26 — feat(semantic-layer): TASK-4709 — guarded dataset sink and read-time authorization
- commit: `b5a9386bc9` — 2026-10-26 — feat(semantic-layer): TASK-4479 — Security-gated raw SQL and guarded hand-off tools (M10b)
- commit: `0e916003e8` — 2026-10-26 — feat(semantic-layer): TASK-4706 — join-grain safety, filtered and derived metrics
- commit: `b2b290089b` — 2026-10-27 — Merge pull request #1821 from phenobarbital/feat-FEAT-704-semantic-layer
- commit: `70bd22e5eb` — 2026-10-27 — Merge pull request #1824 from phenobarbital/fix-feat-704-ci-registration
- commit: `7c0c64bb60` — 2026-10-27 — fix(ci): remove conflicting --package flag from semantic-layer sync
  files: `.github/workflows/ci.yml`
- commit: `8aa1a0d312` — 2026-10-28 — Merge pull request #1841 from phenobarbital/fix-semantic-packaging-test
- commit: `07adb66f01` — 2026-10-28 — fix(semantic-layer): unpin version and update CI sync assertion in packaging test
  files: `packages/ai-parrot-semantic/tests/test_packaging.py`
- commit: `112216095a` — 2026-10-29 — Merge pull request #1865 from phenobarbital/ci/release-semantic
- commit: `f5a338013a` — 2026-10-30 — Merge pull request #1877 from phenobarbital/feat-FEAT-769-semantic-layer-example
- commit: `ef2072066a` — 2026-10-30 — feat(semantic-layer-example): TASK-4883 — governed joins agent (last feature commit in the package)
- commit: `f8fce7a73a` — 2026-11-10 — chore: release v2.1.3 (latest commit touching the package; version bump only)

## Notes

- The old spec pinned `version.py` to `1.3.0` (AC2); the package has since been released up to v2.1.3 and
  `07adb66f01` "unpinned" the version in the packaging test — AC2 cannot hold as written.
- Six post-merge review fixes landed the same day (`0ac263168b`, `32a7762eee`, `c3e2049de4`, `ae7e21f16a`,
  `ef85c50353`, `9a953146d2`), each closing a ledger issue.
- [cross-lane: type=read, intent=confirm in .github/workflows/ci.yml and scripts/release.py what TASK-4463 / PR #1824 / PR #1865 registered for ai-parrot-semantic]
