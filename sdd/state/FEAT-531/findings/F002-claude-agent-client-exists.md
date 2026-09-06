---
id: F002
query_id: Q002
type: grep
intent: Confirm whether an ai-parrot client already wraps the Claude Agent SDK / Claude Code CLI credentials
executed_at: 2026-09-06T03:09:33Z
duration_ms: 380
parent_id: null
depth: 0
---

# F002 — `ClaudeAgentClient` already exists and is registered with `LLMFactory`

## Summary

`packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py` defines
`ClaudeAgentClient(AbstractClient)`, which dispatches through `claude-agent-sdk` (which itself
wraps the bundled `claude` CLI). It is registered in `LLMFactory` under two provider keys, so
`LLMFactory.create("claude-code:...")` already works with zero new client code.

## Citations

- path: `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py`
  symbol: `ClaudeAgentClient`
  excerpt: |
    """ClaudeAgentClient — dispatch tasks to Claude Code agents via the agent SDK.
    ...drives Anthropic's claude-agent-sdk (which itself wraps the bundled claude CLI)..."""
- path: `packages/ai-parrot-client-anthropic/pyproject.toml`
  lines: 26-32
  excerpt: |
    [project.entry-points."parrot.clients"]
    claude = "parrot.clients.anthropic:AnthropicClient"
    anthropic = "parrot.clients.anthropic:AnthropicClient"
    bedrock = "parrot.clients.anthropic:AnthropicClient"
    anthropic-aws = "parrot.clients.anthropic:AnthropicClient"
    claude-agent = "parrot.clients.anthropic:ClaudeAgentClient"
    claude-code = "parrot.clients.anthropic:ClaudeAgentClient"

## Notes

`ask`, `ask_stream`, `invoke`, `resume` are all implemented per the `AbstractClient` contract
(FEAT-524 memory-less shape). `get_client()` returns a fresh `ClaudeSDKClient`.
