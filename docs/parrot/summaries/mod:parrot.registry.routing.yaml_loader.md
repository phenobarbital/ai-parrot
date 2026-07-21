---
type: Wiki Summary
title: parrot.registry.routing.yaml_loader
id: mod:parrot.registry.routing.yaml_loader
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: YAML override loader for ``StoreRouterConfig`` (FEAT-111 Module 2).
relates_to:
- concept: func:parrot.registry.routing.yaml_loader.load_store_router_config
  rel: defines
- concept: mod:parrot.registry.routing.models
  rel: references
---

# `parrot.registry.routing.yaml_loader`

YAML override loader for ``StoreRouterConfig`` (FEAT-111 Module 2).

Merges hardcoded Pydantic defaults with per-agent YAML overrides using
the same precedence semantics as ``IntentRouterConfig.custom_keywords``.

Usage::

    from parrot.registry.routing import load_store_router_config

    cfg = load_store_router_config("/path/to/router.yaml")
    cfg = load_store_router_config({"top_n": 3, "margin_threshold": 0.20})

## Functions

- `def load_store_router_config(path_or_dict: Union[_PathLike, dict]) -> StoreRouterConfig` — Load a ``StoreRouterConfig`` from a YAML file or a pre-parsed dict.
