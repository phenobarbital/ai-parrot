# TASK-514: CrossDomainRouter

**Feature**: refactor-episodic-agentcorememory
**Spec**: `sdd/specs/refactor-episodic-agentcorememory.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 5 from the spec. Ports the cross-domain routing logic from `AgentCoreMemory` into a standalone component for the UnifiedMemoryManager. This enables multi-agent memory sharing — when an agent queries memory, the router identifies other agents whose expertise is semantically relevant and includes their memories (with a decay factor) in the results.

Per the open questions resolution: agent expertise embeddings are **computed on-the-fly** from recent episodes, not persisted.

---

## Scope

- Implement `CrossDomainRouter` class:
  - `register_agent_expertise(agent_id, domain_description)`: Store domain description for an agent
  - `find_relevant_agents(query_embedding, current_agent_id, embedding_provider)`: Return list of agent IDs whose expertise is semantically similar above threshold
  - Expertise embeddings computed on-the-fly by embedding domain descriptions
  - Apply configurable similarity threshold (default 0.5) and decay factor (default 0.6)
  - Exclude current agent from results
  - Respect tenant_id boundaries (agents in different tenants never share)
- Use Pydantic BaseModel for configuration
- Write unit tests

**NOT in scope**: Wiring into UnifiedMemoryManager (TASK-516). Persisting expertise to database.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/unified/routing.py` | CREATE | CrossDomainRouter implementation |
| `tests/unit/memory/unified/test_routing.py` | CREATE | Unit tests |
| `parrot/memory/unified/__init__.py` | MODIFY | Export CrossDomainRouter |

---

## Implementation Notes

### Pattern to Follow
```python
from pydantic import BaseModel, Field
from parrot.memory.episodic.embedding import EpisodeEmbeddingProvider

class AgentExpertise(BaseModel):
    agent_id: str
    tenant_id: str
    domain_description: str
    embedding: list[float] | None = None  # computed on-the-fly

class CrossDomainRouter(BaseModel):
    similarity_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    cross_domain_decay: float = Field(default=0.6, ge=0.0, le=1.0)
    _registry: dict[str, AgentExpertise] = {}
```

### Key Constraints
- Cosine similarity for matching (normalize embeddings, dot product)
- Embeddings computed lazily via `EpisodeEmbeddingProvider.embed()` on first `find_relevant_agents()` call per agent
- Cache computed embeddings in-memory (they only change if domain_description changes)
- Thread-safe: use asyncio.Lock for registry mutations
- `tenant_id` is a hard boundary — never return agents from different tenants

### References in Codebase
- `parrot/memory/core.py` — `_route_cross_domain()` method, `register_agent_expertise()` — source to port
- `parrot/memory/episodic/embedding.py` — `EpisodeEmbeddingProvider` for embedding computation
- `parrot/memory/unified/models.py` — `MemoryConfig` for configuration patterns

---

## Acceptance Criteria

- [ ] `CrossDomainRouter` registers agent expertise with domain descriptions
- [ ] `find_relevant_agents()` returns relevant agent IDs above similarity threshold
- [ ] Current agent is excluded from results
- [ ] Tenant boundaries are respected (cross-tenant sharing impossible)
- [ ] Decay factor applied to cross-domain scores
- [ ] Embeddings computed on-the-fly and cached
- [ ] All tests pass: `pytest tests/unit/memory/unified/test_routing.py -v`
- [ ] Imports work: `from parrot.memory.unified.routing import CrossDomainRouter`

---

## Test Specification

```python
# tests/unit/memory/unified/test_routing.py
import pytest
from unittest.mock import AsyncMock
from parrot.memory.unified.routing import CrossDomainRouter


@pytest.fixture
def mock_embedding_provider():
    provider = AsyncMock()
    # Return different embeddings for different texts
    async def embed(text):
        if "weather" in text.lower():
            return [1.0, 0.0, 0.0] + [0.0] * 381
        elif "finance" in text.lower():
            return [0.0, 1.0, 0.0] + [0.0] * 381
        else:
            return [0.5, 0.5, 0.0] + [0.0] * 381
    provider.embed = embed
    return provider


@pytest.fixture
def router():
    return CrossDomainRouter(similarity_threshold=0.5, cross_domain_decay=0.6)


class TestCrossDomainRouter:
    async def test_find_relevant_agents(self, router, mock_embedding_provider):
        router.register_agent_expertise("weather-agent", "t1", "Weather forecasting and climate data")
        router.register_agent_expertise("finance-agent", "t1", "Financial analysis and trading")
        
        query_embedding = [0.9, 0.1, 0.0] + [0.0] * 381  # weather-like
        agents = await router.find_relevant_agents(
            query_embedding, "other-agent", mock_embedding_provider, tenant_id="t1"
        )
        assert "weather-agent" in agents

    async def test_excludes_current_agent(self, router, mock_embedding_provider):
        router.register_agent_expertise("agent-a", "t1", "General purpose")
        agents = await router.find_relevant_agents(
            [0.5, 0.5, 0.0] + [0.0] * 381, "agent-a", mock_embedding_provider, tenant_id="t1"
        )
        assert "agent-a" not in agents

    async def test_tenant_isolation(self, router, mock_embedding_provider):
        router.register_agent_expertise("agent-t1", "tenant1", "Weather")
        router.register_agent_expertise("agent-t2", "tenant2", "Weather")
        agents = await router.find_relevant_agents(
            [1.0, 0.0, 0.0] + [0.0] * 381, "other", mock_embedding_provider, tenant_id="tenant1"
        )
        assert "agent-t2" not in agents

    def test_decay_factor(self, router):
        assert router.cross_domain_decay == 0.6
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-514-cross-domain-router.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: All 19 unit tests pass. Pydantic BaseModel with arbitrary_types_allowed. Tenant boundary enforced. Embeddings computed lazily and cached. Thread-safe via asyncio.Lock.

**Deviations from spec**: none
