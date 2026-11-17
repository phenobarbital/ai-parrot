---
id: FC-015
query_id: Q031
type: grep
intent: "AgentRegistry decorator signature for registering a new agent kind."
executed_at: 2026-11-07T01:24:35Z
duration_ms: 800
parent_id: null
depth: 0
---

# FC-015 — register_agent is agent_registry.register_bot_decorator; AgentRegistry.register(name, factory: Type[AbstractBot], ...)

## Summary

`packages/ai-parrot/src/parrot/registry/registry.py:302` defines `AgentRegistry`; `parrot/registry/__init__.py:12` aliases `register_agent = agent_registry.register_bot_decorator`, used as `@register_agent(name="MySpecialAgent", priority=10)` (docstring at 317) or `@register_agent(name="CriticalAgent", at_startup=True, startup_config={...})` (1425). The imperative form `AgentRegistry.register(self, name, factory: Type[AbstractBot], *, singleton, tags, priority, dependencies, replace, at_startup, ...)` (570-580). Registration requires an `AbstractBot` subclass — a verdict/expert agent would be a bot class, i.e. an in-process server-side concept, whereas the SDD flow's "agents" (`sdd-worker`, `code-reviewer`) are Claude Code markdown agents in `.claude/agents/`. The brainstorm's "EscrowAgent registered in AgentRegistry" and "external verdict agent launched like sdd-worker" are two different runtimes.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/__init__.py`
  lines: 12-19
  symbol: `register_agent`
  excerpt: |
    register_agent = agent_registry.register_bot_decorator  # type: ignore
        "register_agent",

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 302-317
  symbol: `AgentRegistry`
  excerpt: |
    class AgentRegistry:
        - register_agent decorator: declarative registration on class definition
            @register_agent(name="MySpecialAgent", priority=10)

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 570-580
  symbol: `AgentRegistry.register`
  excerpt: |
        def register(
            self,
            name: str,
            factory: Type[AbstractBot],
            *,
            singleton: bool = False,
            tags: Optional[Iterable[str]] = None,
            priority: int = 0,
            dependencies: Optional[List[str]] = None,
            replace: bool = False,
            at_startup: bool = False,

## Notes

- `.claude/agents/` contains 16 markdown agents (sdd-worker, code-reviewer, sdd-secondopinion, qa-runner, sdd-qa, sdd-feedback…) — the Claude-Code-native runtime for an escrow verdict agent would be a new `.claude/agents/sdd-escrow.md` (+ Codex twin), not an `AgentRegistry` bot.
