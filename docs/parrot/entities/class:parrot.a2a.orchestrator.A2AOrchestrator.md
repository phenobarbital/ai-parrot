---
type: Wiki Entity
title: A2AOrchestrator
id: class:parrot.a2a.orchestrator.A2AOrchestrator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Hybrid orchestrator combining rule-based routing with LLM decision-making.
---

# A2AOrchestrator

Defined in [`parrot.a2a.orchestrator`](../summaries/mod:parrot.a2a.orchestrator.md).

```python
class A2AOrchestrator
```

Hybrid orchestrator combining rule-based routing with LLM decision-making.

This orchestrator provides intelligent request routing and multi-agent
coordination. It uses deterministic rules when patterns are known and
falls back to LLM-based reasoning for complex or ambiguous requests.

Architecture:
    1. Rules Engine (via A2AProxyRouter): Fast, deterministic routing
    2. LLM Decision Engine: Complex reasoning about agent selection
    3. Execution Engine: Parallel/sequential agent invocation
    4. Aggregation Engine: Combine responses from multiple agents

Usage Patterns:
    - RULES_ONLY: Pure rule-based routing, no LLM cost
    - LLM_ONLY: Always use LLM for decisions
    - HYBRID: Rules first, LLM fallback (recommended)
    - PARALLEL: Fan-out to multiple agents
    - SEQUENTIAL: Pipeline execution

Example:
    orchestrator = A2AOrchestrator(mesh, default_mode=OrchestrationMode.HYBRID)

    # Add rules (fast path)
    orchestrator.route_by_skill("analysis", "AnalystBot")
    orchestrator.route_by_regex(r"urgent", "PriorityBot")

    # Set LLM fallback
    orchestrator.set_fallback_llm(claude_client)

    # Simple case: uses rules
    result = await orchestrator.run("Analyze this data")

    # Complex case: LLM decides
    result = await orchestrator.run(
        "Compare our Q3 performance with competitors and suggest improvements"
    )

## Methods

- `def route_by_skill(self, skill_id: str, target: Union[str, List[str]], **kwargs) -> 'A2AOrchestrator'` — Add skill-based routing rule.
- `def route_by_tag(self, tag: str, target: Union[str, List[str]], **kwargs) -> 'A2AOrchestrator'` — Add tag-based routing rule.
- `def route_by_regex(self, pattern: str, target: Union[str, List[str]], **kwargs) -> 'A2AOrchestrator'` — Add regex-based routing rule.
- `def set_default(self, agent_name: str) -> 'A2AOrchestrator'` — Set default agent for unmatched requests.
- `def set_fallback_llm(self, llm_client: 'AbstractClient', *, decision_prompt: Optional[str]=None, model: Optional[str]=None) -> 'A2AOrchestrator'` — Configure LLM for complex orchestration decisions.
- `def clear_llm(self) -> 'A2AOrchestrator'` — Remove LLM fallback configuration.
- `async def run(self, message: str, *, mode: Optional[OrchestrationMode]=None, agents: Optional[List[str]]=None, skill_id: Optional[str]=None, tags: Optional[List[str]]=None, context_id: Optional[str]=None, timeout: Optional[float]=None, metadata: Optional[Dict[str, Any]]=None) -> OrchestrationResult` — Execute orchestration for a message.
- `async def close_clients(self) -> None` — Close all cached clients.
- `async def ask(self, message: str, *, agent: Optional[str]=None, mode: Optional[OrchestrationMode]=None, **kwargs) -> str` — Shortcut: get response as string.
- `async def fan_out(self, message: str, agents: List[str], **kwargs) -> Dict[str, Union[str, Exception]]` — Send to multiple agents and collect responses.
- `async def pipeline(self, message: str, agents: List[str], **kwargs) -> str` — Execute sequential pipeline.
- `def stats(self) -> OrchestratorStats` — Get current statistics.
- `def router(self) -> A2AProxyRouter` — Access the internal router for advanced configuration.
- `def get_info(self) -> Dict[str, Any]` — Get orchestrator state information.
