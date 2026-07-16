---
type: Concept
title: load_store_router_config()
id: func:parrot.registry.routing.yaml_loader.load_store_router_config
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Load a ``StoreRouterConfig`` from a YAML file or a pre-parsed dict.
---

# load_store_router_config

```python
def load_store_router_config(path_or_dict: Union[_PathLike, dict]) -> StoreRouterConfig
```

Load a ``StoreRouterConfig`` from a YAML file or a pre-parsed dict.

Scalar fields present in the source override the Pydantic model defaults.
``custom_rules`` from the source are appended to (not replacing) any rules
already present in the defaults — following the precedence pattern of
``IntentRouterConfig.custom_keywords``.

On any error (missing file, malformed YAML, Pydantic validation failure)
the function logs the problem and returns ``StoreRouterConfig()`` (all
defaults).  It **never** raises.

Args:
    path_or_dict: Either a filesystem path (``str`` or :class:`pathlib.Path`)
        pointing to a YAML file, or a pre-parsed ``dict`` containing
        override values.

Returns:
    A fully-validated ``StoreRouterConfig``.
