---
type: Wiki Overview
title: 'Feature Specification: A2A Protocol v1.0.0 Compatibility'
id: doc:sdd-specs-a2a-protocol-compatibility-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot's A2A implementation was built against the pre-release v0.3 era
  of the
relates_to:
- concept: mod:parrot.a2a.client
  rel: mentions
- concept: mod:parrot.a2a.mesh
  rel: mentions
- concept: mod:parrot.a2a.models
  rel: mentions
- concept: mod:parrot.a2a.push_notifications
  rel: mentions
- concept: mod:parrot.a2a.router
  rel: mentions
- concept: mod:parrot.a2a.server
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: A2A Protocol v1.0.0 Compatibility

**Feature ID**: FEAT-272
**Date**: 2026-07-09
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's A2A implementation was built against the pre-release v0.3 era of the
protocol, primarily targeting Microsoft Copilot Studio's `a2a-dotnet` parser.
The A2A protocol has since been ratified as v1.0.0
(`https://a2a-protocol.org/v1.0.0/specification/`), introducing breaking changes
to the AgentCard structure, enum serialization format, HTTP endpoint patterns,
JSON-RPC method naming, error codes, versioning headers, and new operations.

The current implementation is **not compatible** with v1.0.0 clients or servers.
Any agent ecosystem adopting the ratified standard will be unable to discover or
communicate with AI-Parrot agents, and AI-Parrot's `A2AClient` will fail to
interoperate with v1.0.0 servers.

### Goals

- Upgrade AI-Parrot's A2A server and client to full compliance with the
  A2A Protocol Specification v1.0.0.
- Maintain backward compatibility with v0.3 clients (Microsoft Copilot Studio)
  via version negotiation.
- Implement all mandatory v1.0.0 operations and data model changes.
- Implement optional operations (push notifications, extended AgentCard) behind
  capability flags.
- Ensure all models serialize using the v1.0.0 conventions (ProtoJSON
  `SCREAMING_SNAKE_CASE` enums, camelCase field names).

### Non-Goals (explicitly out of scope)

- **gRPC binding**: The v1.0.0 spec defines JSON-RPC, gRPC, and HTTP+JSON
  bindings. gRPC is deferred to a future feature — this spec covers JSON-RPC
  and HTTP+JSON only.
- **Protocol extensions**: The `extensions` mechanism (custom operations via
  `AgentExtension`) is deferred. The `extensions` field will be modeled but
  no custom extensions will be implemented.
- **AgentCard signatures** (JWS/RFC 7515): Deferred. The `signatures` field
  will be modeled but signing/verification logic is out of scope.
- **Webhook delivery for push notifications**: The push notification CRUD
  operations will be implemented so agents can accept configuration. Actual
  webhook delivery (HTTP POST to client URLs with SSRF validation) is a
  follow-up feature.
- **Replacing the security middleware** (`A2ASecurityMiddleware`): The existing
  auth layer is functionally rich. This spec maps it to v1.0.0's
  `securitySchemes` / `securityRequirements` in the AgentCard, but does not
  rewrite the middleware itself.

---

## 2. Architectural Design

### Overview

The upgrade is a **model-and-protocol-layer refactor** that touches:

1. **Data models** (`models.py`): Update all dataclasses to match v1.0.0
   schemas — new fields, renamed fields, enum value format change.
2. **AgentCard**: Replace flat `url` + `preferredTransport` with
   `supportedInterfaces` array of `AgentInterface` objects. Add
   `provider`, `securitySchemes`, `securityRequirements`, `signatures`,
   `documentationUrl` fields.
3. **Serialization**: All enums switch from lowercase (`"submitted"`) to
   `SCREAMING_SNAKE_CASE` with type prefix (`"TASK_STATE_SUBMITTED"`).
   A compatibility shim accepts both formats on deserialization.
4. **HTTP routes**: Add v1.0.0 REST-binding routes (`POST /message:send`,
   `GET /tasks/{id}`, `POST /tasks/{id}:cancel`, etc.) alongside existing
   routes. Existing routes become the v0.3 compatibility surface.
