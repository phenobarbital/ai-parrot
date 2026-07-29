---
type: Concept
title: create_wiki_store()
id: func:parrot.knowledge.wiki.store.create_wiki_store
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Instantiate the configured wiki retrieval-plane backend.
---

# create_wiki_store

```python
def create_wiki_store(storage_dir: str | Path, wiki_name: str='', backend: str='sqlite') -> BaseWikiStore
```

Instantiate the configured wiki retrieval-plane backend.

Selection is explicit (``WikiConfig.storage_backend``) — there is no
silent fallback: a broken/unavailable backend is a hard error.

Args:
    storage_dir: Wiki storage root.  ``sqlite`` uses
        ``{storage_dir}/wiki.db``; ``memory`` uses the OKF bundle
        directory ``{storage_dir}/pages/``.
    wiki_name: Wiki name recorded by the backend.
    backend: ``"sqlite"`` (single-file SQLite plane) or
        ``"memory"`` (in-memory indexes + OKF markdown directory).

Returns:
    A :class:`BaseWikiStore` implementation.

Raises:
    ValueError: For an unknown ``backend`` value.
