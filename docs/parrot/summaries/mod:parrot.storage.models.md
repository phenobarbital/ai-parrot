---
type: Wiki Summary
title: parrot.storage.models
id: mod:parrot.storage.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Data models for chat persistence.
relates_to:
- concept: class:parrot.storage.models.Artifact
  rel: defines
- concept: class:parrot.storage.models.ArtifactCreator
  rel: defines
- concept: class:parrot.storage.models.ArtifactSummary
  rel: defines
- concept: class:parrot.storage.models.ArtifactType
  rel: defines
- concept: class:parrot.storage.models.CanvasBlock
  rel: defines
- concept: class:parrot.storage.models.CanvasBlockType
  rel: defines
- concept: class:parrot.storage.models.CanvasDefinition
  rel: defines
- concept: class:parrot.storage.models.ChatMessage
  rel: defines
- concept: class:parrot.storage.models.Conversation
  rel: defines
- concept: class:parrot.storage.models.MessageRole
  rel: defines
- concept: class:parrot.storage.models.Source
  rel: defines
- concept: class:parrot.storage.models.ThreadMetadata
  rel: defines
- concept: class:parrot.storage.models.ToolCall
  rel: defines
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.storage.models`

Data models for chat persistence.

Dedicated models that capture the full interaction payload
(user input, agent output, metadata, tool calls, sources, timing).

Also contains Pydantic models for artifact and thread persistence
(FEAT-103: agent-artifact-persistency).

## Classes

- **`MessageRole(str, Enum)`** — Role of the message sender.
- **`ToolCall`** — A single tool invocation within a turn.
- **`Source`** — A source/reference returned by the agent.
- **`ChatMessage`** — Represents a single chat message (one direction: user OR assistant).
- **`Conversation`** — Conversation metadata — one document per session in DocumentDB.
- **`ArtifactType(str, Enum)`** — Type of artifact produced by an agent or user.
- **`ArtifactCreator(str, Enum)`** — Who created the artifact.
- **`ArtifactSummary(BaseModel)`** — Lightweight artifact reference for thread metadata.
- **`Artifact(BaseModel)`** — Full artifact with definition payload.
- **`ThreadMetadata(BaseModel)`** — Conversation thread metadata stored in DynamoDB.
- **`CanvasBlockType(str, Enum)`** — Type of block within a canvas tab.
- **`CanvasBlock(BaseModel)`** — Individual block within a canvas tab.
- **`CanvasDefinition(BaseModel)`** — Complete canvas tab artifact definition.
