---
type: Wiki Entity
title: UnifiedMemoryManager
id: class:parrot.memory.unified.manager.UnifiedMemoryManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Coordinates episodic memory, skill registry, and conversation memory.
---

# UnifiedMemoryManager

Defined in [`parrot.memory.unified.manager`](../summaries/mod:parrot.memory.unified.manager.md).

```python
class UnifiedMemoryManager
```

Coordinates episodic memory, skill registry, and conversation memory.

All retrieval in ``get_context_for_query`` runs concurrently via
``asyncio.gather``.  Subsystems that are ``None`` are silently skipped.

When ``cross_domain_router`` is provided, ``get_context_for_query`` also
queries episodic memories from relevant agent namespaces identified by the
router. Cross-domain results are labeled and appended to the episodic
warnings text. Cross-domain failures never break the main retrieval flow.

Args:
    namespace: Scoping dimensions for episodic memory queries.
    conversation_memory: Optional conversation history store.
    episodic_store: Optional episodic memory store.
    skill_registry: Optional skill registry (duck-typed via SkillRegistry
        protocol).
    config: Optional memory configuration; defaults to ``MemoryConfig()``.
    cross_domain_router: Optional router for multi-agent memory sharing.

Example:
    manager = UnifiedMemoryManager(
        namespace=MemoryNamespace(agent_id="my-agent"),
        episodic_store=store,
        cross_domain_router=router,
    )
    ctx = await manager.get_context_for_query("user query", "u1", "s1")
    prompt += ctx.to_prompt_string()

## Methods

- `async def configure(self, **kwargs: Any) -> None` — Initialise all non-None subsystems.
- `async def cleanup(self) -> None` — Release resources held by all non-None subsystems.
- `async def get_context_for_query(self, query: str, user_id: str, session_id: str) -> MemoryContext` — Retrieve and assemble context from all memory subsystems.
- `async def record_interaction(self, query: str, response: Any, tool_calls: list[Any], user_id: str, session_id: str) -> None` — Record a completed interaction to episodic and conversation memory.
