---
type: Wiki Entity
title: CrossDomainRouter
id: class:parrot.memory.unified.routing.CrossDomainRouter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Routes memory queries to relevant agent namespaces for multi-agent sharing.
---

# CrossDomainRouter

Defined in [`parrot.memory.unified.routing`](../summaries/mod:parrot.memory.unified.routing.md).

```python
class CrossDomainRouter(BaseModel)
```

Routes memory queries to relevant agent namespaces for multi-agent sharing.

Maintains an in-memory registry of agent expertise descriptions. When
``find_relevant_agents()`` is called, it embeds each registered agent's
domain description (lazily, then cached) and computes cosine similarity
with the query embedding. Agents above the similarity threshold (excluding
the current agent and different tenants) are returned.

The ``cross_domain_decay`` factor is available to callers for weighting
cross-domain results lower than same-agent results.

Args:
    similarity_threshold: Minimum cosine similarity for an agent to be
        considered relevant. Default 0.5.
    cross_domain_decay: Decay factor to apply to cross-domain results.
        Default 0.6. (Callers apply this; router does not modify scores.)
    max_relevant_agents: Maximum number of agents to return. Default 2.

## Methods

- `def model_post_init(self, __context: Any) -> None` — Initialize the private registry after Pydantic model init.
- `def register_agent_expertise(self, agent_id: str, tenant_id: str, domain_description: str) -> None` — Register or update an agent's domain expertise.
- `def list_registered_agents(self) -> list[str]` — Return list of registered agent IDs.
- `async def find_relevant_agents(self, query_embedding: list[float], current_agent_id: str, embedding_provider: Any, tenant_id: str) -> list[str]` — Find agents whose expertise is semantically relevant to the query.
