---
id: F015
query_id: Q018
type: grep
intent: Where codex review artifacts land today and whether that path is tracked
executed_at: 2026-09-10T01:00:00Z
duration_ms: 200
parent_id: F006
depth: 1
---

# F015 — artifacts/ is gitignored; the review policy's codex output path is therefore unversioned

## Summary

The adversarial-review prose writes Codex output to `artifacts/reviews/<task>-codex.txt` (F006), but `.gitignore` line 283 ignores `artifacts/` wholesale, so those transcripts are never committed or visible to worktrees. `/sdd-proposal` by contrast persists research under `sdd/state/<FEAT-ID>/` and commits it (this run is an instance). A design-research pass whose ideas must be auditable in the spec should persist its raw Codex output under `sdd/state/<FEAT-ID>/`, not `artifacts/`.

## Citations

- path: `.gitignore`
  lines: 283
  excerpt: |
    artifacts/

- path: `artifacts/`
  lines: 0
  symbol: directory exists locally (untracked)
  excerpt: |
    artifacts/reviews/PR-4028-NAV-8036-review.md  (plus a2ui/, ast/, benchmarks/, ...)

- path: `.claude/commands/sdd-proposal.md`
  lines: 393-399
  symbol: §9a Commit the proposal
  excerpt: |
    git add sdd/proposals/<slug>.proposal.md sdd/state/<FEAT-ID>/
