# F002 — DevLoopRunner is the complete programmatic surface a CLI needs

- **Query**: Q008 (wiki file page `file:.../dev_loop/runner.py`)
- **Citations**:
  - `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py::DevLoopRunner`
    - `run(brief)` — execute one dev-loop run (respects `FLOW_MAX_CONCURRENT_RUNS`)
    - `run_revision(brief)` — revision-mode run (FEAT-250 G6)
    - `resolve_gate(run_id, gate_id, resolution, resolved_by, comment, origin)` — HITL gate write
    - `cancel_run(run_id, requested_by)` — terminal-sticky cancel
    - `get_host(run_id)` — live `SessionHost` per run
    - `registry_state()` — root-channel run catalogue (`parrot-root://`)
    - `active_runs()` / `is_active(run_id)`
  - Runner mints `run_id`, seeds `FlowContext.shared_data['work_brief']`,
    binds `FlowEventPublisher` → `flow:{run_id}:flow`, owns one
    `SessionHost` per run (AHP-style, FEAT-322), gate-expiry sweep.
- **Implication**: an embedded CLI can drive everything through
  `DevLoopRunner` alone — no HTTP layer required in-process.
