---
id: F007
query_id: Q006
type: grep
intent: Map the existing Rich footprint and the conventions it establishes
executed_at: 2026-09-02T22:00:00Z
parent_id: null
depth: 0
---

# F007 — Rich is established across 30 files in 4 distributions

## Summary

Rich is not a new adoption: 30 files import it, spanning core CLI, devloop,
the agentd integration, the server agent handler, the human-in-the-loop channel,
the wiki CLI, and the output-format generators in ai-parrot-visualizations.
Any refactor extends an existing convention rather than introducing a stack.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  symbol: core agent-REPL renderer
- path: `packages/ai-parrot/src/parrot/cli/devloop/renderer.py`
  symbol: devloop Live painter
- path: `packages/ai-parrot/src/parrot/cli/devloop/console.py`
  symbol: devloop console engine
- path: `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py`
  symbol: devloop preflight
- path: `packages/ai-parrot/src/parrot/cli/wizard.py`
  symbol: generic Pydantic wizard engine
- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  symbol: `parrot agent` Click command
- path: `packages/ai-parrot/src/parrot/cli/repl.py`
  symbol: `AgentREPL`
- path: `packages/ai-parrot/src/parrot/human/channels/cli.py`
  symbol: HITL CLI channel
- path: `packages/ai-parrot/src/parrot/human/cli_companion.py`
  symbol: CLI companion
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  symbol: wikitoolkit CLI
- path: `packages/ai-parrot/src/parrot/outputs/formats/table.py`
  symbol: table output format
- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py`
  symbol: agentd CLI
- path: `packages/ai-parrot-server/src/parrot/handlers/agent.py`
  symbol: server agent handler
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/generators/terminal.py`
  symbol: terminal chart generator

## Notes

`parrot/human/channels/cli.py` and `cli_companion.py` are a HITL surface that
already renders with Rich and was not named in the request — relevant to the
"HITL and other interactions" part of the ask.