5. **JSON-RPC methods**: Implement all 11 v1.0.0 methods with PascalCase
   names (`SendMessage`, `GetTask`, `CancelTask`, etc.). Keep old
   `message/send` names as aliases for v0.3 clients.
6. **Version negotiation**: Read `A2A-Version` header from requests.
   Version `1.0` uses v1.0.0 serialization; empty/`0.3` uses legacy format.
   Unsupported versions return `VersionNotSupportedError` (-32009).
7. **Error codes**: Implement the A2A error code table with JSON-RPC
   numeric codes (-32001 through -32009).
8. **Well-Known URI**: Serve AgentCard at both `/.well-known/agent-card.json`
   (v1.0.0) and `/.well-known/agent.json` (v0.3 compat).
9. **Push notification config CRUD**: Implement the four push-notification
   management operations as capability-gated endpoints.
10. **Client upgrade**: `A2AClient` sends `A2A-Version: 1.0` header,
    deserializes v1.0.0 responses, falls back gracefully for v0.3 servers.

### Version Negotiation Strategy

```
Client Request
  ├── A2A-Version: 1.0 → v1.0 serialization (SCREAMING_SNAKE enums, supportedInterfaces)
  ├── A2A-Version: 0.3 → v0.3 serialization (lowercase enums, flat url + preferredTransport)
  ├── A2A-Version: <empty> → treated as 0.3 (per spec: "empty = 0.3")
  └── A2A-Version: 2.0 → VersionNotSupportedError (-32009)
```

### Component Diagram

```
                    ┌─────────────────────────────┐
                    │    A2AServer (server.py)     │
                    │                             │
  v1.0 routes ────→│  VersionNegotiationMixin     │
  v0.3 routes ────→│  ↓                          │
                    │  _serialize(obj, version)   │
                    │  ↓                          │
                    │  models.py (v1.0 models)    │
                    │  ↓                          │
                    │  PushNotificationStore      │
                    │  (in-memory / Redis)        │
                    └─────────────────────────────┘

                    ┌─────────────────────────────┐
                    │    A2AClient (client.py)     │
                    │                             │
                    │  Sends A2A-Version: 1.0     │
                    │  Deserializes v1.0 + v0.3   │
                    └─────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `A2AServer` (server.py) | modified | Add v1.0 routes, version negotiation, push config CRUD |
| `models.py` | modified | Update all dataclasses to v1.0.0 schema |
| `A2AClient` (client.py) | modified | Send version header, handle v1.0 responses |
| `A2AMeshDiscovery` (mesh.py) | modified | Parse v1.0 AgentCards |
| `A2AProxyRouter` (router.py) | modified | Forward version headers, handle v1.0 cards |
| `A2ASecurityMiddleware` (security.py) | unmodified | Existing auth unchanged; AgentCard exposes its config via securitySchemes |
| `A2ARemoteAgentTool` (client.py) | modified | Handle v1.0 task/message responses |
| `A2ARemoteSkillTool` (client.py) | modified | Handle v1.0 skill schema differences |

### Data Models

```python
# --- New / changed models for v1.0.0 ---

class TaskState(str, Enum):
    """Task lifecycle states — v1.0.0 ProtoJSON values."""
    UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"       # was CANCELLED (double-L)
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    REJECTED = "TASK_STATE_REJECTED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"  # NEW in v1.0

class Role(str, Enum):
    UNSPECIFIED = "ROLE_UNSPECIFIED"
    USER = "ROLE_USER"
    AGENT = "ROLE_AGENT"

@dataclass
class AgentInterface:
    """v1.0 AgentCard interface entry."""
    url: str
    protocol_binding: str   # "JSONRPC" | "GRPC" | "HTTP+JSON"
    protocol_version: str   # "1.0"
    tenant: Optional[str] = None

@dataclass
class AgentProvider:
    url: str
    organization: str

@dataclass
class AgentCapabilities:
    streaming: bool = True
    push_notifications: bool = False
    extended_agent_card: bool = False
    extensions: List[AgentExtension] = field(default_factory=list)

