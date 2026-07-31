# F007 — Recent activity: dev-loop is hot; CLI package is stable

- **Query**: Q011 (git_log)
- **Citations** (last 4 months on `packages/ai-parrot/src/parrot/flows/dev_loop/`):
  - FEAT-322 agent-host-protocol-session-state merged into dev (e5d23c782):
    TASK-1850..1856 — SessionHost, dual-publish shims, HITL gate
    integration, `view=state` multiplexer, REST commands, e2e tests.
  - FEAT-323 dev-loop-multiple-dev-agents: TASK-1859..1864 — dev-agent
    pool, sub-worktrees, scheduler.
- CLI package (`parrot/cli/`, 6 months): console-cli-agents (TASK-1136,
  FEAT-168 fixes), `parrot generate-keys`, wikitoolkit CLI — additive,
  low churn.
- **Implication**: build the CLI as a *client* of stable surfaces
  (`DevLoopRunner`, multiplexer envelopes, REST commands) rather than
  reaching into the actively-churning dispatcher internals.
