# TASK-516: UnifiedMemoryManager Cross-Domain Routing

**Feature**: refactor-episodic-agentcorememory
**Spec**: `sdd/specs/refactor-episodic-agentcorememory.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-514, TASK-515
**Assigned-to**: unassigned

---

## Context

Module 7 from the spec. Wires `CrossDomainRouter` into `UnifiedMemoryManager.get_context_for_query()`. When a router is present and query matches other agents' expertise, the manager expands the search to include memories from those agents (with decay factor applied), then merges and deduplicates results.

---

## Scope

- Add `cross_domain_router: CrossDomainRouter | None` parameter to `UnifiedMemoryManager.__init__()`
- In `get_context_for_query()`:
  - If router is present, call `find_relevant_agents()` with the query embedding
  - For each relevant agent, retrieve episodic warnings from their namespace
  - Apply decay factor to cross-domain scores
  - Merge with local results, deduplicate by episode_id
  - Respect token budget (cross-domain results share the episodic_weight budget)
- If router is None, preserve current behavior exactly
- Write tests

**NOT in scope**: Modifying `ContextAssembler`. Changing `MemoryConfig`. Adding routing to the mixin.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/unified/manager.py` | MODIFY | Add cross_domain_router parameter and routing logic |
| `tests/unit/memory/unified/test_manager_routing.py` | CREATE | Tests for cross-domain routing in manager |
| `parrot/memory/unified/__init__.py` | MODIFY | Ensure CrossDomainRouter is exported |

---

## Implementation Notes

### Integration Pattern
```python
class UnifiedMemoryManager:
    def __init__(
        self,
        ...,
        cross_domain_router: CrossDomainRouter | None = None,
    ):
        self._cross_domain_router = cross_domain_router

    async def get_context_for_query(self, query, user_id=None, session_id=None):
        # ... existing retrieval ...
        
        if self._cross_domain_router and self._episodic_store:
            try:
                query_embedding = await self._episodic_store._embedding_provider.embed(query)
                relevant_agents = await self._cross_domain_router.find_relevant_agents(
                    query_embedding, 
                    self._namespace.agent_id,
                    self._episodic_store._embedding_provider,
                    tenant_id=self._namespace.tenant_id,
                )
                for agent_id in relevant_agents:
                    cross_ns = MemoryNamespace(
                        tenant_id=self._namespace.tenant_id,
                        agent_id=agent_id,
                    )
                    cross_warnings = await self._episodic_store.get_failure_warnings(
                        query, namespace=cross_ns, max_warnings=2
                    )
                    # Append with [cross-domain] label
                    ...
            except Exception as e:
                self.logger.warning("Cross-domain routing failed: %s", e)
```

### Key Constraints
- Cross-domain routing is completely optional — None router = zero behavior change
- Must not block the main retrieval path — use `asyncio.gather()` for concurrent cross-domain fetches
- Cross-domain failures must never break the main flow (catch and log)
- Token budget: cross-domain results share the episodic allocation, not a separate budget

### References in Codebase
- `parrot/memory/unified/manager.py` — current implementation to modify
- `parrot/memory/unified/routing.py` — CrossDomainRouter (TASK-514)
- `parrot/memory/unified/context.py` — ContextAssembler (do not modify)
- `parrot/memory/unified/models.py` — MemoryNamespace, MemoryConfig

---

## Acceptance Criteria

- [ ] `UnifiedMemoryManager` accepts optional `cross_domain_router`
- [ ] When router returns relevant agents, their memories are included in context
- [ ] Cross-domain results are labeled as such in the context string
- [ ] Cross-domain failures are caught and logged without breaking main flow
- [ ] Default behavior (None router) is unchanged
- [ ] All existing manager tests still pass
- [ ] All tests pass: `pytest tests/unit/memory/unified/test_manager_routing.py -v`

---

## Test Specification

```python
# tests/unit/memory/unified/test_manager_routing.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.routing import CrossDomainRouter
from parrot.memory.episodic.models import MemoryNamespace


@pytest.fixture
def mock_episodic_store():
    store = AsyncMock()
    store.get_failure_warnings = AsyncMock(return_value="Warning from agent-b")
    store._embedding_provider = AsyncMock()
    store._embedding_provider.embed = AsyncMock(return_value=[0.1] * 384)
    return store


@pytest.fixture
def mock_router():
    router = AsyncMock(spec=CrossDomainRouter)
    router.find_relevant_agents = AsyncMock(return_value=["agent-b"])
    router.cross_domain_decay = 0.6
    return router


class TestManagerCrossDomainRouting:
    async def test_routing_includes_cross_domain(self, mock_episodic_store, mock_router):
        ns = MemoryNamespace(agent_id="agent-a", tenant_id="t1")
        manager = UnifiedMemoryManager(
            namespace=ns,
            episodic_store=mock_episodic_store,
            cross_domain_router=mock_router,
        )
        context = await manager.get_context_for_query("test query")
        mock_router.find_relevant_agents.assert_called_once()

    async def test_no_router_no_cross_domain(self, mock_episodic_store):
        ns = MemoryNamespace(agent_id="agent-a", tenant_id="t1")
        manager = UnifiedMemoryManager(
            namespace=ns,
            episodic_store=mock_episodic_store,
        )
        context = await manager.get_context_for_query("test query")
        # Should work fine without router

    async def test_router_failure_graceful(self, mock_episodic_store, mock_router):
        mock_router.find_relevant_agents = AsyncMock(side_effect=Exception("fail"))
        ns = MemoryNamespace(agent_id="agent-a", tenant_id="t1")
        manager = UnifiedMemoryManager(
            namespace=ns,
            episodic_store=mock_episodic_store,
            cross_domain_router=mock_router,
        )
        # Should not raise
        context = await manager.get_context_for_query("test query")
        assert context is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-516-unified-manager-routing.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: All 10 tests pass. cross_domain_router optional param added. Routing in _get_episodic_warnings with asyncio.gather for concurrent cross-domain fetches. All failures caught and logged.

**Deviations from spec**: none
