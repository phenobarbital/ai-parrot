---
id: F002
query_id: Q002
type: read
intent: Understand NODE_REGISTRY registration for adding a new node type
executed_at: 2026-09-21T22:06:00Z
depth: 0
parent_id: null
---

# F002 — NODE_REGISTRY registration mechanism

## Summary

`register_node(name)(cls)` in `parrot.bots.flows.flow.flow` registers a Node subclass into the global `NODE_REGISTRY` dict. It validates that `cls` is a `Node` subclass and raises on duplicate names. The plan module's `ensure_tool_node_registered` is the idempotent wrapper pattern. A delegate would register as `register_node("delegate")(DelegateToolNode)` following the same pattern.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
  lines: 196-204
  symbol: `register_node.decorator`
  excerpt: |
    def decorator(cls: Type[Node]) -> Type[Node]:
        if not (isinstance(cls, type) and issubclass(cls, Node)):
            raise TypeError(f"@register_node({name!r}) target must be a Node subclass")
        if name in NODE_REGISTRY:
            raise ValueError(f"Node type {name!r} already registered to {NODE_REGISTRY[name].__name__}")
        NODE_REGISTRY[name] = cls
        if config_model is not None:
            NODE_CONFIG_MODELS[name] = config_model
        return cls

- path: `packages/ai-parrot/src/parrot/bots/flows/plan/compile.py`
  lines: 33
  symbol: `PLAN_NODE_TYPE`
  excerpt: |
    PLAN_NODE_TYPE = "tool"

## Notes

The `NODE_CONFIG_MODELS` dict is a secondary registry for config model classes. A `DelegateToolNode` could register `DelegateNode` (the Pydantic model for the plan-language shape) there for introspection. The `register_node` call also appears in `dev_loop/nodes/base.py` (`register_dev_loop_node`) and `flows/thales/nodes/registry.py`, confirming it is the standard pattern.
