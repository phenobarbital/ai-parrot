---
title: User Memory
summary: Independent knowledge, provenance, correction and suppression
---

# User Memory

## Purpose

The user memory subsystem provides durable, correctable knowledge about users across sessions, independent of episodic recording. It enables agents to learn, recall, and manage user-specific facts, preferences, goals, and constraints without requiring episodic memory to be enabled.

Key features:
- Cross-session persistence of user knowledge
- Independent validity and provenance tracking
- Explicit correction and suppression mechanisms
- Context-specific knowledge management
- No dependency on episodic memory

## Public API

### Core Classes

- [`UserMemoryStore`](ref:parrot.memory.user.store.UserMemoryStore) — Main storage and retrieval interface
- [`UserKnowledge`](ref:parrot.memory.user.models.UserKnowledge) — User knowledge model
- [`UserKnowledgeCandidate`](ref:parrot.memory.user.models.UserKnowledgeCandidate) — Extracted knowledge candidate
- [`UserKnowledgeCommand`](ref:parrot.memory.user.models.UserKnowledgeCommand) — Knowledge operation command
- [`UserMemoryReceipt`](ref:parrot.memory.user.models.UserMemoryReceipt) — Operation receipt

### Models

- [`UserKnowledge`](ref:parrot.memory.user.models.UserKnowledge) — Main knowledge model
- [`UserKnowledgeCandidate`](ref:parrot.memory.user.models.UserKnowledgeCandidate) — Candidate for persistence
- [`UserKnowledgeCommand`](ref:parrot.memory.user.models.UserKnowledgeCommand) — Operation command
- [`UserMemoryReceipt`](ref:parrot.memory.user.models.UserMemoryReceipt) — Operation result

### Extraction

- [`extract_user_knowledge`](ref:parrot.memory.user.extraction.extract_user_knowledge) — Extract knowledge from events

## Configuration & Parameters

### UserKnowledge Model

The `UserKnowledge` model includes the following fields:

| Field | Type | Description |
|---|---|---|
| `knowledge_id` | `str` | Stable unique identifier |
| `tenant_id` | `str` | Tenant identifier |
| `agent_id` | `str` | Agent identifier |
| `user_id` | `str` | User identifier |
| `kind` | `Literal["fact", "preference", "goal", "constraint"]` | Knowledge type |
| `normalized_key` | `str | None` | Normalized key for lookup |
| `context_key` | `str` | Context-specific key |
| `provenance` | `str` | Provenance information |
| `status` | `Literal["active", "pending", "superseded", "invalidated"]` | Current status |
| `created_at` | `datetime` | Creation timestamp |
| `updated_at` | `datetime` | Last update timestamp |
| `confirmed_at` | `datetime | None` | Confirmation timestamp |
| `valid_from` | `datetime | None` | Valid from timestamp |
| `expires_at` | `datetime | None` | Expiration timestamp |
| `revision` | `int` | Revision number |
| `supersedes_id` | `str | None` | ID of superseded knowledge |
| `payload` | `dict[str, Any]` | Additional data |

### UserKnowledgeCandidate Model

The `UserKnowledgeCandidate` model includes:

| Field | Type | Description |
|---|---|---|
| `kind` | `Literal["fact", "preference", "goal", "constraint"]` | Knowledge type |
| `normalized_key` | `str | None` | Normalized key |
| `context_key` | `str` | Context-specific key |
| `value` | `str` | Knowledge value |
| `provenance` | `str` | Provenance information |
| `evidence_refs` | `tuple[str, ...]` | Evidence references |
| `metadata` | `dict[str, Any]` | Additional metadata |

### Store Configuration

The `UserMemoryStore` is configured with:

| Parameter | Type | Description |
|---|---|---|
| `path` | `Path` | Path to SQLite database |
| `evidence_tenant_resolver` | `Callable | None` | Optional evidence tenant resolver |

## Usage Examples

### Basic Store Usage

