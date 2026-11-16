---
title: Agent Memory
summary: Architecture, flags, lifecycle, scope and hard-cut migration
---

# Agent Memory

## Purpose

The `AgentMemoryMixin` provides a unified integration for persistent memory capabilities in AI Parrot agents. It consolidates episodic memory and user knowledge into a single lifecycle adapter, eliminating duplicate context and recording paths. This mixin is designed to work with the `UnifiedMemoryManager`, which orchestrates memory operations while stores retain ownership of persistence and dynamics.

Key responsibilities:
- One preparation/finalization path for persistent memory in `ask`, `ask_stream`, and `invoke`
- Independent control of user memory and episodic memory capabilities
- Hard-cut migration from legacy mixins (`EpisodicMemoryMixin` and `LongTermMemoryMixin`)
- Integration with `BrainService` for tenant-bound recall and derivative forgetting

## Public API

### Core Classes

- [`AgentMemoryMixin`](ref:parrot.memory.agent_memory.mixin) — Main integration point for agent memory
- [`AgentMemoryConfig`](ref:parrot.memory.agent_memory.models) — Configuration for memory capabilities
- [`MemoryRequestScope`](ref:parrot.memory.agent_memory.models) — Immutable runtime-derived identity
- [`UnifiedMemoryManager`](ref:parrot.memory.unified.manager) — Memory operation orchestrator

### Configuration

- [`AgentMemoryConfig`](ref:parrot.memory.agent_memory.models) — Main configuration class

### Toolkit

- [`AgentMemoryToolkit`](ref:parrot.memory.agent_memory.toolkit) — Exposes scoped memory operations

## Configuration & Parameters

### AgentMemoryConfig

The `AgentMemoryConfig` class controls all memory capabilities with the following fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `enable_episodic_memory` | `bool` | `False` | Enable episodic memory storage and retrieval |
| `enable_user_memory` | `bool` | `False` | Enable user knowledge storage and retrieval |
| `enable_brain` | `bool` | `False` | Enable BrainService integration (requires `enable_episodic_memory`; without an episodic store `configure` raises `invalid_configuration`) |
| `memory_dynamics` | `bool` | `False` | Enable dynamics (reviews, state tracking) |
| `max_context_tokens` | `int` | `2000` | Maximum tokens for memory context (ge=0) |
| `episodic_context_tokens` | `int` | `600` | Tokens budget for episodic memory |
| `user_context_tokens` | `int` | `600` | Tokens budget for user knowledge |
| `user_memory_priority` | `Literal["high", "normal"]` | `"high"` | Priority for user memory in context |
| `brain_context_tokens` | `int` | `400` | Tokens budget for brain recall |
| `skills_context_tokens` | `int` | `400` | Tokens budget for skills context |
| `include_relevant_skills` | `bool` | `False` | Include relevant skills in context |
| `episodic_backend` | `Literal["sqlite"]` | `"sqlite"` | Backend for episodic storage |
| `storage_path` | `str | None` | `None` | Path to SQLite database |
| `enable_reflection` | `bool` | `True` | Enable automatic reflection generation |
| `max_episodic_warnings` | `int` | `3` | Maximum warnings to include (ge=0) |
| `suppress_trivial_tools` | `bool` | `True` | Suppress trivial tool calls |
| `flush_on_startup` | `bool` | `False` | Flush memory on startup |

### Configuration Precedence

1. Explicit instance capability flags and overrides of fields declared by memory-aware subclasses (highest priority)
2. Explicit `agent_memory_config` dict or `AgentMemoryConfig` object
3. Plain class attributes from subclasses of `AgentMemoryMixin`; unrelated MRO parents and descriptors are ignored
4. Default values from `AgentMemoryConfig` (lowest priority)

Generic host fields such as `storage_path` and `max_context_tokens` should be placed in
`agent_memory_config`; unrelated host instance attributes cannot silently configure memory.

### Background extraction and evidence

Completed response writes that extract user knowledge run as owned background tasks. Cleanup and
reconfiguration drain them before closing memory resources. Each extraction gets a fresh client
constructed from the host's resolved LLM configuration, with no shared response-client session.
For a custom live client instance, set `memory_extraction_client_factory` on the host to a callable
that returns a new independently owned client for each extraction (use `staticmethod` for a class
attribute). Without that factory, automatic extraction is unavailable; episodic recording continues.

ChatStorage-backed evidence also needs a trusted metadata resolver. Pass
`evidence_tenant_resolver=` to `create_memory_manager`, or set the host's
`memory_evidence_tenant_resolver`. The async callable receives `ChatStorageEvidenceRef` and returns
the stored tenant for a live turn, or `None` for missing/tombstoned evidence. The host must connect
this callable to its authoritative storage service; the factory does not infer evidence authority
from the reference itself. Missing resolvers and tenant mismatches reject the knowledge write.

`memory_status` reports the backend's review state. SQLite reviews commit transactionally and
report zero pending reviews only after verifying storage availability. Unsupported backends report
an unknown pending count (`null`); `memory_sync` does not claim synchronization for unknown or
degraded storage. It does not replay already committed reviews.

### Legacy Flag Migration

The old `enable_long_term_memory` flag has been removed. Use the new independent flags:
- `enable_episodic_memory` for episodic memory
- `enable_user_memory` for user knowledge

