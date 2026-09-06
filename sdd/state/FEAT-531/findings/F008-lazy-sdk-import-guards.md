---
id: F008
query_id: Q010
type: grep
intent: Confirm ClaudeAgentClient/OpenAICodexClient use a lazy, cheap-to-check SDK import guard rather than an eager subprocess/network call
executed_at: 2026-09-06T03:15:40Z
duration_ms: 220
parent_id: null
depth: 0
---

# F008 — Both clients already gate real work behind a lazy `_import_sdk()`-style guard

## Summary

`ClaudeAgentClient` performs the `claude_agent_sdk` import lazily inside every method that
needs it (module docstring: "The `claude_agent_sdk` import is strictly lazy... `import
parrot.clients.anthropic.claude_agent` is therefore safe even when the optional
`ai-parrot[claude-agent]` extra is not installed"). `OpenAICodexClient` has the symmetric
`_import_sdk()` static method (line 656) that raises a clear `ImportError` with an install
hint. Neither eagerly spawns the `claude`/`codex` binary or makes a network call just from
being imported/constructed — this is exactly the "safe execution" primitive the requester
asked for: a cheap `try: import <sdk>` (mirroring what each client already does internally)
plus `shutil.which("<cli-bin>")`, with no real request sent to probe availability.

## Citations

- path: `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py`
  lines: 1-16
  excerpt: |
    * The ``claude_agent_sdk`` import is **strictly lazy** — performed inside
      every method that needs it. ``import parrot.clients.anthropic.claude_agent`` is
      therefore safe even when the optional ``ai-parrot[claude-agent]`` extra
      is not installed; the failure surfaces only when the user actually
      calls a method (with a clear ``ImportError``).
- path: `packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py`
  lines: 656-660
  symbol: `_import_sdk`
  excerpt: |
    def _import_sdk() -> Any:
        try:
            ...
        except ImportError as exc:
            raise ImportError(...)

## Notes

The new shared detection helper should reuse this exact "try import, catch ImportError" idiom
plus `shutil.which(<cli_bin>)`, never actually instantiate a client or call `ask()`/`invoke()`
during detection.
