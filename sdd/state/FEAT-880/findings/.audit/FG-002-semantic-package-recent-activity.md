---
id: FG-002
query_id: Q034
type: git_log
intent: "Recent semantic package activity since FEAT-704/769."
executed_at: 2026-11-11T22:05:20Z
duration_ms: 0
parent_id: null
depth: 0
---

# FG-002 — Semantic package is feature-frozen since 2026-10-30: only release bumps and a docs move afterwards

## Summary

`git log --since=45.days.ago -- packages/ai-parrot-semantic` shows the FEAT-704 core landing and review fixes (2026-10-26/27), the FEAT-769 example tasks TASK-4877..4883 (2026-10-29/30), and after that only `chore: release` bumps (v1.2.5 → v2.1.3) plus the wiki docs move (TASK-5172, 2026-11-05). No source change to `parrot.semantic` in the last ~12 days and no in-flight feature on `dev`. The API a DatasetManager source would consume (loader, compiler, pipeline) is therefore stable to build against.

## Citations

- sha: `f8fce7a73a`  date: 2026-11-10  message: "chore: release v2.1.3"  path: `packages/ai-parrot-semantic`
- sha: `321c9883a3`  date: 2026-11-05  message: "feat(github-wiki-technical-reference): TASK-5172 — move technical docs to wiki/ (275 pages), nav/link/consumer rewrites, translations"  path: `packages/ai-parrot-semantic`
- sha: `cf11f9faa6`  date: 2026-11-03  message: "chore: release v2.0.0"  path: `packages/ai-parrot-semantic`
- sha: `ef2072066a`  date: 2026-10-30  message: "feat(semantic-layer-example): TASK-4883 — governed joins agent"  path: `packages/ai-parrot-semantic`
- sha: `d411042625`  date: 2026-10-29  message: "feat(semantic-layer-example): TASK-4878 — engine-committed coder deliverable"  path: `packages/ai-parrot-semantic`
- sha: `07adb66f01`  date: 2026-10-28  message: "fix(semantic-layer): unpin version and update CI sync assertion in packaging test"  path: `packages/ai-parrot-semantic`
- sha: `9a953146d2`  date: 2026-10-27  message: "fix(semantic-layer): test the doc's own YAML/JSON blocks and align its model format (issue:d01c24f18770)"  path: `packages/ai-parrot-semantic`
- sha: `ef85c50353`  date: 2026-10-27  message: "fix(semantic-layer): wire real PBAC guard in agent example, scope env and owner checks (issue:f0da823294fb)"  path: `packages/ai-parrot-semantic`

## Notes

- `07adb66f01` + the release commits show the package has a packaging test that asserts version sync with the workspace (`test_packaging.py`); a new cross-package dependency (core → semantic or semantic → core) will touch that surface.
- The semantic docs now live under `wiki/` (TASK-5172), not `docs/tools/semantic-layer.md`.
