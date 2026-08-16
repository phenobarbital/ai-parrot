# F006 — HITL gates + existing Rich CLI companion precedent

- **Query**: Q007/Q012 (wiki query + file page)
- **Citations**:
  - `packages/ai-parrot/src/parrot/human/cli_companion.py::HITLCompanion` —
    standalone Rich-rendered CLI process that connects to Redis, lists
    pending HITL interactions, renders questions (`CLIHumanChannel`), sends
    responses back via Redis queues. Direct stylistic/architectural
    precedent for interactive gate answering from a terminal.
  - FEAT-322 (`sdd/proposals/dev-loop-session-state-hitl.brainstorm.md`,
    tasks 1849-1856): dev-loop has blocking HITL **gates** (blocking
    `ManualCriterion` + deployment approval), gate TTLs
    (`runner.py::gate_ttl_for`), arbitration + 409 on double-resolve,
    reconnect/crash-rebuild e2e tests (TASK-1856).
  - `session_state.py` — AHP-style channels, actions & pure reducers;
    sequenced envelopes on `flow:{run_id}:actions`; terminal `Snapshot`
    persisted as run artifact.
- **Implication**: the CLI must render pending gates and resolve them
  (interactive y/n/comment), and can rebuild state after reconnect via
  `view="state"` (F004) — the hard problems are already solved server-side.