@dataclass
class AgentCard:
    name: str
    description: str
    version: str
    skills: List[AgentSkill]
    supported_interfaces: List[AgentInterface]  # replaces flat url
    capabilities: AgentCapabilities
    default_input_modes: List[str]
    default_output_modes: List[str]
    provider: Optional[AgentProvider] = None
    documentation_url: Optional[str] = None
    security_schemes: Optional[Dict[str, SecurityScheme]] = None
    security_requirements: Optional[List[SecurityRequirement]] = None
    signatures: Optional[List[AgentCardSignature]] = None
    icon_url: Optional[str] = None

@dataclass
class SendMessageConfiguration:
    accepted_output_modes: Optional[List[str]] = None
    task_push_notification_config: Optional[TaskPushNotificationConfig] = None
    history_length: Optional[int] = None
    return_immediately: bool = False

@dataclass
class TaskPushNotificationConfig:
    id: str
    task_id: str
    url: str
    authentication: Optional[AuthenticationInfo] = None
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class AuthenticationInfo:
    scheme: str           # e.g., "Bearer", "Basic"
    credentials: Optional[str] = None

# A2A Error model
@dataclass
class A2AError:
    code: int
    message: str
    data: Optional[Any] = None
```

### New Public Interfaces

```python
# Version-aware serialization (used by server and client)
def serialize_for_version(obj: Any, version: str = "1.0") -> Dict[str, Any]:
    """Serialize an A2A model to dict using the target protocol version."""

def deserialize_with_compat(data: Dict[str, Any]) -> Any:
    """Deserialize a dict, accepting both v0.3 and v1.0 enum formats."""

# Push notification config store
class PushNotificationStore:
    """In-memory store for TaskPushNotificationConfig (pluggable to Redis)."""
    async def create(self, config: TaskPushNotificationConfig) -> TaskPushNotificationConfig: ...
    async def get(self, task_id: str, config_id: str) -> Optional[TaskPushNotificationConfig]: ...
    async def list(self, task_id: str) -> List[TaskPushNotificationConfig]: ...
    async def delete(self, task_id: str, config_id: str) -> bool: ...
