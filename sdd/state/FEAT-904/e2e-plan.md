---
schema_version: 1
feature_id: FEAT-904
spec_path: sdd/specs/user-memory-recall-e2e.spec.md
policy: optional
targets: {}
scenarios:
  - id: agent-memory-cross-session-live
    tier: live
    target_ids: []
    required: true
    node_ids:
      - packages/ai-parrot/tests/e2e/test_agent_memory_live.py::test_agent_memory_cross_session_live
    timeout_s: 600
    prerequisites: []
    assertions:
      - Session A history and durable records persist after cleanup.
      - A fresh agent and session recall both profile and an earlier interaction.
      - The answer reflects the short-response preference.
budget:
  model: google:gemini-3-flash-preview
  max_calls: 24
  max_output_tokens: 2048
  max_request_bytes: 131072
  timeout_s: 60
run_timeout_s: 900
---

# FEAT-904 live cross-session proof

Host-only opt-in execution uses Redis database 15 with a unique prefix and a temporary SQLite file.
Both sessions and all extraction clients share one generation budget.
Optional policy controls invocation; the required node must pass setup, call and teardown.
Inspect the required node outcome, not only the aggregate run status.
