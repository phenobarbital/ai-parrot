---
type: Wiki Entity
title: CodeToolkit
id: class:parrot_tools.code_toolkit.CodeToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for delegating coding tasks to Codex-compatible providers.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# CodeToolkit

Defined in [`parrot_tools.code_toolkit`](../summaries/mod:parrot_tools.code_toolkit.md).

```python
class CodeToolkit(AbstractToolkit)
```

Toolkit for delegating coding tasks to Codex-compatible providers.

## Methods

- `async def implement_spec(self, spec_file: str, repo_path: str, test_command: str | None=None, model: str | None=None) -> CodingTaskResult` — Implement the bugfix or feature described in a specification file.
- `async def fix_bug(self, spec_file: str, repo_path: str, test_command: str | None=None, model: str | None=None) -> CodingTaskResult` — Fix the bug described in a specification file.
- `async def review_diff(self, spec_file: str, repo_path: str, test_command: str | None=None, model: str | None=None) -> CodingTaskResult` — Review the repository diff against the specification file.
- `async def generate_tests(self, spec_file: str, repo_path: str, test_command: str | None=None, model: str | None=None) -> CodingTaskResult` — Generate or update tests required by a specification file.
- `async def explain_patch(self, patch_file: str, repo_path: str, model: str | None=None) -> CodingTaskResult` — Explain an existing patch in the context of a repository.