```

---

## 3. Module Breakdown

### Module 1: Data Model Upgrade
- **Path**: `packages/ai-parrot/src/parrot/a2a/models.py`
- **Responsibility**: Update all dataclasses to v1.0.0 schema. Add new types
  (`AgentInterface`, `AgentProvider`, `SendMessageConfiguration`,
  `TaskPushNotificationConfig`, `AuthenticationInfo`, `AgentExtension`,
  `AgentCardSignature`, `SecurityScheme`, `SecurityRequirement`, `A2AError`).
  Change enum values to `SCREAMING_SNAKE_CASE` with type prefix. Add
  `AUTH_REQUIRED` state. Rename `CANCELLED` → `CANCELED`. Add compat
  deserialization that accepts both v0.3 and v1.0 enum formats. Update
  `Part` model: rename `file_uri` → `url`, `file_bytes` → `raw`, add
  `filename` field. Update `Message` with `extensions`, `referenceTaskIds`.
  Update `AgentSkill` with `inputModes`, `outputModes`,
  `securityRequirements`. Add version-aware `to_dict(version=)` to all
  models.
- **Depends on**: none

### Module 2: AgentCard v1.0 Structure
- **Path**: `packages/ai-parrot/src/parrot/a2a/models.py` (AgentCard class)
- **Responsibility**: Replace flat `url` + `preferred_transport` with
  `supported_interfaces: List[AgentInterface]`. Add `provider`,
  `documentation_url`, `security_schemes`, `security_requirements`,
  `signatures` fields. Implement version-aware `to_dict(version=)`: v1.0
  emits `supportedInterfaces`, v0.3 emits flat `url` + `preferredTransport`.
  Keep backward-compat `from_dict()` that accepts both formats.
- **Depends on**: Module 1

### Module 3: A2AServer v1.0 Routes & Version Negotiation
- **Path**: `packages/ai-parrot-server/src/parrot/a2a/server.py`
- **Responsibility**: Add v1.0.0 REST-binding routes
  (`POST {base}/message:send`, `POST {base}/message:stream`,
  `GET {base}/tasks/{id}`, `POST {base}/tasks/{id}:cancel`,
  `POST {base}/tasks/{id}:subscribe`). Add well-known endpoint at
  `/.well-known/agent-card.json`. Read `A2A-Version` header to select
  serialization format. Implement v1.0 JSON-RPC method names
  (`SendMessage`, `SendStreamingMessage`, `GetTask`, `ListTasks`,
  `CancelTask`, `SubscribeToTask`, plus push notification CRUD,
  `GetExtendedAgentCard`). Implement A2A error code table
  (-32001 through -32009). Process `SendMessageConfiguration`
  (especially `historyLength`, `returnImmediately`). Add
  `Content-Type: application/a2a+json` to v1.0 responses.
- **Depends on**: Module 1, Module 2

### Module 4: Push Notification Config Store
- **Path**: `packages/ai-parrot-server/src/parrot/a2a/push_notifications.py` (new)
- **Responsibility**: In-memory `PushNotificationStore` for
  `TaskPushNotificationConfig` CRUD. Pluggable interface for Redis backend.
  Wired into `A2AServer` for the four push notification operations.
  SSRF validation stub for webhook URLs (reject private IPs).
- **Depends on**: Module 1

### Module 5: A2AClient v1.0 Upgrade
- **Path**: `packages/ai-parrot/src/parrot/a2a/client.py`
- **Responsibility**: Send `A2A-Version: 1.0` header on all requests.
  Detect server version from AgentCard format (presence of
  `supportedInterfaces` → v1.0, flat `url` → v0.3). Deserialize
  responses using compat layer (both enum formats). Update
  `discover()` to try `/.well-known/agent-card.json` first, fall back
  to `/.well-known/agent.json`. Add `cancel_task()` and push notification
  config methods.
- **Depends on**: Module 1, Module 2

### Module 6: Mesh & Router Compatibility
- **Path**: `packages/ai-parrot/src/parrot/a2a/mesh.py`,
  `packages/ai-parrot/src/parrot/a2a/router.py`
- **Responsibility**: Update `A2AMeshDiscovery` to parse v1.0 AgentCards
  (extract URL from `supportedInterfaces[0].url` when flat `url` is
  absent). Update `A2AProxyRouter` to forward `A2A-Version` header and
  generate v1.0-compatible aggregated AgentCard.
- **Depends on**: Module 2

### Module 7: Tests
- **Path**: `packages/ai-parrot/tests/test_a2a_v1_models.py` (new),
  `packages/ai-parrot-server/tests/unit/test_a2a_v1_server.py` (new),
  `packages/ai-parrot/tests/test_a2a_v1_client.py` (new)
- **Responsibility**: Unit tests for v1.0 model serialization/deserialization,
  version negotiation, route handling, error codes, push notification CRUD,
  and backward compatibility with v0.3 format.
- **Depends on**: Modules 1-6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_task_state_v1_values` | 1 | TaskState enum values are SCREAMING_SNAKE with prefix |
| `test_task_state_compat_deserialize` | 1 | Accepts both `"submitted"` and `"TASK_STATE_SUBMITTED"` |
| `test_role_v1_values` | 1 | Role enum values use ROLE_ prefix |
| `test_part_url_field` | 1 | Part uses `url` (not `file_uri`) and `raw` (not `file_bytes`) |
| `test_part_to_dict_v1` | 1 | Part.to_dict() uses v1.0 field names |
| `test_message_extensions_field` | 1 | Message has `extensions` and `referenceTaskIds` |
| `test_agent_card_v1_to_dict` | 2 | AgentCard emits `supportedInterfaces` array |
| `test_agent_card_v03_to_dict` | 2 | AgentCard.to_dict(version="0.3") emits flat `url` |
| `test_agent_card_from_dict_v1` | 2 | Parses v1.0 card with `supportedInterfaces` |
| `test_agent_card_from_dict_v03` | 2 | Parses v0.3 card with flat `url` |
| `test_agent_card_security_schemes` | 2 | SecuritySchemes serialized in card |
| `test_v1_route_message_send` | 3 | `POST /a2a/message:send` works |
| `test_v1_route_task_cancel` | 3 | `POST /a2a/tasks/{id}:cancel` works |
| `test_version_header_negotiation` | 3 | Version header selects serialization |
| `test_version_not_supported_error` | 3 | Unknown version returns -32009 |
| `test_jsonrpc_v1_method_names` | 3 | PascalCase method names work |
| `test_jsonrpc_v03_compat` | 3 | Old `message/send` names still work |
| `test_a2a_error_codes` | 3 | Correct JSON-RPC codes for each error type |
| `test_push_config_crud` | 4 | Create/Get/List/Delete push notification config |
| `test_client_sends_version_header` | 5 | A2AClient sends A2A-Version: 1.0 |
| `test_client_discover_v1_endpoint` | 5 | Client tries agent-card.json first |
| `test_well_known_agent_card_json` | 3 | `/.well-known/agent-card.json` serves card |

