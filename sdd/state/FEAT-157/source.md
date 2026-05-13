---
kind: inline
jira_key: null
fetched_at: 2026-05-11T00:00:00Z
summary_oneline: Add on_complete and on_error hooks to AgentCrew for post-execution callbacks
---

# AgentCrew Hooks

Add "on_complete" hooks to AgentCrew — a list of registered functions that can be
called when an AgentCrew finishes execution. A potential "on_error" hook can be
added as well.

## Intent

Allow users to register callback functions that fire when AgentCrew execution
completes (successfully or with errors), enabling logging, notifications,
cleanup, or chaining of post-execution actions.
