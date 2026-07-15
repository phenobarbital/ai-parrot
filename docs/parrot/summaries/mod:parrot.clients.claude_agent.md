---
type: Wiki Summary
title: parrot.clients.claude_agent
id: mod:parrot.clients.claude_agent
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ClaudeAgentClient — dispatch tasks to Claude Code agents via the agent SDK.
relates_to:
- concept: class:parrot.clients.claude_agent.ClaudeAgentClient
  rel: defines
- concept: class:parrot.clients.claude_agent.ClaudeAgentRunOptions
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.models.responses
  rel: references
---

# `parrot.clients.claude_agent`

ClaudeAgentClient — dispatch tasks to Claude Code agents via the agent SDK.

This module exposes :class:`ClaudeAgentClient`, an
:class:`AbstractClient` subclass that drives Anthropic's
``claude-agent-sdk`` (which itself wraps the bundled ``claude`` CLI) so
ai-parrot Agents can delegate file-aware, bash-capable, tool-using work
to a Claude Code sub-agent.

Highlights:

* The ``claude_agent_sdk`` import is **strictly lazy** — performed inside
  every method that needs it. ``import parrot.clients.claude_agent`` is
  therefore safe even when the optional ``ai-parrot[claude-agent]`` extra
  is not installed; the failure surfaces only when the user actually
  calls a method (with a clear ``ImportError``).

* ``ask`` runs a one-shot ``query()``, collects the entire SDK message
  stream, and renders an :class:`AIMessage` via
  :py:meth:`AIMessageFactory.from_claude_agent`.

* ``ask_stream`` yields :class:`TextBlock` text incrementally as each
  ``AssistantMessage`` arrives.

* ``invoke`` produces a stateless structured-output extraction by
  embedding the JSON schema of ``output_type`` directly in the prompt and
  parsing the assistant's text response. The agent SDK has no native
  ``response_format`` parameter equivalent to OpenAI's, so we follow the
  ``AnthropicClient.invoke`` schema-in-prompt pattern.

* ``resume`` continues a conversation by passing
  ``ClaudeAgentOptions.resume = session_id`` to ``query()``.

* Methods that the upstream SDK does not support (``batch_ask``,
  ``ask_to_image``, the analytic helpers) raise ``NotImplementedError``
  with a redirect message pointing at :class:`AnthropicClient`.

## Classes

- **`ClaudeAgentRunOptions(BaseModel)`** — Run-time options forwarded to ``claude_agent_sdk.ClaudeAgentOptions``.
- **`ClaudeAgentClient(AbstractClient)`** — Dispatch tasks to a Claude Code agent via ``claude-agent-sdk``.
