---
type: Wiki Summary
title: parrot_tools.code_toolkit
id: mod:parrot_tools.code_toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Code toolkit for spec-driven coding tasks.
relates_to:
- concept: class:parrot_tools.code_toolkit.CodeToolkit
  rel: defines
- concept: class:parrot_tools.code_toolkit.CodexProvider
  rel: defines
- concept: class:parrot_tools.code_toolkit.CodingProvider
  rel: defines
- concept: class:parrot_tools.code_toolkit.CodingTask
  rel: defines
- concept: class:parrot_tools.code_toolkit.CodingTaskInput
  rel: defines
- concept: class:parrot_tools.code_toolkit.CodingTaskResult
  rel: defines
- concept: class:parrot_tools.code_toolkit.ExplainPatchInput
  rel: defines
- concept: class:parrot_tools.code_toolkit.MinimaxProvider
  rel: defines
- concept: func:parrot_tools.code_toolkit.parse_frontmatter
  rel: defines
- concept: mod:parrot.clients.nvidia
  rel: references
- concept: mod:parrot.models.nvidia
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.code_toolkit`

Code toolkit for spec-driven coding tasks.

The toolkit exposes high-level coding operations through ``AbstractToolkit``
while keeping execution behind provider classes. The Codex SDK integration is
lazy because the SDK is experimental and optional.

## Classes

- **`CodingTask`** — Artifact describing a coding task to execute against a repository.
- **`CodingTaskResult`** — Structured result returned by coding providers.
- **`CodingProvider(Protocol)`** — Provider protocol implemented by coding backends.
- **`CodingTaskInput(BaseModel)`** — Shared input fields for code toolkit tools.
- **`ExplainPatchInput(BaseModel)`** — Input for explaining an existing patch or diff.
- **`CodexProvider`** — Coding provider backed by the experimental OpenAI Codex SDK.
- **`MinimaxProvider`** — Coding provider backed by Nvidia-hosted Minimax-compatible models.
- **`CodeToolkit(AbstractToolkit)`** — Toolkit for delegating coding tasks to Codex-compatible providers.

## Functions

- `def parse_frontmatter(text: str) -> dict[str, Any]` — Parse a small YAML-like frontmatter block without adding dependencies.
