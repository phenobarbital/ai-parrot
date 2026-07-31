---
type: Wiki Summary
title: parrot.handlers.knowledge
id: mod:parrot.handlers.knowledge
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP handler to manage an agent's knowledge index (PageIndex / GraphIndex).
relates_to:
- concept: class:parrot.handlers.knowledge.AgentKnowledgeHandler
  rel: defines
- concept: mod:parrot.bots
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot_loaders.docx
  rel: references
---

# `parrot.handlers.knowledge`

HTTP handler to manage an agent's knowledge index (PageIndex / GraphIndex).

This handler exposes a REST surface to upload, edit, delete and query the
documents that feed an agent's **PageIndex** (hierarchical, vectorless ToC
tree) and/or **GraphIndex** (knowledge graph), and to test the agent's LLM via
``ask_stream`` over HTTP chunked transfer encoding.

Routes (registered in ``manager/manager.py``)::

    GET    /api/v1/agents/knowledge/{agent_id}            -> index status / list trees
    GET    /api/v1/agents/knowledge/{agent_id}/search     -> query the index (JSON)
    GET    /api/v1/agents/knowledge/{agent_id}/ask        -> ask_stream (chunked)
    PUT    /api/v1/agents/knowledge/{agent_id}            -> upload new files
    POST   /api/v1/agents/knowledge/{agent_id}            -> edit existing content
    DELETE /api/v1/agents/knowledge/{agent_id}            -> delete node / tree

Index selection: ``?index=pageindex|graphindex`` (default ``pageindex``).
Tree selection : ``?tree=<tree_name>`` (default ``pageindex``).

PageIndex supports the full file lifecycle. GraphIndex supports **query** and
**upload** (when the agent exposes a ``GraphIndexBuilder`` + ``TenantContext``);
per-file edit/delete return ``501 Not Implemented`` because the GraphIndex
toolkit has no document-level edit/delete primitives.

## Classes

- **`AgentKnowledgeHandler(BaseView)`** — Manage an agent's PageIndex / GraphIndex documents over REST.
