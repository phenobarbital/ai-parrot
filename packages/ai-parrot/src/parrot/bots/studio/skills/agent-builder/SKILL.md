---
name: agent-builder
description: How to scaffold a Python agent from the base-class catalog, or create a simple YAML-defined agent
triggers:
  - build an agent
  - create an agent
  - scaffold an agent
  - new agent
category: agent-development
---

# Agent Builder

Two paths to a new agent — pick the simpler one whenever it satisfies the
request.

## Path A — Simple agent (no custom code)

Use `list_agent_base_classes` to see the available base classes
(`BasicBot`, `Chatbot`, `Agent`, `WebAgent`, `WebSearchAgent`, ...) and
their configurable constructor parameters. Then call `create_yaml_agent`
with:

- `name` — a slug (`^[a-z0-9_-]+$`).
- `bot_class` — the base class name.
- `llm` — optional `"provider:model"` override.
- `description` — what the agent does.
- `category` — a grouping folder under `AGENTS_DIR/agents/` (default
  `"general"`).

This writes a lossless YAML definition and registers the agent
immediately — no draft/activate step needed.

## Path B — Code-generated agent (custom tools/behavior)

When the user needs custom Python logic (a bespoke tool, custom prompt
building, non-trivial control flow), write a full agent module and call
`save_agent_draft(name, source)`. Rules for the generated source:

1. Subclass one of the catalog base classes (`from parrot.bots.agent
   import Agent`, etc.) — check `list_agent_base_classes` for the exact
   import path.
2. Decorate the class with `@register_agent("<name>")` (`from
   parrot.registry import register_agent`) so activation actually
   registers it.
3. Keep imports to the standard library, `parrot.*`, and already-listed
   tools (`list_available_tools`) — the draft validator statically
   rejects unknown/unsafe imports (AST allowlist) before it is ever
   imported.
4. A draft is NEVER live code. Explain to the user that they (or an
   admin) must call `POST /astudio/drafts/{name}/activate` — you cannot
   activate a draft yourself.

Always show the user the full generated source and the validation report
returned by `save_agent_draft` before suggesting they activate it.
