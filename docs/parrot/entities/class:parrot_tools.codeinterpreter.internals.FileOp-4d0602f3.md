---
type: Wiki Entity
title: FileOperationsTool
id: class:parrot_tools.codeinterpreter.internals.FileOperationsTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for file operations (reading, writing, organizing outputs).
---

# FileOperationsTool

Defined in [`parrot_tools.codeinterpreter.internals`](../summaries/mod:parrot_tools.codeinterpreter.internals.md).

```python
class FileOperationsTool
```

Tool for file operations (reading, writing, organizing outputs).

## Methods

- `def save_file(self, content: str, filename: str, subdirectory: Optional[str]=None) -> Dict[str, Any]` — Save content to a file.
- `def read_file(self, file_path: str) -> Dict[str, Any]` — Read content from a file.
- `def save_multiple(self, files: Dict[str, str], subdirectory: Optional[str]=None) -> Dict[str, Any]` — Save multiple files.
