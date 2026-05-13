---
kind: inline
jira_key: null
fetched_at: "2026-05-10T20:00:00Z"
summary_oneline: "Final migration phase: move OrchestratorAgent and A2AOrchestrator to flows, remove bots/orchestration"
---

# Source

With the feature `flow-primitives` (FEAT-134) we started the migration from
`orchestration` to `flows` — all artifacts like AgentCrew have been migrated.

This spec covers the **final phase**: moving the `a2a_orchestrator` and
`OrchestratorAgent` to `parrot.bots.flows.agents`, and because `AgentCrew` was
already migrated, removing the `bots/orchestration` folder completely.
