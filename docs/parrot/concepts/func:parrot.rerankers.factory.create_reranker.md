---
type: Concept
title: create_reranker()
id: func:parrot.rerankers.factory.create_reranker
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Instantiate a reranker from a config dict.
---

# create_reranker

```python
def create_reranker(config: dict, *, bot_llm_client: Optional['AbstractClient']=None) -> Optional[AbstractReranker]
```

Instantiate a reranker from a config dict.

Args:
    config: Reranker config (typically loaded from
        ``navigator.ai_bots.reranker_config``). An empty dict means
        "no reranker" and returns ``None``.
    bot_llm_client: Reused for ``type=llm`` when ``client_ref="bot"``
        (avoids a second LLM client instantiation).

Returns:
    The reranker instance, or ``None`` if config is empty.

Raises:
    ConfigError: If ``config['type']`` is missing or unknown, or if a
        required dependency (e.g. LLM client) is absent.

Examples:
    >>> create_reranker({})
    None
    >>> create_reranker({"type": "local_cross_encoder",
    ...                   "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ...                   "device": "cpu"})  # doctest: +ELLIPSIS
    <parrot.rerankers.local.LocalCrossEncoderReranker object at 0x...>
