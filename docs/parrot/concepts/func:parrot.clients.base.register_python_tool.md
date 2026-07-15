---
type: Concept
title: register_python_tool()
id: func:parrot.clients.base.register_python_tool
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register Python REPL tool with a ClaudeAPIClient.
---

# register_python_tool

```python
def register_python_tool(client, report_dir: Optional[Path]=None, plt_style: str='seaborn-v0_8-whitegrid', palette: str='Set2') -> PythonREPLTool
```

Register Python REPL tool with a ClaudeAPIClient.

Args:
    client: The ClaudeAPIClient instance
    report_dir: Directory for saving reports
    plt_style: Matplotlib style
    palette: Seaborn color palette

Returns:
    The PythonREPLTool instance
