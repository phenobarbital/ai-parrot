---
type: Wiki Entity
title: ToolNode
id: class:parrot.bots.flows.crew.tool_node.ToolNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Deterministic tool-caller crew node (no LLM involved).
relates_to:
- concept: class:parrot.bots.flows.core.node.Node
  rel: extends
---

# ToolNode

Defined in [`parrot.bots.flows.crew.tool_node`](../summaries/mod:parrot.bots.flows.crew.tool_node.md).

```python
class ToolNode(Node)
```

Deterministic tool-caller crew node (no LLM involved).

Registered into a crew via ``AgentCrew.add_tool_node()``, this node
participates in every execution mode: sequential/parallel/loop runs
dispatch to :meth:`call_tool` (via ``AgentCrew._execute_agent``), while
flow mode invokes :meth:`execute` with the same contract as
``AgentNode.execute``.

Duck-typing notes:

- ``is_configured`` defaults to ``True`` so ``_ensure_agent_ready``
  never attempts LLM configuration.
- ``agent`` is a self-referencing property: flow-mode plumbing reads
  ``node.agent.name`` and ``build_node_metadata`` probes agent
  attributes with ``getattr(..., None)`` — both are safe on this model.
- The FSM lifecycle is driven externally by the crew scheduler, exactly
  as for ``CrewAgentNode``.

Args:
    tool: The tool to invoke (any ``AbstractTool`` or ``ToolLike``).
    node_id: Unique identifier for this node within the crew.
    args: Positional arguments passed through to the tool (template
        placeholders allowed in string values).
    kwargs: Keyword arguments passed through to the tool (template
        placeholders allowed in string values).
    description: Optional human-readable description.
    dependencies: Node ids that must complete before this node runs.
    successors: Node ids dispatched after this node completes.
    fsm: Optional pre-built FSM (auto-created when ``None``).

## Methods

- `def model_post_init(self, __context: Any) -> None` — Auto-create the FSM if not provided; initialise logger.
- `def name(self) -> str` — Node identity (same as ``node_id`` for tool nodes).
- `def agent(self) -> 'ToolNode'` — Self-reference for flow-mode plumbing that reads ``node.agent``.
- `async def configure(self) -> None` — No-op — the wrapped tool needs no LLM configuration.
- `async def call_tool(self, *, input_text: str, results: Mapping[str, Any], timeout: Optional[float]=None) -> ToolResult` — Resolve templates and invoke the tool (sequential/parallel/loop path).
- `async def execute(self, ctx: Any, deps: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]` — Execute the tool node in flow mode.
