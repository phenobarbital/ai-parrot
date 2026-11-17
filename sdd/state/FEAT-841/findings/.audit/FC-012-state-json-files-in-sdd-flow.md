---
id: FC-012
query_id: Q027
type: grep
intent: "Which state.json files exist in the SDD flow and what each holds (proposal state vs worker/autopilot state)."
executed_at: 2026-11-07T01:23:30Z
duration_ms: 1000
parent_id: null
depth: 0
---

# FC-012 — Two state.json files exist: sdd/state/<FEAT-ID>/state.json (proposal research only) and .autopilot/state.json (autopilot pipeline); the worker has none

## Summary

Grep `state\.json` across `.claude/commands`, `.claude/agents`, `parrot/sdd`, `parrot/flows/dev_loop`: all hits are either `/sdd-proposal` (the research state under `sdd/state/<FEAT-ID>/state.json`, schema `sdd/templates/state.schema.json`) or `sdd-autopilot` (`.autopilot/state.json`, a per-pipeline stage tracker with `stages.worker.status`, etc.). No `state.json` is read or written by `sdd-worker`, `sdd-start`, `close_task` or `sdd-done`. The only feature-execution state is the per-spec index `sdd/tasks/index/<slug>.json` (FC-005, FC-020). Therefore the user's "El estado pasa a AWAITING_VERDICT en state.json" must map onto either (a) a new field block in the per-spec index header (brainstorm's choice), or (b) a new worktree/ledger-held record — `sdd/state/<FEAT-ID>/state.json` is a research artifact with a closed schema (`additionalProperties: false`) and must not carry execution state.

## Citations

- path: `.claude/commands/sdd-proposal.md`
  lines: 92-92
  symbol: null
  excerpt: |
    Initialize `${STATE_DIR}/state.json` per the schema in

- path: `.claude/agents/sdd-autopilot.md`
  lines: 471-473
  symbol: null
  excerpt: |
    .autopilot/
    ├── state.json              # Current pipeline state

- path: `.claude/agents/sdd-autopilot.md`
  lines: 484-495
  symbol: null
  excerpt: |
    **`state.json` schema:**
    {
      "feature_id": "FEAT-071",
      "jira_key": "PROJ-123",
      "started_at": "2026-04-14T10:30:00Z",
      "stages": {
        "worker": {
          "status": "completed",

- path: `sdd/templates/state.schema.json`
  lines: 1-5
  symbol: null
  excerpt: |
    "title": "SDDProposalState",
    "description": "Persistent state for /sdd-proposal runs. One file per FEAT-ID at sdd/state/<FEAT-ID>/state.json. Enables resumability, audit, and budget enforcement.",

## Notes

- Zero hits in `packages/ai-parrot/src/parrot/sdd/` and `parrot/flows/dev_loop/` outside the `_assets` copy of sdd-proposal.md.
- `sdd/state/<FEAT-ID>/` is also where the E2E plan lives (`e2e-plan.md`, FC-002) — the directory is per-feature but its `state.json` is proposal-scoped.
