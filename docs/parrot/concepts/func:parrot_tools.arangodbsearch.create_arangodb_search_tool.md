---
type: Concept
title: create_arangodb_search_tool()
id: func:parrot_tools.arangodbsearch.create_arangodb_search_tool
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Factory function to create ArangoDB search tool with embedding support.
---

# create_arangodb_search_tool

```python
async def create_arangodb_search_tool(connection_params: Optional[Dict]=None, embedding_model: Optional[str]=None, **kwargs) -> ArangoDBSearchTool
```

Factory function to create ArangoDB search tool with embedding support.

Args:
    connection_params: ArangoDB connection parameters
    embedding_model: Hugging Face model name for embeddings
    **kwargs: Additional tool configuration

Returns:
    Configured ArangoDBSearchTool instance
