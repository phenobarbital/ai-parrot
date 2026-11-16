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
| `tenant_id` / `agent_id` / `user_id` | `str` | Scope the knowledge belongs to |
| `kind` | `Literal["fact", "preference", "goal", "constraint"]` | Knowledge type |
| `normalized_key` | `str | None` | Normalized key for lookup |
| `value` | `Any` | The stored value |
| `context` | `dict[str, str]` | Context qualifiers (for example a project) |
| `provenance` | `Literal["explicit", "inferred"]` | Whether the user said it directly or it was inferred |
| `evidence_refs` | `tuple[str, ...]` | Evidence references backing the knowledge |
| `status` | `Literal["active", "pending", "superseded", "invalidated"]` | Current status |
| `created_at` / `updated_at` | `datetime` | Timestamps |
| `confirmed_at` | `datetime | None` | Confirmation timestamp |
| `valid_from` / `expires_at` | `datetime | None` | Validity window |
| `revision` | `int` | Revision number (compare-and-swap) |
| `supersedes_id` | `str | None` | ID of the superseded knowledge |

### UserKnowledgeCandidate Model

The `UserKnowledgeCandidate` model includes:

| Field | Type | Description |
|---|---|---|
| `kind` | `Literal["fact", "preference", "goal", "constraint"]` | Knowledge type |
| `value` | `Any` | Knowledge value |
| `provenance` | `Literal["explicit", "inferred"]` | How the claim was obtained |
| `evidence_refs` | `tuple[str, ...]` | Evidence references (required) |
| `context` | `dict[str, str]` | Context qualifiers |
| `normalized_key` | `str | None` | Normalized key |
| `valid_from` / `expires_at` | `datetime | None` | Optional validity window |

### UserKnowledgeCommand Model

| Field | Type | Description |
|---|---|---|
| `event_id` | `str` | Idempotency identity of the originating event |
| `knowledge_id` | `str | None` | Existing knowledge to act on |
| `expected_revision` | `int | None` | Revision the caller saw (compare-and-swap) |
| `candidate` | `UserKnowledgeCandidate | None` | The claim for `upsert` / `correct` |
| `operation` | `Literal["upsert", "correct", "forget"]` | Defaults to `upsert` |
| `evidence_refs` | `tuple[str, ...]` | Evidence references |

`UserMemoryReceipt` reports `knowledge_id`, `revision` and a `status` of `applied`, `duplicate`, `conflict`, `ignored` or `storage_unavailable`.

### Store Configuration

The `UserMemoryStore` is configured with:

| Parameter | Type | Description |
|---|---|---|
| `path` | `Path` | Path to SQLite database |
| `evidence_tenant_resolver` | `Callable | None` | Optional metadata-only ChatStorage tenant resolver; required for `chatstorage/...` evidence to be accepted |

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
from datetime import datetime, timezone

from parrot.memory.user.extraction import extract_user_knowledge
from parrot.memory.agent_memory.models import MemoryEvent

# `client` is the agent's configured AbstractClient (any provider client works);
# extract_user_knowledge makes one bounded extraction call through it.

event = MemoryEvent(
    event_id="event123",
    kind="user_knowledge",
    scope=scope,
    observed_at=datetime.now(timezone.utc),
    evidence_refs=(),
    payload={"text": "User mentioned they prefer dark mode"}
)

candidates = await extract_user_knowledge(event, client=client)  # -> list[UserKnowledgeCandidate]
```

Extraction only proposes candidates; it never selects the scope and never persists anything.

### Managing User Knowledge

```python
from parrot.memory.user.models import UserKnowledgeCandidate, UserKnowledgeCommand

existing = (await store.recall("theme", scope=scope, limit=1))[0]

# Correct user knowledge (compare-and-swap on the revision you read; the correction must be explicit and keep the same
# kind/key/context, otherwise the receipt is `conflict`)
candidate = UserKnowledgeCandidate(
    kind="preference",
    normalized_key="theme",
    value="light",
    provenance="explicit",
    evidence_refs=existing.evidence_refs,
    context=existing.context,  # a correction keeps the same claim: kind, key and context
)
command = UserKnowledgeCommand(
    event_id="event-correct-1",
    knowledge_id=existing.knowledge_id,
    expected_revision=existing.revision,
    candidate=candidate,
    operation="correct",
    evidence_refs=candidate.evidence_refs,
)
receipt = await store.correct(command, scope=scope)

# Forget user knowledge (writes a suppression marker)
forget_command = UserKnowledgeCommand(
    event_id="event-forget-1",
    knowledge_id=receipt.knowledge_id,  # the corrected record; the old one is now superseded
    expected_revision=receipt.revision,
    operation="forget",
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
- An `explicit` candidate is admitted `active`; an `inferred` one is admitted `pending`, and `recall` returns only active, currently valid facts

### Conflict Resolution

- Most recent explicit declaration wins on conflict
- Superseded knowledge is kept as history, not served
- Suppression markers prevent re-learning from retained evidence

### Evidence and Provenance

- `provenance` is `explicit` (the user said it directly) or `inferred`; for extracted candidates the extraction model chooses the label, so treat it as a model assertion, not verified authority
- `chatstorage/...` evidence references are validated before persistence: malformed, cross-scope and tombstoned ones are rejected (see the next bullet); other reference schemes are stored as given
- `chatstorage/...` evidence references fail closed: a command carrying one is `ignored` unless the store was built with an `evidence_tenant_resolver` that confirms the stored tenant matches the scope (malformed, cross-scope and tombstoned references are ignored too); other reference schemes are not resolved

### Physical Erasure

- `forget` runs in one transaction: it deletes the whole claim chain (superseded revisions included) and its event rows, with `PRAGMA secure_delete=ON`, and writes a suppression marker that holds only hashes (no content)
- Events that never produced a fact (ignored or suppressed) keep a payload digest, not the claim content
- A suppression marker is lifted by an `explicit` candidate that brings at least one evidence reference not already blocked; because the extractor labels provenance, that label alone is not proof of an explicit user request
- `user_derivative_forgets` records the source episodes for derivative invalidation; nothing in this feature reads it yet (FEAT-889 consumes it)

## Related

### Wiki Pages

- [Agent Memory](agent-memory.md) — Architecture, flags, lifecycle, scope and hard-cut migration
- [Memory Dynamics](memory-dynamics.md) — Accepted gates, evidence, backends, CLI/MCP/export and measured limits
- [Conversation Memory](conversation-memory.md) — How conversation history is stored and managed

### External References

- [FEAT-892 Specification](../../sdd/specs/agent-memory-mixin.spec.md) — Full feature specification
- [FEAT-889 Agent Brain](../../sdd/specs/agent-brain.spec.md) — Brain service and knowledge promotion
- [FEAT-571 Memory Dynamics](../../sdd/specs/memory-dynamics.spec.md) — Historical dynamics policies

### Ownership

- User memory models and store are owned by FEAT-892
- Knowledge extraction and validation policies are governed by accepted gates
- Physical erasure is implemented here (see Physical Erasure); retention of other stores is governed separately
