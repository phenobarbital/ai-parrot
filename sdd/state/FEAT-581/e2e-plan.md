---
schema_version: 1
feature_id: FEAT-581
spec_path: sdd/specs/agentic-e2e-testing.spec.md
policy: required
targets:
  http:
    kind: mcp-toolkit
    profile: minimal
    startup_timeout_s: 60
    shutdown_timeout_s: 10
    options: {}
  stdio:
    kind: mcp-stdio
    profile: minimal
    startup_timeout_s: 60
    shutdown_timeout_s: 10
    options: {}
  app:
    kind: botmanager
    profile: minimal
    startup_timeout_s: 60
    shutdown_timeout_s: 10
    options: {}
budget:
  model: google:gemini-2.5-flash-lite
  max_calls: 4
  max_output_tokens: 512
  max_request_bytes: 16384
  timeout_s: 60
run_timeout_s: 600
scenarios:
- id: http-cli-stays-alive-and-stops
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_mcp_http.py::test_http_cli_stays_alive_and_stops
  timeout_s: 60
  prerequisites: []
  assertions:
  - Create suite-local opt-in fixtures before any spawn; use existing markers and
    explicit supervisor context.
  - Add real HTTP initialize/list/tool-effect checks and persistent stdio JSON purity/EOF
    behavior.
- id: stdio-tool-roundtrip-and-eof
  tier: deterministic
  target_ids:
  - stdio
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py::test_stdio_tool_roundtrip_and_eof
  timeout_s: 60
  prerequisites: []
  assertions:
  - Create suite-local opt-in fixtures before any spawn; use existing markers and
    explicit supervisor context.
  - Add real HTTP initialize/list/tool-effect checks and persistent stdio JSON purity/EOF
    behavior.
- id: authenticated-minimal-profile
  tier: deterministic
  target_ids:
  - app
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_authenticated_minimal_profile
  timeout_s: 60
  prerequisites: []
  assertions:
  - Add private-Redis bootstrap cookie round-trip, anonymous/invalid denial and selected
    real API assertion.
  - Test minimal boot with a controlled empty tokenizer cache and outbound network
    disabled except fixture loopback.
- id: botmanager-offline-boot
  tier: deterministic
  target_ids:
  - app
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_botmanager_offline_boot
  timeout_s: 60
  prerequisites: []
  assertions:
  - Add private-Redis bootstrap cookie round-trip, anonymous/invalid denial and selected
    real API assertion.
  - Test minimal boot with a controlled empty tokenizer cache and outbound network
    disabled except fixture loopback.
- id: controller-and-supervisor-death
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_controller_and_supervisor_death
  timeout_s: 90
  prerequisites: []
  assertions:
  - Kill controller and supervisor separately at deterministic registration barriers
    and after readiness; verify watchdog cleanup.
  - Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained
    unresolved cleanup failure.
- id: timeout-and-grandchild-teardown
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_timeout_and_grandchild_teardown
  timeout_s: 90
  prerequisites: []
  assertions:
  - Kill controller and supervisor separately at deterministic registration barriers
    and after readiness; verify watchdog cleanup.
  - Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained
    unresolved cleanup failure.
- id: two-worktrees-independent
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_two_worktrees_independent
  timeout_s: 90
  prerequisites: []
  assertions:
  - Kill controller and supervisor separately at deterministic registration barriers
    and after readiness; verify watchdog cleanup.
  - Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained
    unresolved cleanup failure.
- id: wrong-checkout-cannot-pass
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_wrong_checkout_cannot_pass
  timeout_s: 90
  prerequisites: []
  assertions:
  - Kill controller and supervisor separately at deterministic registration barriers
    and after readiness; verify watchdog cleanup.
  - Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained
    unresolved cleanup failure.
- id: required-evidence-rejections
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_evidence.py::test_required_evidence_rejections
  timeout_s: 60
  prerequisites: []
  assertions:
  - 'Adopt the decomposition-generated canonical plan embedded below; validate all
    frozen node IDs against integrated collection before committing it. Add matching
    e2e: required metadata and frozen scenario IDs to this feature spec in the same
    implementation commit. This activates the already-approved required scenario intent;
    without that metadata the compatibility default is optional and the generated
    plan is not yet runnable.'
  - Add real runner/verify rejection scenarios for source/log tampering, required
    skips and cleanup failures; keep evidence writer independent of exploration.
---

# FEAT-581 canonical deterministic plan

Generated during decomposition. Node IDs are frozen task contracts; runtime
validation and successful execution remain pending implementation. Live/browser
lanes are selected separately and are not claimed as executed by this plan.
