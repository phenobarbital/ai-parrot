---
type: Wiki Summary
title: parrot.tools.pythonrepl
id: mod:parrot.tools.pythonrepl
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PythonREPLTool migrated to use AbstractTool framework with matplotlib fixes.
relates_to:
- concept: class:parrot.tools.pythonrepl.PythonREPLArgs
  rel: defines
- concept: class:parrot.tools.pythonrepl.PythonREPLTool
  rel: defines
- concept: func:parrot.tools.pythonrepl.brace_escape
  rel: defines
- concept: func:parrot.tools.pythonrepl.sanitize_input
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.security.python_sanitizer
  rel: references
- concept: mod:parrot.security.redaction
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.tools.pythonrepl`

PythonREPLTool migrated to use AbstractTool framework with matplotlib fixes.

## Classes

- **`PythonREPLArgs(BaseModel)`** — Arguments schema for PythonREPLTool.
- **`PythonREPLTool(AbstractTool)`** — Python REPL Tool with pre-loaded data science libraries and enhanced capabilities.

## Functions

- `def brace_escape(text: str) -> str` — Escape curly braces in text for format strings.
- `def sanitize_input(query: str) -> str` — Sanitize input to the python REPL.
