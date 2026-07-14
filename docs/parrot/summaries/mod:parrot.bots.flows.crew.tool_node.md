---
type: Wiki Summary
title: parrot.bots.flows.crew.tool_node
id: mod:parrot.bots.flows.crew.tool_node
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ToolNode — deterministic tool execution node for AgentCrew.
relates_to:
- concept: class:parrot.bots.flows.crew.tool_node.TemplateResolutionError
  rel: defines
- concept: class:parrot.bots.flows.crew.tool_node.ToolLike
  rel: defines
- concept: class:parrot.bots.flows.crew.tool_node.ToolNode
  rel: defines
- concept: class:parrot.bots.flows.crew.tool_node.ToolNodeExecutionError
  rel: defines
- concept: func:parrot.bots.flows.crew.tool_node.extract_tool_output
  rel: defines
- concept: func:parrot.bots.flows.crew.tool_node.resolve_templates
  rel: defines
- concept: mod:parrot.bots.flows.core.fsm
  rel: references
- concept: mod:parrot.bots.flows.core.node
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.bots.flows.crew.tool_node`

ToolNode — deterministic tool execution node for AgentCrew.

Provides a crew member that is NOT an LLM agent but a direct tool caller:
it invokes an ``AbstractTool`` with statically declared ``args``/``kwargs``
(pass-through) and wraps the outcome so it is indistinguishable from an
agent-execution result to the rest of the flow machinery (``FlowResult``,
context summaries, persistence, FSM lifecycle). No LLM tokens are spent.

Template placeholders — resolved deterministically at execution time from
prior results (never via an LLM):

- ``{input}`` — the node's input. Sequential/loop modes: the composed
  previous input; parallel mode: the task's query; flow mode: the last
  completed dependency's output (or the initial task when the node has
  no dependencies).
- ``{nodes.<node_name>.output}`` — the stored output of a previously
  completed node. Avoid dots in node ids: they are ambiguous inside
  this placeholder syntax.

A string value that consists of exactly one placeholder is replaced by the
referenced value with its native type preserved (a dict result passes
through to the tool as a dict). Placeholders embedded in a larger string
are substituted via ``str()``. Literal braces that do not match the
placeholder grammar (e.g. inline JSON) are left untouched.

## Classes

- **`ToolLike(Protocol)`** — Structural protocol for any object usable as a ToolNode tool.
- **`TemplateResolutionError(ValueError)`** — A template placeholder references a node with no stored result.
- **`ToolNodeExecutionError(RuntimeError)`** — The wrapped tool reported failure (``ToolResult.success == False``).
- **`ToolNode(Node)`** — Deterministic tool-caller crew node (no LLM involved).

## Functions

- `def resolve_templates(value: Any, *, input_text: str, results: Mapping[str, Any]) -> Any` — Recursively resolve template placeholders inside a value.
- `def extract_tool_output(tool_result: ToolResult) -> str` — Return the string form of a ``ToolResult`` payload.
