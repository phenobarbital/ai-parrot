---
type: Wiki Summary
title: parrot.clients.base
id: mod:parrot.clients.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.clients.base
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: defines
- concept: class:parrot.clients.base.BatchRequest
  rel: defines
- concept: class:parrot.clients.base.MessageResponse
  rel: defines
- concept: class:parrot.clients.base.RetryConfig
  rel: defines
- concept: class:parrot.clients.base.StreamingRetryConfig
  rel: defines
- concept: class:parrot.clients.base.TokenRetryMixin
  rel: defines
- concept: func:parrot.clients.base.register_python_tool
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: references
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.models.basic
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.observability.context
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
- concept: mod:parrot.tools.pythonrepl
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.clients.base`

## Classes

- **`MessageResponse(TypedDict)`** — Response structure for LLM messages.
- **`RetryConfig`** — Configuration for MAX_TOKENS retry behavior.
- **`TokenRetryMixin`** — Mixin class to add token retry functionality to any LLM client.
- **`BatchRequest`** — Data structure for batch request.
- **`StreamingRetryConfig`** — Configuration for streaming retry behavior.
- **`AbstractClient(EventEmitterMixin, ABC)`** — Abstract base Class for LLM models.

## Functions

- `def register_python_tool(client, report_dir: Optional[Path]=None, plt_style: str='seaborn-v0_8-whitegrid', palette: str='Set2') -> PythonREPLTool` — Register Python REPL tool with a ClaudeAPIClient.