## Usage Examples

### Basic Agent Configuration

`BasicAgent` already inherits `AgentMemoryMixin`, so the flags are set directly on it. Listing the mixin again as a base
(`class MyAgent(AgentMemoryMixin, BasicAgent)`) raises `TypeError: Cannot create a consistent method resolution order`.
Use the mixin as an explicit base only for a host class that does not already include it.

```python
from parrot.bots import BasicAgent

class MyAgent(BasicAgent):
    enable_episodic_memory = True
    enable_user_memory = True
    agent_memory_config = {
        "max_context_tokens": 1500,
        "episodic_context_tokens": 500,
        "user_context_tokens": 500,
    }

agent = MyAgent(name="my-agent")
```

### Using the Mixin

```python
from datetime import datetime, timezone

from parrot.memory.agent_memory.models import MemoryRequestScope

# Prepare memory context
scope = MemoryRequestScope(
    tenant_id="default",
    agent_id="my-agent",
    user_id="user123",
    session_id="session456",
    turn_id="turn789",
    identity_provenance="server_resolved"
)

memory_context = await agent.prepare_memory("user query", scope=scope)

# Record an event
from parrot.memory.agent_memory.models import MemoryEvent

event = MemoryEvent(
    event_id="event123",
    kind="response",
    scope=scope,
    observed_at=datetime.now(timezone.utc),
    evidence_refs=(),
    payload={}
)

await agent.complete_memory(event)
```

### Brain Service Integration

```python
class MyAgent(BasicAgent):
    enable_episodic_memory = True
    enable_brain = True  # requires enable_episodic_memory

# The brain service is constructed lazily from the sibling FEAT-889 module and started on configure().
# Access it through agent.brain_service; if that module is unavailable, configure() raises invalid_configuration.
```

## Gotchas

### Hard-Cut Migration

- The old `EpisodicMemoryMixin` and `LongTermMemoryMixin` have been removed without compatibility shims
- Existing code using these mixins must be updated to use `AgentMemoryMixin`
- Persisted data from the old mixins is preserved but must be accessed through the new interfaces

### Brain Service Limitations

- `enable_brain=True` requires `enable_episodic_memory=True`: the config does not switch episodic memory on for you, and `configure()` raises `invalid_configuration` when the brain has no episodic store
- The brain service is constructed lazily and requires an episodic store
- Brain operations are tenant-bound and use the server-resolved request tenant
- No agent-side `BrainAdminToolkit` is registered; administrative operations go through the HTTP handler

### Configuration Constraints

- `enable_user_memory=False` stops automatic learning and recall but doesn't delete existing data
- Explicit forget operations are required to remove user knowledge
- User memory works independently of episodic memory

### Scope and Identity

- `MemoryRequestScope` is immutable and runtime-bound
- Missing or anonymous identity prevents user profile operations
- Tenant and agent IDs are required; user/session/room/crew/model IDs are optional
- Scope is applied before top-k selection in all retrieval operations
- An episode is recorded under the full request scope (user and session included), but automatic episodic recall is wider than one session. A request recalls:
  - an identified user: that user's episodes from every session;
  - an anonymous request with a session: that session's episodes that carry no user;
  - always: agent-level episodes, recorded with neither a user nor a session (explicit lessons and episodes that predate request scoping).
- The agent-facing `search_episodic_memory` and `get_warnings` tools follow the same visibility inside a request; `get_warnings` reads the identified user's failures only. Outside a request they use the toolkit's configured namespace.
- Another user's episodes are never recalled. Set room, crew and model dimensions keep narrowing every recall.
- Agent-level recall needs a backend that can match an unset dimension: SQLite, pgvector and FAISS can; the Redis backend returns no agent-level episodes.

### Dynamics and Reviews

- Memory dynamics (reviews, state tracking) is disabled by default
- Reviews require delivered version, attribution, and verified outcome
- Recall/citation alone doesn't reinforce memory
- Review identity is the exact request namespace: an episode recalled from another session, or from the agent level, is delivered as context only (`episodic_context:` in `delivered_refs`) and cannot be cited or reviewed
- Synthetic evidence is rejected; only verified outcomes produce reviews

## Related

### Wiki Pages

- [User Memory](user-memory.md) — Independent knowledge, provenance, correction and suppression
- [Memory Dynamics](memory-dynamics.md) — Accepted gates, evidence, backends, CLI/MCP/export and measured limits
- [Conversation Memory](conversation-memory.md) — How conversation history is stored and managed

### External References

- [FEAT-892 Specification](https://github.com/phenobarbital/ai-parrot/blob/main/sdd/specs/agent-memory-mixin.spec.md) — Full feature specification
- [FEAT-889 Agent Brain](https://github.com/phenobarbital/ai-parrot/blob/main/sdd/specs/agent-brain.spec.md) — Brain service and administrative interfaces (phase 2)
- [FEAT-571 Memory Dynamics](https://github.com/phenobarbital/ai-parrot/blob/main/sdd/specs/memory-dynamics.spec.md) — Historical dynamics specification

### Ownership

- `AgentMemoryMixin` and related classes are owned by FEAT-892
- `BrainService` and administrative interfaces are owned by FEAT-889
- Persisted data migration and CLI/MCP contracts are separately governed
