---
type: Wiki Summary
title: parrot_tools.arangodbsearch
id: mod:parrot_tools.arangodbsearch
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ArangoDB Vector Search Tool for AI-Parrot Framework.
relates_to:
- concept: class:parrot_tools.arangodbsearch.ArangoDBSearchTool
  rel: defines
- concept: class:parrot_tools.arangodbsearch.ArangoSearchArgs
  rel: defines
- concept: class:parrot_tools.arangodbsearch.SearchType
  rel: defines
- concept: func:parrot_tools.arangodbsearch.create_arangodb_search_tool
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot_tools.arangodbsearch`

ArangoDB Vector Search Tool for AI-Parrot Framework.

Provides comprehensive search capabilities including:
- Vector similarity search
- Full-text search (BM25)
- Hybrid search (combining vector + text)
- Graph traversal and context enrichment

## Classes

- **`SearchType(str, Enum)`** — Supported search types.
- **`ArangoSearchArgs(BaseModel)`** — Arguments schema for ArangoDB search operations.
- **`ArangoDBSearchTool(AbstractTool)`** — ArangoDB Vector Search Tool.

## Functions

- `async def create_arangodb_search_tool(connection_params: Optional[Dict]=None, embedding_model: Optional[str]=None, **kwargs) -> ArangoDBSearchTool` — Factory function to create ArangoDB search tool with embedding support.