```python
from pathlib import Path
from parrot.memory.user.store import UserMemoryStore
from parrot.memory.agent_memory.models import MemoryRequestScope

store = UserMemoryStore(Path("/path/to/memory.db"))
await store.configure()

# Recall user knowledge
scope = MemoryRequestScope(
    tenant_id="default",
    agent_id="my-agent",
    user_id="user123",
    session_id="session456",
    turn_id="turn789",
    identity_provenance="server_resolved"
)

knowledge = await store.recall("user preferences", scope=scope, limit=5)

# List all user knowledge
all_knowledge = await store.list(scope=scope, limit=100)

await store.close()
```

### Knowledge Extraction

```python
from parrot.memory.user.extraction import extract_user_knowledge
from parrot.memory.agent_memory.models import MemoryEvent
from parrot.clients.base import AbstractClient

# Create a mock client
class MockClient(AbstractClient):
    async def complete(self, prompt: str, **kwargs: Any) -> str:
        return "Extracted knowledge"

client = MockClient()

event = MemoryEvent(
    event_id="event123",
    kind="user_knowledge",
    scope=scope,
    observed_at=datetime.now(timezone.utc),
    evidence_refs=(),
    payload={"text": "User mentioned they prefer dark mode"}
)

candidates = await extract_user_knowledge(event, client=client)
```

### Managing User Knowledge

```python
from parrot.memory.user.models import UserKnowledgeCommand

# Correct user knowledge
command = UserKnowledgeCommand(
    kind="preference",
    normalized_key="theme",
    context_key="general",
    value="light",
    provenance="user_correction",
    expected_revision=1
)

receipt = await store.correct(command, scope=scope)

# Forget user knowledge
forget_command = UserKnowledgeCommand(
    kind="preference",
    normalized_key="theme",
    context_key="general",
    value="",
    provenance="user_request",
    expected_revision=2
)

forget_receipt = await store.forget(forget_command, scope=scope)
```

## Gotchas

### Independence from Episodic Memory

- User memory works completely independently of episodic memory
- Enabling user memory doesn't require episodic memory to be enabled
- User knowledge is stored in separate tables in the same SQLite database

### Identity and Scope

- User knowledge is scoped by `(tenant_id, agent_id, user_id)`
- Missing or anonymous user identity prevents knowledge operations
- Session information is used for provenance, not identity

### Validity and Status

- Knowledge has explicit validity periods (`valid_from`, `expires_at`)
- Status can be `active`, `pending`, `superseded`, or `invalidated`
- Explicit confirmation is required for inferred knowledge

### Conflict Resolution

- Most recent explicit declaration wins on conflict
- Superseded knowledge is kept as history, not served
- Suppression markers prevent re-learning from retained evidence

### Evidence and Provenance

- Evidence references are validated before persistence
- Provenance distinguishes caller-supplied identity from anonymous defaults
- Cross-scope evidence references are rejected

### Physical Erasure

- Forget operations write suppression markers by default
- Physical deletion policy is governed by separate retention rules
- Only explicit user requests can lift suppression markers

## Related

### Wiki Pages

- [Agent Memory](agent-memory.md) — Architecture, flags, lifecycle, scope and hard-cut migration
- [Memory Dynamics](memory-dynamics.md) — Accepted gates, evidence, backends, CLI/MCP/export and measured limits
- [Conversation Memory](conversation-memory.md) — How conversation history is stored and managed

### External References

- [FEAT-892 Specification](../../specs/agent-memory-mixin.spec.md) — Full feature specification
- [FEAT-889 Agent Brain](../../specs/agent-brain.spec.md) — Brain service and knowledge promotion
- [FEAT-571 Memory Dynamics](../../specs/memory-dynamics.spec.md) — Historical dynamics policies

### Ownership

- User memory models and store are owned by FEAT-892
- Knowledge extraction and validation policies are governed by accepted gates
- Physical erasure and retention policies are separately managed
