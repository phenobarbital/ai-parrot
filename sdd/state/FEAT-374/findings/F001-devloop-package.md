# F001 — dev-loop flow package location & shape

- **Query**: Q001/Q003 (wiki_query + dir page)
- **Wiki**: `dir:packages/ai-parrot/src/parrot/flows/dev_loop` (score 0.80)
- **Citations**:
  - `packages/ai-parrot/src/parrot/flows/dev_loop/` — 20 entries: `runner.py`,
    `models.py`, `dispatcher.py`, `streaming.py`, `session_state.py`,
    `commands.py`, `flow.py`, `definition.py`, `factories.py`, `nodes/`,
    `agent_pool.py`, `worktree_manager.py`, `webhook.py`, …
  - Eight-node AgentsFlow: `IntentClassifier → [BugIntake →] Research →
    Development → QA → DeploymentHandoff → Close` + `FailureHandler`
    (per `examples/dev_loop/README.md`).
- **Note**: code lives under the `packages/ai-parrot/src/parrot/` uv-workspace
  layout, NOT top-level `parrot/`. FEATs involved: 129, 132, 250, 253, 270,
  322, 323.
