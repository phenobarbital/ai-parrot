---
id: F007
query_id: Q009
type: grep
intent: Enumerate every registered parrot.clients entry point to confirm Claude Code and Codex both already have first-class LLMFactory providers
executed_at: 2026-09-06T03:15:00Z
duration_ms: 350
parent_id: null
depth: 0
---

# F007 — `OpenAICodexClient` also already exists and is registered, symmetric to Claude Code

## Summary

`packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py` defines
`OpenAICodexClient`, registered under three provider keys (`codex-agent`, `openai-codex`,
`codex-code`), `client_name = "openai-codex"`, `default_model = "gpt-5.1-codex"`,
`codex_bin: str = "codex"`. This means the requester's parenthetical "(o Codex)" is already
just as cheap to support as Claude Code — both are first-class `LLMFactory` providers today,
so the proposal's scope is "add detection + defaulting," never "add a new client."

## Citations

- path: `packages/ai-parrot-client-openai/pyproject.toml`
  lines: 37-41
  excerpt: |
    [project.entry-points."parrot.clients"]
    openai = "parrot.clients.openai:OpenAIClient"
    codex-agent = "parrot.clients.openai:OpenAICodexClient"
    openai-codex = "parrot.clients.openai:OpenAICodexClient"
    codex-code = "parrot.clients.openai:OpenAICodexClient"
- path: `packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py`
  lines: 46-81
  excerpt: |
    codex_bin: str = "codex"
    ...
    client_type = "openai_codex"
    client_name = "openai-codex"
    default_model = "gpt-5.1-codex"

## Notes

No cheap/"mini" Codex model id was found in this pass (only `default_model = "gpt-5.1-codex"`)
— unlike Claude's `ClaudeModel.HAIKU_4_5`, there is no obviously-deterministic-and-cheap Codex
model id confirmed yet. Flagged as an open question (see synthesis unknowns) rather than
guessed.
