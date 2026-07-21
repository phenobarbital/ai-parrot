---
type: Concept
title: get_embedding_models()
id: func:parrot.embeddings.catalog.get_embedding_models
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the curated list of embedding models, optionally filtered.
---

# get_embedding_models

```python
def get_embedding_models(provider: Optional[str]=None, use_case: Optional[str]=None, metric: Optional[str]=None, max_dims: Optional[int]=None, hnsw_compatible: Optional[bool]=None, requires_prefix: Optional[bool]=None) -> List[Dict[str, Any]]
```

Return the curated list of embedding models, optionally filtered.

All active filters compose with AND semantics — only entries satisfying
every non-``None`` filter are returned.

Args:
    provider: Filter by provider name (``"huggingface"``, ``"openai"``,
        ``"google"``). If ``None``, no provider filtering is applied.
    use_case: Filter by use case tag (``"similarity"``, ``"retrieval"``,
        ``"clustering"``, ``"multilingual"``, ``"code"``, ``"qa"``,
        ``"long-context"``, ``"instruct"``, ``"asymmetric"``,
        ``"symmetric"``). If ``None``, no use-case filtering is applied.
    metric: Filter by recommended similarity metric (``"cosine"``,
        ``"dot"``, ``"l2"``). If ``None``, no metric filtering is applied.
    max_dims: Keep only models whose ``dimension <= max_dims``.
        If ``None``, no dimension cap is applied.
    hnsw_compatible: If ``True``, return only models whose
        ``hnsw_compatible`` flag is ``True`` (dimension <= 2000 for
        pgvector HNSW). If ``False``, return only non-HNSW-compatible
        models. If ``None``, no filtering on this field.
    requires_prefix: If ``True``, return only prefix-requiring models.
        If ``False``, return only models that do not require prefixes.
        If ``None``, no filtering on this field.

Returns:
    List of embedding model descriptor dicts satisfying all active filters.
