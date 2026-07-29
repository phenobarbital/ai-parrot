---
type: Wiki Entity
title: WorkIQTool
id: class:parrot.tools.workiq_tool.WorkIQTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Work IQ MCP credential adapter — queries the Work IQ MCP server via OBO auth.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# WorkIQTool

Defined in [`parrot.tools.workiq_tool`](../summaries/mod:parrot.tools.workiq_tool.md).

```python
class WorkIQTool(AbstractTool)
```

Work IQ MCP credential adapter — queries the Work IQ MCP server via OBO auth.

Work IQ (``github.com/microsoft/work-iq``) is a Microsoft enterprise
assistant delivered as an MCP server.  It answers natural-language queries
about enterprise M365 data (Teams, SharePoint, email, calendar) while
applying the user's M365 permissions, sensitivity labels, and compliance
policies automatically.

This tool is a **credential adapter**: it declares the OBO credential
requirement (``credential_provider = "workiq"``) so the A2A bridge
(FEAT-263 / TASK-1644) resolves the delegated Entra OBO token via
:class:`~parrot.auth.oauth2.workiq_provider.WorkIQOBOCredentialResolver`
before invocation.  After credential resolution, the tool proxies the query
to the Work IQ MCP server endpoint.

Attributes:
    name: ``"workiq_ask"`` — stable identifier used in A2A ``"tool"``
        payloads.
    credential_provider: ``"workiq"`` — signals OBO-gated resolver.
    args_schema: :class:`_WorkIQArgs` Pydantic v2 model.
    mcp_server_url: Work IQ MCP server endpoint (configurable per
        deployment; default: ``"https://workiq.svc.cloud.microsoft/mcp"``).
