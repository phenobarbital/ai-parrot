---
type: Wiki Summary
title: parrot.memory.unified.routing
id: mod:parrot.memory.unified.routing
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: CrossDomainRouter for multi-agent memory sharing.
relates_to:
- concept: class:parrot.memory.unified.routing.AgentExpertise
  rel: defines
- concept: class:parrot.memory.unified.routing.CrossDomainRouter
  rel: defines
---

# `parrot.memory.unified.routing`

CrossDomainRouter for multi-agent memory sharing.

Ports the cross-domain routing logic from AgentCoreMemory into a standalone
component for the UnifiedMemoryManager. Enables agents to discover other
agents whose expertise is semantically relevant to a given query and include
their memories (with a decay factor) in the results.

Agent expertise embeddings are computed on-the-fly from domain descriptions
and cached in-memory. Tenant boundaries are strictly enforced.

## Classes

- **`AgentExpertise(BaseModel)`** — Registry entry for an agent's domain expertise.
- **`CrossDomainRouter(BaseModel)`** — Routes memory queries to relevant agent namespaces for multi-agent sharing.
