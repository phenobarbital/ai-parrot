---
type: Wiki Summary
title: parrot.a2a.models
id: mod:parrot.a2a.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2A Protocol Data Models.
relates_to:
- concept: class:parrot.a2a.models.A2AError
  rel: defines
- concept: class:parrot.a2a.models.APIKeySecurityScheme
  rel: defines
- concept: class:parrot.a2a.models.AgentCapabilities
  rel: defines
- concept: class:parrot.a2a.models.AgentCard
  rel: defines
- concept: class:parrot.a2a.models.AgentCardSignature
  rel: defines
- concept: class:parrot.a2a.models.AgentConfig
  rel: defines
- concept: class:parrot.a2a.models.AgentExtension
  rel: defines
- concept: class:parrot.a2a.models.AgentInterface
  rel: defines
- concept: class:parrot.a2a.models.AgentProvider
  rel: defines
- concept: class:parrot.a2a.models.AgentSkill
  rel: defines
- concept: class:parrot.a2a.models.Artifact
  rel: defines
- concept: class:parrot.a2a.models.AuthenticationInfo
  rel: defines
- concept: class:parrot.a2a.models.HTTPAuthSecurityScheme
  rel: defines
- concept: class:parrot.a2a.models.Message
  rel: defines
- concept: class:parrot.a2a.models.MutualTlsSecurityScheme
  rel: defines
- concept: class:parrot.a2a.models.OAuth2SecurityScheme
  rel: defines
- concept: class:parrot.a2a.models.OpenIdConnectSecurityScheme
  rel: defines
- concept: class:parrot.a2a.models.Part
  rel: defines
- concept: class:parrot.a2a.models.RegisteredAgent
  rel: defines
- concept: class:parrot.a2a.models.Role
  rel: defines
- concept: class:parrot.a2a.models.SecurityRequirement
  rel: defines
- concept: class:parrot.a2a.models.SecurityScheme
  rel: defines
- concept: class:parrot.a2a.models.SendMessageConfiguration
  rel: defines
- concept: class:parrot.a2a.models.Task
  rel: defines
- concept: class:parrot.a2a.models.TaskPushNotificationConfig
  rel: defines
- concept: class:parrot.a2a.models.TaskState
  rel: defines
- concept: class:parrot.a2a.models.TaskStatus
  rel: defines
- concept: func:parrot.a2a.models.parse_role
  rel: defines
- concept: func:parrot.a2a.models.parse_task_state
  rel: defines
- concept: func:parrot.a2a.models.serialize_role
  rel: defines
- concept: func:parrot.a2a.models.serialize_task_state
  rel: defines
- concept: mod:parrot.outputs.a2ui.catalog
  rel: references
---

# `parrot.a2a.models`

A2A Protocol Data Models.

Upgraded to the A2A Protocol Specification v1.0.0 while retaining backward
compatibility with the pre-release v0.3 wire format used by Microsoft Copilot
Studio's ``a2a-dotnet`` parser.

Serialization is *version-aware*: every ``to_dict()`` accepts a ``version``
argument (``"1.0"`` by default). v1.0 emits ProtoJSON ``SCREAMING_SNAKE_CASE``
enum values (``"TASK_STATE_SUBMITTED"``) and v1.0 field shapes; v0.3 emits the
legacy lowercase values (``"submitted"``) and the flat card shape. Every
``from_dict()`` auto-detects the incoming format and accepts BOTH.

## Classes

- **`AgentConfig`** — Configuration for an A2A agent.
- **`TaskState(str, Enum)`** — Task lifecycle states — v1.0.0 ProtoJSON values.
- **`Role(str, Enum)`** — Message role — v1.0.0 ProtoJSON values.
- **`Part`** — Atomic content unit.
- **`Message`** — Communication unit between agents.
- **`TaskStatus`** — Current status of a task.
- **`Artifact`** — Output produced by an agent.
- **`Task`** — Unit of work with lifecycle.
- **`AgentExtension`** — A protocol extension declared by an agent (v1.0).
- **`AgentInterface`** — v1.0 AgentCard interface entry.
- **`AgentProvider`** — Organization that provides the agent (v1.0).
- **`SecurityScheme`** — Base security scheme (v1.0 securitySchemes entry).
- **`APIKeySecurityScheme(SecurityScheme)`** — API key security scheme.
- **`HTTPAuthSecurityScheme(SecurityScheme)`** — HTTP authentication security scheme (Bearer/Basic).
- **`OAuth2SecurityScheme(SecurityScheme)`** — OAuth 2.0 security scheme.
- **`OpenIdConnectSecurityScheme(SecurityScheme)`** — OpenID Connect security scheme.
- **`MutualTlsSecurityScheme(SecurityScheme)`** — Mutual TLS security scheme.
- **`SecurityRequirement`** — A security requirement: a map of scheme name -> required scopes.
- **`AgentCardSignature`** — A JWS signature over the AgentCard (v1.0). Signing itself is out of scope.
- **`AuthenticationInfo`** — Authentication details for a push notification webhook (v1.0).
- **`TaskPushNotificationConfig`** — Configuration for a task's push-notification webhook (v1.0).
- **`SendMessageConfiguration`** — Configuration accompanying a `SendMessage` request (v1.0).
- **`A2AError`** — A2A JSON-RPC error object.
- **`AgentSkill`** — A capability exposed by an agent (maps to a tool).
- **`AgentCapabilities`** — Capabilities supported by an agent.
- **`AgentCard`** — Self-describing manifest for an agent (A2A v1.0 structure).
- **`RegisteredAgent`** — Definition about a Registered Agent.

## Functions

- `def serialize_task_state(state: 'TaskState', version: str='1.0') -> str` — Serialize a TaskState to the wire value for the target protocol version.
- `def serialize_role(role: 'Role', version: str='1.0') -> str` — Serialize a Role to the wire value for the target protocol version.
- `def parse_task_state(value: Union[str, 'TaskState']) -> 'TaskState'` — Parse a TaskState from either the v0.3 or the v1.0 format.
- `def parse_role(value: Union[str, 'Role']) -> 'Role'` — Parse a Role from either the v0.3 or the v1.0 format.
