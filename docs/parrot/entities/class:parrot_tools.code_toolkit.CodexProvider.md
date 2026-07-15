---
type: Wiki Entity
title: CodexProvider
id: class:parrot_tools.code_toolkit.CodexProvider
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Coding provider backed by the experimental OpenAI Codex SDK.
---

# CodexProvider

Defined in [`parrot_tools.code_toolkit`](../summaries/mod:parrot_tools.code_toolkit.md).

```python
class CodexProvider
```

Coding provider backed by the experimental OpenAI Codex SDK.

## Methods

- `async def run_task(self, task: CodingTask, model: str | None=None) -> CodingTaskResult` — Run a coding task with the OpenAI Codex SDK.
- `def build_prompt(self, task: CodingTask, spec: str) -> str` — Build a Codex prompt from a coding task and specification text.
- `def parse_result(result: Any) -> CodingTaskResult` — Parse a Codex SDK result object without repository diff context.
