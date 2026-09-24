---
feature_id: FEAT-581
spec_path: sdd/specs/agentic-e2e-testing.spec.md
policy: required
targets: {}
scenarios:
  - id: mcp-http-lifecycle
    tier: deterministic
    target_ids: []
    required: true
    node_ids:
      - packages/ai-parrot-server/tests/e2e/test_mcp_http.py::test_http_cli_stays_alive_and_stops
    timeout_s: 120
    assertions:
      - "Standalone HTTP MCP CLI stays alive across two time-separated real requests and stops bounded on SIGTERM"
  - id: mcp-stdio-roundtrip
    tier: deterministic
    target_ids: []
    required: true
    node_ids:
      - packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py::test_stdio_tool_roundtrip_and_eof
    timeout_s: 60
    assertions:
      - "Real stdio MCP pipes: fixed tool round-trip and clean EOF exit"
  - id: botmanager-auth-and-offline
    tier: deterministic
    target_ids: []
    required: true
    node_ids:
      - packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_authenticated_minimal_profile
      - packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_botmanager_offline_boot
    timeout_s: 120
    assertions:
      - "Private-Redis bootstrap cookie round-trip, anonymous/invalid denial and a real authenticated API response"
      - "Minimal offline boot with a controlled empty tokenizer cache and outbound network disabled except fixture loopback"
  - id: supervisor-crash-isolation
    tier: deterministic
    target_ids: []
    required: true
    node_ids:
      - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_controller_and_supervisor_death
      - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_timeout_and_grandchild_teardown
      - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_two_worktrees_independent
      - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_wrong_checkout_cannot_pass
    timeout_s: 240
    assertions:
      - "Killing the controller and the supervisor separately at deterministic barriers still yields verified watchdog cleanup"
      - "A hung grandchild process tree is force-torn-down within a bounded deadline, never a brittle sleep"
      - "Two concurrent worktrees keep independent ports/state/data; stopping one owner never signals the sibling"
      - "A foreign/non-owned process identity (wrong checkout/module origin) is never a target this run may signal"
  - id: ui-browser-console-network
    tier: deterministic
    target_ids: []
    required: false
    node_ids:
      - packages/ai-parrot-server/tests/e2e/test_ui.py::test_ui_browser_console_network
    timeout_s: 120
    assertions:
      - "Owned browser navigation against the admin UI reports console/network invariants (or an explicit, visible BLOCKED when the browser lane is not provisioned)"
run_timeout_s: 1800
---

# Deterministic E2E plan — FEAT-581

This is the scheduled/manual **deterministic** CI plan for the M9 nightly
cron (`0 3 * * *`) and `workflow_dispatch` job declared in
`.github/workflows/e2e.yml`. Every scenario above is `tier: deterministic`;
none is `tier: live` — the deterministic CI plan intentionally contains no
required (or optional) live node IDs, matching spec §4 "the deterministic
CI plan must contain no required live node IDs."

Every `node_ids` entry above is a **frozen** integration node ID declared by
its owning task (TASK-3535/3536/3537/3548); renaming any of them requires
updating this plan (and `tests/sdd_scripts/test_e2e_ci_plans.py`, which
loads this document through the real `parrot.e2e.plan.load_plan` schema and
asserts on it) in the same change.

`targets` is intentionally empty and every scenario's `target_ids` is
empty: each scenario's own test module already owns its full target
lifecycle through the shared `e2e_supervisor_factory` fixture in
`packages/ai-parrot-server/tests/e2e/conftest.py` (real, owner-scoped
`E2ESupervisor` instances started and stopped inside the test itself), so
this plan does not ask the runner to pre-start a second, redundant copy of
the same target before invoking pytest.

The `ui-browser-console-network` scenario is deliberately `required: false`:
this feature's browser lane needs an explicitly pinned, separately
provisioned browser binary/Node/pnpm toolchain (spec §3 M9) that this CI
job does not install. Rather than being silently skipped as green, the
scenario is always selected and its true outcome — `passed` when the
toolchain happens to be present, or an explicit `blocked` recording the
missing prerequisite (never a fabricated pass) — is recorded in the run's
evidence and uploaded on failure; it never gates the deterministic policy.

Every one of the four `required: true` scenarios needs no provider secret:
`mcp-http-lifecycle`/`mcp-stdio-roundtrip` need only the already-declared
`mcp` extra; `botmanager-auth-and-offline` needs a local `redis-server`
binary (no managed service, no credential); `supervisor-crash-isolation`
only signals real child processes it owns. `PARROT_TEST_E2E=1` is the only
opt-in these scenarios require.
