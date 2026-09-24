---
feature_id: FEAT-581
spec_path: sdd/specs/agentic-e2e-testing.spec.md
policy: required
targets: {}
scenarios:
  - id: live-google-mcp-agent-tool
    tier: live
    target_ids: []
    required: true
    node_ids:
      - packages/ai-parrot-server/tests/e2e/test_mcp_agent_live.py::test_live_google_tool_and_schema
    timeout_s: 150
    assertions:
      - "A real, budgeted live Google MCP-agent call invokes and records the observable synthetic fixture tool effect and schema, never judged from prose"
budget:
  model: google:gemini-2.5-flash-lite
  max_calls: 4
  max_output_tokens: 512
  max_request_bytes: 16384
  timeout_s: 90
run_timeout_s: 300
---

# Optional live E2E plan — FEAT-581

This is the **dispatch-only** live CI plan invoked by the separate `live`
job in `.github/workflows/e2e.yml`: it never runs on the `0 3 * * *`
deterministic cron, only on an explicit `workflow_dispatch` with
`run_live: true`, and only after the deterministic job has already passed.

`policy: required` here is deliberate and scoped to *this dedicated plan
only* — not the feature's overall policy, and not the deterministic plan
above (which declares no live scenario at all). Spec §3 M9: "Missing live
secret is BLOCKED when the live job was explicitly requested." Marking the
one live scenario `required: true` is exactly what makes that true: the
runner's own live-tier gate (`parrot.e2e.runner._live_enabled()`) always
blocks a `live` scenario when `PARROT_TEST_REAL_LLM=1` and a real
`GOOGLE_API_KEY` are not both present, and a `required` scenario left
`blocked` makes the whole run's verdict `BLOCKED` (exit code 3) — an
explicit, visible outcome distinct from a false `PASS` and distinct from
the deterministic gate's own separate `FAIL`/`PASS`/`BLOCKED` verdict.

`live-google-mcp-agent-tool`'s node ID is frozen by TASK-3540; renaming it
requires updating this plan (and `tests/sdd_scripts/test_e2e_ci_plans.py`)
in the same change. Requires `GOOGLE_API_KEY` (from a repository secret,
never a fork-visible pull-request context — this workflow has no
`pull_request` trigger) plus `PARROT_TEST_E2E=1`/`PARROT_TEST_REAL_LLM=1`.
The aggregate request/byte/output/deadline budget above bounds every
generation attempt across the run (spec §2 "Live Provider Budget"); no
Groq or cross-provider fallback is used or required.
