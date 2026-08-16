# F006 — Recent dev_loop activity (query Q012)

**Type**: git_log (3 months, 25 commits sampled)

- FEAT-322 agent-host-protocol-session-state (merged): SessionHost, HITL gates, REST command endpoints — dispatchers now thread `session_host`.
- FEAT-323 dev-loop-multiple-dev-agents (merged): DevAgentPool, agent_builder, TaskScheduler, SubWorktreeManager.
- FEAT-270 new-codereviewers (merged): Claude/Codex/Gemini review dispatchers + QANode review-fix-rerun loop + `28d88b9eb fix(code-review): resolve 10 correctness bugs`.
- `5982096fb` MoonshotCodeDispatcher added recently — the dispatcher-per-backend pattern is actively growing.
- Uncommitted in main checkout: `parrot/cli/devloop/bootstrap.py`, `parrot/cli/wizard.py`, `parrot/conf.py` (in-flight FEAT-374 devloop CLI console work) — a new feature branch must rebase on current dev and avoid touching those files' in-flight edits.

**Implication**: subsystem is hot; any FEAT-375 work should be additive (new profile/registry entries + new brief files) rather than reworking dispatcher internals.
