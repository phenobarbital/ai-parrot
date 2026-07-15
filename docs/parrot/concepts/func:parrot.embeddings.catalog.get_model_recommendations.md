---
type: Concept
title: get_model_recommendations()
id: func:parrot.embeddings.catalog.get_model_recommendations
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return per-model retrieval recommendations from the catalog.
---

# get_model_recommendations

```python
def get_model_recommendations(model_name: Optional[str]) -> Optional[Dict[str, Any]]
```

Return per-model retrieval recommendations from the catalog.

Provides default ``score_threshold`` and ``search_limit`` values that
consumers (chatbots, RAG pipelines, vector-store handlers) should use
when the operator has not configured them explicitly. The global
fallback of ``0.7`` is too aggressive for several models — e.g.
``multi-qa-mpnet-base-cos-v1`` produces scores in the 0.30-0.55 range
and would silently return empty result sets.

Args:
    model_name: HuggingFace model identifier or provider model ID.
        ``None`` or unknown names return ``None``.

Returns:
    A dict with keys ``recommended_score_threshold`` (float) and
    ``recommended_search_limit`` (int) when ``model_name`` matches a
    catalog entry; ``None`` otherwise.
