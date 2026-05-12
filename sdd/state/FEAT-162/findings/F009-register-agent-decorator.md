---
id: F009
query_id: Q009
type: grep
intent: Locate register_agent decorator usage and definition.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F009 — `register_agent` is the alias for `agent_registry.register_bot_decorator`

## Summary

`from parrot.registry import register_agent` resolves to
`agent_registry.register_bot_decorator` (`parrot/registry/__init__.py:12`),
which is defined at `parrot/registry/registry.py:1130`. Signature accepts
`name`, `priority`, `dependencies`, `singleton`, `tags`, and `**kwargs` (which
absorbs `at_startup`, `startup_config`, etc.). It enforces that the decorated
class is a subclass of `AbstractBot`. Used by `SecurityAgent` already.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/__init__.py`
  lines: 12
  symbol: alias
  excerpt: |
    register_agent = agent_registry.register_bot_decorator  # type: ignore

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1130-1156
  symbol: register_bot_decorator
  excerpt: |
    def register_bot_decorator(
        self,
        name: Optional[str] = None,
        priority: int = 0,
        dependencies: Optional[List[str]] = None,
        singleton: bool = False,
        tags: Optional[List[str]] = None,
        **kwargs
    ):
        def _decorator(cls: Type[AbstractBot]) -> Type[AbstractBot]:
            if not issubclass(cls, AbstractBot):
                raise TypeError("@register_agent can only be used on AbstractBot subclasses.")

- path: `agents/security.py`
  lines: 84-86
  symbol: existing usage
  excerpt: |
    @register_agent(name="security_agent", at_startup=True)
    class SecurityAgent(Agent):
        agent_id: str = "security_agent"

## Notes

- `at_startup=True` is consumed via `**kwargs` — no change needed to the spec.
