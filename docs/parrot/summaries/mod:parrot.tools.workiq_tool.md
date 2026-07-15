---
type: Wiki Summary
title: parrot.tools.workiq_tool
id: mod:parrot.tools.workiq_tool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Work IQ MCP credential adapter tool for the A2A per-user credential bridge.
relates_to:
- concept: class:parrot.tools.workiq_tool.WorkIQTool
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.tools.workiq_tool`

Work IQ MCP credential adapter tool for the A2A per-user credential bridge.

OQ#5 resolved (2026-06-27 — FEAT-263 / TASK-1649):
Work IQ (``github.com/microsoft/work-iq``) is an **MCP server**, not a native
toolkit.  Auth: Entra On-Behalf-Of (OBO), scope
``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``.  Admin consent required.
App-only access is NOT supported.

This module contains :class:`WorkIQTool`, which acts as a credential adapter:
- Declares ``credential_provider = "workiq"`` so the A2A bridge routes through
  :class:`~parrot.auth.oauth2.workiq_provider.WorkIQOBOCredentialResolver`.
- After the bridge resolves the per-user OBO token, the tool proxies the query
  to the Work IQ MCP server.

Work IQ enforces M365 permissions, sensitivity labels, and compliance policies
automatically — no additional filtering is required on this adapter side.

Usage::

    from parrot.tools.workiq_tool import WorkIQTool
    from parrot.auth.oauth2.workiq_provider import WorkIQOAuth2Provider

    tool = WorkIQTool()
    provider = WorkIQOAuth2Provider(
        o365_interface=o365,
        o365_oauth_manager=o365_manager,
        vault_token_sync=vault,
    )
    a2a_server.wire_workiq_resolver(provider.credential_resolver())
    # agent.tools = [tool]

## Classes

- **`WorkIQTool(AbstractTool)`** — Work IQ MCP credential adapter — queries the Work IQ MCP server via OBO auth.
