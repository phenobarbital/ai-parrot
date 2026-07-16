---
type: Concept
title: serve()
id: func:parrot.mcp.cli.serve
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Start an MCP server from a Python config file or YAML.
---

# serve

```python
def serve(config_file: str, transport: Optional[str], socket: Optional[str], port: Optional[int], log_level: str)
```

Start an MCP server from a Python config file or YAML.

Examples:

    # Python config file
    parrot mcp serve workday_server.py --transport unix --socket /tmp/workday.sock

    # YAML config file
    parrot mcp serve mcp_config.yaml

Python config file should define 'mcp' variable:

    # workday_server.py
    from parrot.services import ParrotMCPServer
    from parrot.toolkits.workday import WorkdayToolkit

    mcp = ParrotMCPServer(
        name="workday-mcp",
        tools=WorkdayToolkit(redis_url="redis://localhost:6379/4")
    )
