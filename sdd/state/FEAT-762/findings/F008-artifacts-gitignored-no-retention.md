---
id: F008
query_id: Q012
type: grep
intent: "check whether artifacts/ is gitignored (video files should never land in git) and whether any retention/cleanup policy exists"
executed_at: 2026-10-27T19:10:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F008 — `artifacts/` is wholly gitignored; no retention or size policy exists for `artifacts/logs/e2e/`

## Summary

`artifacts/` is excluded from git entirely (`.gitignore:286`), so a
`.webm` written there can never be accidentally committed. However, no
code, spec text, or script anywhere in the repo implements retention,
rotation, or a size cap for `artifacts/logs/e2e/<run-id>/` — logs/
screenshots there currently accumulate indefinitely across runs on
whatever machine executes them (dev workstation or CI runner). Video files
are one to two orders of magnitude larger than a single PNG screenshot or
a text log, so adding always-on recording without at least an opt-in
default materially changes this directory's disk-growth profile.

## Citations

- path: `.gitignore`
  lines: 286
  symbol: `artifacts/` ignore rule
  excerpt: |
    artifacts/

## Notes

No finding in F001-F007 surfaced any cleanup mechanism for this directory
(the CLI's `logs`/`down` commands only ever touch `sdd/state/e2e/*.json`
run-state files, never `artifacts/logs/e2e/`). This is a genuine gap this
proposal must explicitly scope — not assume existing infrastructure will
absorb it. See synthesis Constraint C-video-opt-in and §3 Non-Goals.
