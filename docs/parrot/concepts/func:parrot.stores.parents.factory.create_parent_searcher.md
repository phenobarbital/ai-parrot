---
type: Concept
title: create_parent_searcher()
id: func:parrot.stores.parents.factory.create_parent_searcher
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Instantiate a parent searcher from a config dict.
---

# create_parent_searcher

```python
def create_parent_searcher(config: dict, *, store: Optional['AbstractStore']) -> Optional[AbstractParentSearcher]
```

Instantiate a parent searcher from a config dict.

Args:
    config: Parent searcher config (from
        ``navigator.ai_bots.parent_searcher_config``). Empty dict
        returns ``None``.
    store: The bot's already-configured store; required for
        ``type=in_table`` because ``InTableParentSearcher`` queries the
        same table where chunks live.  Pass ``None`` only if you are
        certain no store-dependent type is used (empty config).

Returns:
    The parent searcher instance, or ``None`` if config is empty.

Raises:
    ConfigError: If ``config['type']`` is missing or unknown, or
        ``store`` is ``None`` when required by the chosen type.

Examples:
    >>> create_parent_searcher({}, store=my_store)
    None
    >>> create_parent_searcher({"type": "in_table"}, store=my_store)
    <InTableParentSearcher ...>