### Integration Tests

| Test | Description |
|---|---|
| `test_v1_roundtrip` | Client (v1.0) → Server (v1.0) → full task lifecycle |
| `test_v03_client_v1_server` | v0.3 client talks to v1.0 server via negotiation |
| `test_v1_client_v03_server` | v1.0 client talks to v0.3 server via fallback |
| `test_streaming_v1_events` | SSE events use v1.0 serialization |

### Test Data / Fixtures

```python
@pytest.fixture
def v1_agent_card_data():
    return {
        "name": "TestAgent",
        "description": "Test",
        "version": "1.0",
        "supportedInterfaces": [{
            "url": "https://agent.example.com/a2a",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0"
        }],
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{"id": "chat", "name": "Chat", "description": "Chat", "tags": []}]
    }

@pytest.fixture
def v03_agent_card_data():
    return {
        "name": "TestAgent",
        "description": "Test",
        "version": "1.0",
        "url": "https://agent.example.com/a2a",
        "preferredTransport": "JSONRPC",
        "protocolVersion": "0.3.0",
        "capabilities": {"streaming": True},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{"id": "chat", "name": "Chat", "description": "Chat", "tags": []}]
    }
```

---

## 5. Acceptance Criteria

- [ ] All models serialize to v1.0.0 ProtoJSON format by default (SCREAMING_SNAKE_CASE enums, camelCase fields)
- [ ] `TaskState` includes `AUTH_REQUIRED`; `CANCELLED` renamed to `CANCELED` (single-L per v1.0)
- [ ] `AgentCard.to_dict()` emits `supportedInterfaces` array (not flat `url`)
- [ ] `AgentCard.to_dict(version="0.3")` emits flat `url` + `preferredTransport` for backward compat
- [ ] Well-known endpoint served at `/.well-known/agent-card.json` (v1.0) and `/.well-known/agent.json` (v0.3 compat)
- [ ] Server reads `A2A-Version` header; `1.0` → v1.0 serialization; empty/`0.3` → v0.3 serialization
- [ ] Unsupported version returns `VersionNotSupportedError` (JSON-RPC -32009, HTTP 400)
- [ ] v1.0 REST routes registered: `POST /message:send`, `POST /message:stream`, `GET /tasks/{id}`, `POST /tasks/{id}:cancel`, `POST /tasks/{id}:subscribe`
- [ ] JSON-RPC handler supports all 11 v1.0 method names (PascalCase)
- [ ] JSON-RPC handler still accepts old v0.3 method names (`message/send`, `tasks/get`, `tasks/list`)
- [ ] All A2A errors use the v1.0 error code table (-32001 to -32009) with correct HTTP status codes
- [ ] `SendMessageConfiguration` is parsed and `historyLength` / `returnImmediately` are respected
- [ ] Push notification config CRUD operations implemented (Create/Get/List/Delete)
- [ ] `A2AClient` sends `A2A-Version: 1.0` header on all requests
- [ ] `A2AClient.discover()` tries `/.well-known/agent-card.json` first, falls back to `/.well-known/agent.json`
- [ ] `A2AClient` correctly deserializes both v1.0 and v0.3 AgentCards
- [ ] `A2AMeshDiscovery` and `A2AProxyRouter` handle v1.0 AgentCards
- [ ] `Part` model uses `url` (not `file_uri`) and `raw` (not `file_bytes`) with backward-compat deserialization
- [ ] v1.0 responses use `Content-Type: application/a2a+json`
- [ ] Existing v0.3 tests continue to pass (backward compatibility)
- [ ] All new unit tests pass (`pytest packages/ai-parrot/tests/test_a2a_v1*.py -v`)
- [ ] All new integration tests pass

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.

