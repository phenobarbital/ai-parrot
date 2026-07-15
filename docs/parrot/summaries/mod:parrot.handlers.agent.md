---
type: Wiki Summary
title: parrot.handlers.agent
id: mod:parrot.handlers.agent
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AgentTalk - HTTP Handler for Agent Conversations
relates_to:
- concept: class:parrot.handlers.agent.AgentTalk
  rel: defines
- concept: class:parrot.handlers.agent.PausedEnvelope
  rel: defines
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.auth.oauth2.models
  rel: references
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.bots.data
  rel: references
- concept: mod:parrot.bots.search
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.core.exceptions
  rel: references
- concept: mod:parrot.handlers.avatar_fullmode
  rel: references
- concept: mod:parrot.handlers.credentials_utils
  rel: references
- concept: mod:parrot.handlers.csp
  rel: references
- concept: mod:parrot.handlers.mcp_persistence
  rel: references
- concept: mod:parrot.handlers.user_objects
  rel: references
- concept: mod:parrot.handlers.web_hitl
  rel: references
- concept: mod:parrot.human
  rel: references
- concept: mod:parrot.human.models
  rel: references
- concept: mod:parrot.human.suspended_store
  rel: references
- concept: mod:parrot.integrations.liveavatar
  rel: references
- concept: mod:parrot.integrations.liveavatar.models
  rel: references
- concept: mod:parrot.integrations.liveavatar.output_bridge
  rel: references
- concept: mod:parrot.integrations.liveavatar.output_transport
  rel: references
- concept: mod:parrot.interfaces.documentdb
  rel: references
- concept: mod:parrot.manager
  rel: references
- concept: mod:parrot.mcp.integration
  rel: references
- concept: mod:parrot.mcp.registry
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models.infographic
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.outputs
  rel: references
- concept: mod:parrot.storage.models
  rel: references
- concept: mod:parrot.tools.jira_connect_tool
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.handlers.agent`

AgentTalk - HTTP Handler for Agent Conversations
=================================================
Provides a flexible HTTP interface for talking with agents/bots using the ask() method
with support for multiple output modes and MCP server integration.

## Classes

- **`PausedEnvelope(BaseModel)`** — HTTP-200 structured reply returned by AgentTalk when a SUSPEND tool raises
- **`AgentTalk(BaseView)`** — AgentTalk Handler - Universal agent conversation interface.
