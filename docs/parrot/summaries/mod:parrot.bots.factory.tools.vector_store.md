---
type: Wiki Summary
title: parrot.bots.factory.tools.vector_store
id: mod:parrot.bots.factory.tools.vector_store
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Provision a PgVector table for a RAG agent.
relates_to:
- concept: func:parrot.bots.factory.tools.vector_store.provision_vector_store
  rel: defines
- concept: mod:parrot.stores.postgres
  rel: references
- concept: mod:parrot.tools.decorators
  rel: references
---

# `parrot.bots.factory.tools.vector_store`

Provision a PgVector table for a RAG agent.

Builders call ``provision_vector_store`` after the LLM has chosen a table
name, schema and embedding dimension. The function creates the table via
``PgVectorStore.create_embedding_table`` and returns a ``StoreConfig`` block
ready to embed in the resulting ``AgentDefinition``.

## Functions

- `async def provision_vector_store(table: str, *, schema: str='public', dimension: int=768, embedding_model: str='sentence-transformers/all-mpnet-base-v2', extra_columns: Optional[List[str]]=None, dsn: Optional[str]=None) -> Dict[str, Any]` — Create a PgVector table and return a ``StoreConfig``-shaped dict.
