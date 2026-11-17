---
id: FC-012
query_id: Q025
type: glob
intent: "Existing tests for CLI, mcp-local, agentd"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-012 — Tests exist for CLI identity, local server, hosts, toolkit install, agentd

## Summary

Relevant test files: core `tests/cli/test_identity.py`, `test_agent_command.py`, `test_session.py`, `test_repl_runner.py`, `tests/integration/test_cli_devicecode_e2e.py`; core `tests/mcp/test_local_server.py`, `test_local_server_concurrency.py`, `test_hosts.py`, `test_toolkit_install.py`, `test_toolkit_matrix.py`, `test_owned_toolkit_lifecycle.py`, `test_adapter.py`; integrations `tests/agentd/` (directory present).

## Citations

- path: `packages/ai-parrot/tests/cli/`
  lines: dir
  symbol: `cli tests`
  excerpt: |
    test_identity.py test_agent_command.py test_session.py test_repl_runner.py test_commands_context.py ...

- path: `packages/ai-parrot/tests/mcp/`
  lines: dir
  symbol: `mcp tests`
  excerpt: |
    test_local_server.py test_local_server_concurrency.py test_hosts.py test_toolkit_install.py test_toolkit_matrix.py test_owned_toolkit_lifecycle.py test_adapter.py

- path: `packages/ai-parrot-integrations/tests/agentd/`
  lines: dir
  symbol: `agentd tests`
  excerpt: |
    (directory present)


## Notes

No test covers a per-user credential inside a stdio toolkit server (none exists to test).
