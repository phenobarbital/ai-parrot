---
type: Wiki Entity
title: ClaudeAgentRunOptions
id: class:parrot.clients.claude_agent.ClaudeAgentRunOptions
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Run-time options forwarded to ``claude_agent_sdk.ClaudeAgentOptions``.
---

# ClaudeAgentRunOptions

Defined in [`parrot.clients.claude_agent`](../summaries/mod:parrot.clients.claude_agent.md).

```python
class ClaudeAgentRunOptions(BaseModel)
```

Run-time options forwarded to ``claude_agent_sdk.ClaudeAgentOptions``.

The agent SDK exposes a fairly large dataclass (``ClaudeAgentOptions``)
with about 30 fields. We surface only the subset that is meaningful for
typical ai-parrot agent dispatch scenarios — file/bash agents, tool
whitelisting, working-directory pinning, model selection. Unknown
options can still be passed by callers via the ``extra_options`` mapping.

Attributes:
    allowed_tools: Whitelist of CC tools (``Read``, ``Write``, ``Bash``,
        ``Edit``, …). When set, every tool not in this list is forbidden.
    disallowed_tools: Tools that must never be used during this run.
    permission_mode: One of ``default`` / ``acceptEdits`` / ``plan`` /
        ``bypassPermissions`` (see the SDK for the exhaustive list). The
        spec recommends ``"default"`` as the safest library default.
    cwd: Working directory the agent should operate from.
    cli_path: Override the bundled ``claude`` CLI binary location.
    system_prompt: Override the agent's system prompt.
    max_turns: Hard cap on agent reasoning turns.
    max_budget_usd: Hard cap on total spend for the run.
    model: Model id passed to the SDK (e.g. ``claude-sonnet-4-6``).
    fallback_model: Model id used if the primary model is unavailable.
    add_dirs: Extra directories the agent is permitted to access.
    env: Extra environment variables for the spawned CLI.
    extra_options: Escape hatch — keys forwarded to ``ClaudeAgentOptions``
        verbatim. Use sparingly; prefer adding fields here.
