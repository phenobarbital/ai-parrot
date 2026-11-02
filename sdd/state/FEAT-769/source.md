---
kind: inline
jira_key: null
fetched_at: 2026-10-29T00:00:00Z
summary_oneline: "Create a couple of runnable example agents under examples/agents/semantic that use the FEAT-704 Semantic Layer"
---

# Source (inline, user request)

> `/sdd-proposal semantic-layer-example -- Vamos a crear a partir de FEAT-704 un par de
> ejemplos en /examples/agents/semantic de un par de agentes haciendo uso de Semantic Layer`

Translation / reading:

Starting from FEAT-704 (the governed semantic layer, distribution `ai-parrot-semantic`),
create a pair of **example agents** under `examples/agents/semantic/` that demonstrate real
use of the Semantic Layer.

Implied requirements:
- Examples live in the repo's `examples/` tree (currently `examples/agents/` has no `semantic/`
  subdirectory).
- "a couple of agents" → at least two distinct examples, presumably exercising different
  surfaces / governance postures of the semantic layer.
- Deliverable is example code (+ the YAML model/policy fixtures and a README they need),
  not new library functionality.