### Verified Imports

```python
# Models — all from parrot.a2a.models
from parrot.a2a.models import (
    AgentCard,         # verified: models.py:332
    AgentSkill,        # verified: models.py:282
    AgentCapabilities, # verified: models.py:309
    AgentConfig,       # verified: models.py:11
    Task,              # verified: models.py:231
    TaskState,         # verified: models.py:20
    TaskStatus,        # verified: models.py:172
    Message,           # verified: models.py:99
    Part,              # verified: models.py:38
    Artifact,          # verified: models.py:191
    Role,              # verified: models.py:31
    RegisteredAgent,   # verified: models.py:427
)

# Server
from parrot.a2a.server import A2AServer       # verified: server.py:50
from parrot.a2a.server import A2AEnabledMixin  # verified: server.py:1266

# Client
from parrot.a2a.client import A2AClient            # verified: client.py:39
from parrot.a2a.client import A2AAgentConnection   # verified: client.py:28
from parrot.a2a.client import A2ARemoteAgentTool   # verified: client.py:452
from parrot.a2a.client import A2ARemoteSkillTool   # verified: client.py:604

# Mesh & Router
from parrot.a2a.mesh import A2AMeshDiscovery       # verified: mesh.py:136
from parrot.a2a.router import A2AProxyRouter       # verified: router.py:189
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/a2a/models.py

class TaskState(str, Enum):                      # line 20
    SUBMITTED = "submitted"                      # line 22
    WORKING = "working"                          # line 23
    COMPLETED = "completed"                      # line 24
    FAILED = "failed"                            # line 25
    CANCELLED = "cancelled"                      # line 26
    INPUT_REQUIRED = "input_required"            # line 27
    REJECTED = "rejected"                        # line 28
    # NOTE: no AUTH_REQUIRED state

class Role(str, Enum):                           # line 31
    USER = "user"                                # line 33
    AGENT = "agent"                              # line 34
    # NOTE: no UNSPECIFIED value

class Part:                                      # line 38
    text: Optional[str] = None                   # line 40
    file_uri: Optional[str] = None               # line 41 — v1.0 renames to `url`
    file_bytes: Optional[bytes] = None           # line 42 — v1.0 renames to `raw`
    file_media_type: Optional[str] = None        # line 43
    data: Optional[Dict[str, Any]] = None        # line 44
    metadata: Optional[Dict[str, Any]] = None    # line 45
    # NOTE: no `filename` field (v1.0 adds it)

    def to_dict(self) -> Dict[str, Any]:         # line 55
    @classmethod
    def from_dict(cls, d: Dict) -> "Part":       # line 81

class Message:                                   # line 99
    message_id: str                              # line 101
    role: Role                                   # line 102
    parts: List[Part]                            # line 103
    context_id: Optional[str] = None             # line 104
    task_id: Optional[str] = None                # line 105
    metadata: Optional[Dict] = None              # line 106
    # NOTE: no `extensions` or `referenceTaskIds` fields

class AgentCapabilities:                         # line 309
    streaming: bool = True                       # line 311
    push_notifications: bool = False             # line 312
    state_transition_history: bool = False       # line 313
    # NOTE: no `extended_agent_card` or `extensions` fields

class AgentCard:                                 # line 332
    name: str                                    # line 334
    description: str                             # line 335
    version: str                                 # line 336
    skills: List[AgentSkill]                     # line 337
    url: Optional[str] = None                    # line 338 — v1.0 removes
    capabilities: AgentCapabilities              # line 339
    default_input_modes: List[str]               # line 340
    default_output_modes: List[str]              # line 341
    protocol_version: str = "0.3.0"             # line 345 — hardcoded v0.3
    preferred_transport: str = "JSONRPC"         # line 349 — v1.0 removes
    icon_url: Optional[str] = None               # line 350

…(truncated)…
