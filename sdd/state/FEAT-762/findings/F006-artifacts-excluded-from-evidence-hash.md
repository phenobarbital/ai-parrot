---
id: F006
query_id: Q009
type: read
intent: "confirm artifacts/logs/e2e/ is excluded from the source-identity hash and deterministic evidence tree only lists JSON/logs/JUnit/screenshots"
executed_at: 2026-10-27T19:10:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — `artifacts/logs/e2e/` is already excluded from the deterministic gate's source-identity hash; video is not yet part of deterministic evidence

## Summary

`sdd/specs/agentic-e2e-testing.spec.md`'s "Evidence Identity and Gate
Evaluation" section explicitly excludes `artifacts/logs/e2e/` from the
before/after source-identity hash the runner uses to fail a run on
unexpected mutation (`parrot.e2e.runner._verdict_status`'s
`source_unchanged` check). This means writing a `.webm` file under
`artifacts/logs/e2e/<run-id>/` during a run is safe — it will never trip
"source changed during execution" and force a spurious `FAIL`. Separately,
the spec's deterministic evidence tree
(`sdd/state/<FEAT-ID>/e2e/runs/<run-id>/`) is documented to "Store result
JSON, logs, JUnit XML and screenshots by relative path with SHA-256
hashes" — video/screencast is not currently a named evidence type there.

## Citations

- path: `sdd/specs/agentic-e2e-testing.spec.md`
  lines: 299-302
  symbol: "Evidence Identity and Gate Evaluation"
  excerpt: |
    Exclude only declared generated artifacts (`artifacts/logs/e2e/`, this
    feature's run evidence/candidates, pytest caches, bytecode) and SDD
    task bookkeeping (`sdd/tasks/`, `sdd/ledger/`).

- path: `sdd/specs/agentic-e2e-testing.spec.md`
  lines: 303-304 (paragraph immediately following, evidence tree)
  symbol: deterministic evidence tree description
  excerpt: |
    Persist immutable per-run evidence under
    `sdd/state/<FEAT-ID>/e2e/runs/<run-id>/` ... Store result JSON, logs,
    JUnit XML and screenshots by relative path with SHA-256 hashes.

- path: `sdd/specs/agentic-e2e-testing.spec.md`
  lines: 221-222
  symbol: "Process Lifecycle and Worktree Isolation"
  excerpt: |
    State is worktree-local `sdd/state/e2e/<run-id>.json`, mode 0600;
    sockets and private profiles reside in a mode-0700 run directory.
    Logs go to `artifacts/logs/e2e/<run-id>/`.

## Notes

This confirms the exploration-only placement the source request already
assumed is correct and low-risk: a screencast under `artifacts/logs/e2e/`
stays entirely outside both the hashed-source surface and the
deterministic evidence schema, so it cannot be mistaken for gate evidence
and cannot itself break a deterministic run by its mere presence. Wiring a
`.webm` into the *deterministic* evidence tree (SHA-256-hashed, listed in
`E2EVerdict`) would be a materially bigger, separate decision — this
proposal scopes to the exploration flow only (see §3 Non-Goals).
