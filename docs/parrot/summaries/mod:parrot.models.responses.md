---
type: Wiki Summary
title: parrot.models.responses
id: mod:parrot.models.responses
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.models.responses
relates_to:
- concept: class:parrot.models.responses.AIMessage
  rel: defines
- concept: class:parrot.models.responses.AIMessageFactory
  rel: defines
- concept: class:parrot.models.responses.AgentResponse
  rel: defines
- concept: class:parrot.models.responses.InvokeResult
  rel: defines
- concept: class:parrot.models.responses.MessageResponse
  rel: defines
- concept: class:parrot.models.responses.SourceDocument
  rel: defines
- concept: class:parrot.models.responses.StreamChunk
  rel: defines
- concept: mod:parrot.models.basic
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.models.responses`

## Classes

- **`SourceDocument`** — Enhanced source document information similar to Parrot's format.
- **`StreamChunk(BaseModel)`** — Represents a chunk in a streaming response.
- **`MessageResponse(TypedDict)`** — Response structure for LLM messages.
- **`AIMessage(BaseModel)`** — Unified AI message response that can handle various output types.
- **`AIMessageFactory`** — Factory to create AIMessage from different provider responses.
- **`AgentResponse(BaseModel)`** — AgentResponse is a model that defines the structure of the response for Any Parrot agent.
- **`InvokeResult(BaseModel)`** — Lightweight result from a stateless invoke() call.
