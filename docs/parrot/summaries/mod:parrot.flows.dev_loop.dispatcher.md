---
type: Wiki Summary
title: parrot.flows.dev_loop.dispatcher
id: mod:parrot.flows.dev_loop.dispatcher
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ClaudeCodeDispatcher — orchestration glue between AgentsFlow and Claude Code.
relates_to:
- concept: class:parrot.flows.dev_loop.dispatcher.ClaudeCodeDispatcher
  rel: defines
- concept: class:parrot.flows.dev_loop.dispatcher.CodexCodeDispatcher
  rel: defines
- concept: class:parrot.flows.dev_loop.dispatcher.DevLoopCodeDispatcher
  rel: defines
- concept: class:parrot.flows.dev_loop.dispatcher.DispatchExecutionError
  rel: defines
- concept: class:parrot.flows.dev_loop.dispatcher.DispatchOutputValidationError
  rel: defines
- concept: class:parrot.flows.dev_loop.dispatcher.GeminiCodeDispatcher
  rel: defines
- concept: class:parrot.flows.dev_loop.dispatcher.GrokCodeDispatcher
  rel: defines
- concept: class:parrot.flows.dev_loop.dispatcher.LLMCodeDispatcher
  rel: defines
- concept: class:parrot.flows.dev_loop.dispatcher.ZaiCodeDispatcher
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.clients.claude_agent
  rel: references
- concept: mod:parrot.clients.factory
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.flows.dev_loop._subagent_defs
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
- concept: mod:parrot.models.zai
  rel: references
---

# `parrot.flows.dev_loop.dispatcher`

ClaudeCodeDispatcher — orchestration glue between AgentsFlow and Claude Code.

The dispatcher is the heart of FEAT-129. It is intentionally a *thin*
class: it owns the global concurrency cap, the Redis stream plumbing,
and the profile → run-options resolver, but delegates all SDK work to
:class:`parrot.clients.claude_agent.ClaudeAgentClient` (FEAT-124) via
:class:`parrot.clients.factory.LLMFactory`.

Responsibilities (per spec §3 Module 2):

1. Resolve a :class:`ClaudeCodeDispatchProfile` into a populated
   :class:`ClaudeAgentRunOptions`, including programmatic ``agents=`` and
   the ``extra_args={"output-format":"json","json-schema":<path>}``
   structured-output flags.
2. Acquire a global :class:`asyncio.Semaphore` sized by
   ``CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES``.
3. Iterate ``client.ask_stream(...)``, wrap each event in a
   :class:`DispatchEvent`, and ``XADD`` to
   ``flow:{run_id}:dispatch:{node_id}`` with an ``MAXLEN`` derived from
   ``stream_ttl_seconds``.
4. On final ``ResultMessage``, parse the concatenated assistant text as
   JSON and validate against ``output_model``. Raises
   :class:`DispatchOutputValidationError` on failure (carrying the raw
   payload for the audit log).
5. Defense-in-depth: refuse dispatch when ``cwd`` is not under
   ``WORKTREE_BASE_PATH`` (spec §7 R4).

## Classes

- **`DispatchExecutionError(Exception)`** — Raised when the Claude Code session fails before producing a result.
- **`DispatchOutputValidationError(Exception)`** — Raised when the final ResultMessage payload fails to validate.
- **`DevLoopCodeDispatcher(Protocol)`** — Shared dispatch contract consumed by dev-loop code-agent nodes.
- **`ClaudeCodeDispatcher`** — Thin orchestration class over :class:`ClaudeAgentClient`.
- **`CodexCodeDispatcher`** — Thin orchestration class over ``codex exec --json``.
- **`GeminiCodeDispatcher`** — Thin orchestration class over ``gemini --output-format stream-json``.
- **`LLMCodeDispatcher`** — Local coding-agent loop for OpenAI-compatible LLM clients.
- **`GrokCodeDispatcher(LLMCodeDispatcher)`** — Local coding-agent loop tailored for Grok client and Grok Build model.
- **`ZaiCodeDispatcher(LLMCodeDispatcher)`** — Local coding-agent loop bound to ``ZaiClient`` / GLM-5.2.
