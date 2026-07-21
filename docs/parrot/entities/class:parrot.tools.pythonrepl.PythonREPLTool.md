---
type: Wiki Entity
title: PythonREPLTool
id: class:parrot.tools.pythonrepl.PythonREPLTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Python REPL Tool with pre-loaded data science libraries and enhanced capabilities.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# PythonREPLTool

Defined in [`parrot.tools.pythonrepl`](../summaries/mod:parrot.tools.pythonrepl.md).

```python
class PythonREPLTool(AbstractTool)
```

Python REPL Tool with pre-loaded data science libraries and enhanced capabilities.

Features:
- Pre-loaded libraries: pandas (pd), numpy (np), matplotlib.pyplot (plt), seaborn (sns), numexpr (ne)
- Pre-loaded libraries: altair, plotly, folium
- Base64 encoding support for matplotlib plots
- Automatic plot saving
- Report directory management
- JSON serialization/deserialization for execution results

## Methods

- `def execute_sync(self, code: str, debug: bool=False) -> str` — Execute Python code synchronously.
- `def get_environment_info(self) -> Dict[str, Any]` — Get information about the current REPL environment.
- `def reset_environment(self) -> None` — Reset the REPL environment to its initial state.
- `def save_execution_results(self, filename: Optional[str]=None) -> Dict[str, Any]` — Save current execution results to a JSON file.
- `def load_execution_results(self, file_path: Union[str, Path]) -> Dict[str, Any]` — Load execution results from a JSON file.
- `def safe_execution_context(self)` — Context manager for safe code execution that prevents crashes.
- `def execute_code_safely(self, code: str, debug: bool=False) -> str` — Execute code with maximum safety against crashes.
