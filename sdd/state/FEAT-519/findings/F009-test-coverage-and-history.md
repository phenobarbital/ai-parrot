---
id: F009
query_id: Q017,Q018
type: glob
intent: Establish what a refactor must keep green and what changed recently
executed_at: 2026-09-02T22:01:00Z
parent_id: null
depth: 0
---

# F009 — A FEAT-168 integration suite covers the REPL; devloop has a dedicated console/renderer suite

## Summary

`tests/cli/test_integration.py` is the regression net for the agent REPL,
covering `ResponseRenderer`, `AgentREPL.send`/`send_stream`, slash commands,
export roundtrip and the Click command — all mock-based, no server or API keys.
The devloop console has its own suite (`tests/cli/devloop/`), including e2e
console tests, giving a template for how a Live-based console is tested here.
Recent history shows the streaming renderer was touched as a bugfix, not
designed: commit `99ad3ddf3` bundles "REPL quit/exit handling, streaming
renderer".

## Citations

- path: `packages/ai-parrot/tests/cli/test_integration.py`
  lines: 1-20
  symbol: module docstring + imports
  excerpt: |
    """Integration tests for the AI-Parrot CLI agent REPL (FEAT-168).
    ...
    from parrot.cli.agent_repl import agent as agent_cmd
    from parrot.cli.repl import AgentREPL, REPLConfig

- path: `packages/ai-parrot/tests/cli/test_integration.py`
  lines: 29,88,156,186,247,300,360,441,491
  symbol: test classes
  excerpt: |
    class TestResponseRenderer:
    class TestSlashCommandDispatcher:
    class TestREPLConfig:
    class TestStandaloneAgentLoader:
    class TestAgentREPLSend:
    class TestAgentREPLStream:
    class TestSlashCommandsAsync:
    class TestExportRoundtrip:
    class TestCLICommandAgent:

- path: `packages/ai-parrot/tests/cli/devloop/test_renderer.py`
  symbol: devloop Live renderer tests
- path: `packages/ai-parrot/tests/cli/devloop/integration/test_console_e2e.py`
  symbol: devloop console e2e tests

- path: `packages/ai-parrot/tests/cli/test_wizard.py`
  symbol: wizard engine tests

## Notes

git log (120 days, `packages/ai-parrot/src/parrot/cli`):
- `99ad3ddf3` fix: FirefliesObsidianAgent tool registration, REPL quit/exit handling, streaming renderer
- `d92fdac86` feat(devloop-cli-homologation): TASK-1970 — Console kind picker, feature wizard path, pool/judge steps, flags
- `243d67346` feat(devloop-cli-homologation): TASK-1971 — Bootstrap multi-backend dispatcher
- `ecd2d205d` feat(agent-cli-daemon): TASK-2216 — CLI commands + core LazyGroup registration

The dominant recent theme is devloop console work — i.e. investment has been
flowing into the *sibling* console, which is why it has outgrown `parrot agent`.
