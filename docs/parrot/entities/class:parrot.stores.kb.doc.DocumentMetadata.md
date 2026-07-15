---
type: Wiki Entity
title: DocumentMetadata
id: class:parrot.stores.kb.doc.DocumentMetadata
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Knowledge Base for document metadata and indexing.
relates_to:
- concept: class:parrot.stores.kb.redis.RedisKnowledgeBase
  rel: extends
---

# DocumentMetadata

Defined in [`parrot.stores.kb.doc`](../summaries/mod:parrot.stores.kb.doc.md).

```python
class DocumentMetadata(RedisKnowledgeBase)
```

Knowledge Base for document metadata and indexing.

## Methods

- `async def search(self, query: str, user_id: Optional[str]=None, **kwargs) -> List[Dict[str, Any]]` — Search document metadata.
- `async def add_document(self, doc_id: str, user_id: str, title: str, filename: str, description: str='', tags: List[str]=None, **metadata) -> bool` — Add document metadata.
- `async def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]` — Get a specific document's metadata.
- `async def delete_document(self, doc_id: str) -> bool` — Delete a document's metadata.
- `async def list_user_documents(self, user_id: str, limit: int=100) -> List[Dict[str, Any]]` — List all documents for a specific user.
- `async def search_by_tags(self, tags: List[str], user_id: Optional[str]=None, match_all: bool=False) -> List[Dict[str, Any]]` — Search documents by tags.
