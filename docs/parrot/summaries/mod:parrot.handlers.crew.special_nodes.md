---
type: Wiki Summary
title: parrot.handlers.crew.special_nodes
id: mod:parrot.handlers.crew.special_nodes
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Curated special-node catalog for the crew builder UI.
relates_to:
- concept: class:parrot.handlers.crew.special_nodes.CrewSpecialNodeCatalogHandler
  rel: defines
---

# `parrot.handlers.crew.special_nodes`

Curated special-node catalog for the crew builder UI.

Exposes the list of "special nodes" — crew members that are not LLM agents
(e.g. the deterministic tool-execution node). The frontend uses this
catalog to present non-agent node types when composing a crew.

Mirrors the curated-catalog pattern of ``tool_catalog.py``: entries are
hand-picked and carry display metadata plus a JSON-Schema-ish
``config_schema`` fragment describing the node's configuration.

Route:
    GET /api/v1/crew/special_nodes

## Classes

- **`CrewSpecialNodeCatalogHandler(BaseView)`** — Returns the curated special-node catalog for the crew builder UI.
