---
type: Wiki Summary
title: parrot.integrations.msteams.graph
id: mod:parrot.integrations.msteams.graph
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Minimal async Microsoft Graph client for the Teams HITL channel.
relates_to:
- concept: class:parrot.integrations.msteams.graph.GraphClient
  rel: defines
- concept: class:parrot.integrations.msteams.graph.ResolvedTeamsUser
  rel: defines
---

# `parrot.integrations.msteams.graph`

Minimal async Microsoft Graph client for the Teams HITL channel.

Provides email-to-AAD resolution used by TeamsHumanChannel.send_interaction
to map a recipient email address to an Azure AD object ID before opening
a proactive 1:1 conversation.

This module has NO dependency on botbuilder and does NOT import aiogram.
It uses only aiohttp (project-standard async HTTP) and pydantic (data models).

Graph app credentials:
    The app registration must have User.Read.All (application permission).
    Credentials are sourced from navconfig / environment variables at boot;
    never hardcoded here.

Usage::

    client = GraphClient(
        client_id="...",
        client_secret="...",
        tenant_id="...",
    )
    user = await client.get_user_by_email("manager@contoso.com")
    if user is None:
        # resolution failed — caller should return False
        ...
    manager = await client.get_user_manager(user.upn)

## Classes

- **`ResolvedTeamsUser(BaseModel)`** — Result of a successful Graph email-to-AAD resolution.
- **`GraphClient`** — Async Microsoft Graph client for the Teams HITL channel.
