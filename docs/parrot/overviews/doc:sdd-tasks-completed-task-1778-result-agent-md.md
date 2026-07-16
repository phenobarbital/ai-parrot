---
type: Wiki Overview
title: 'TASK-1778: `ResultAgent` — Registered Agent for Infographic Rendering'
id: doc:sdd-tasks-completed-task-1778-result-agent-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'that: (a) LLM-authors Tab 1 blocks from the crew summary, (b) merges'
relates_to:
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.bots.flows.crew.result_infographic
  rel: mentions
- concept: mod:parrot.bots.flows.result_agent
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

# TASK-1778: `ResultAgent` — Registered Agent for Infographic Rendering

**Feature**: FEAT-308 — AgentCrew ResultAgent End-of-Flow Multi-Tab Infographic Node
**Spec**: `sdd/specs/agentcrew-node-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1775
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 3. The `ResultAgent` is a proper internal `Agent` subclass
> registered as `"result-agent"` via `@register_agent`. It carries an
> `InfographicToolkit`, receives the crew's synthesis summary + deterministic
> tab blocks, LLM-authors the Tab 1 (Executive Summary & Insights) blocks,
> and renders the merged block list through the `crew_report` template.
> Default LLM is Gemini 3.5 Flash (`google` client) when no crew LLM is
> supplied.

---

## Scope

- Create `parrot/bots/flows/result_agent.py` with:
  - `@register_agent("result-agent")` class `ResultAgent(Agent)`.
  - Override `agent_tools()` → returns `[InfographicToolkit(...)]`.
  - A method `async def generate_infographic(summary, deterministic_blocks, **kwargs) -> InfographicRenderResult`
    that: (a) LLM-authors Tab 1 blocks from the crew summary, (b) merges
    them with the deterministic blocks via `merge_tab1_blocks`, (c) calls
    `InfographicToolkit.render(template_name="crew_report", blocks=merged, data_variables=[])`.
  - Default LLM fallback to Gemini Flash when no `llm` is provided.
- Write unit tests.

**NOT in scope**: Building the deterministic blocks (that's TASK-1777). Integrating into `AgentCrew` (that's TASK-1779).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/result_agent.py` | CREATE | ResultAgent implementation |
| `tests/unit/test_result_agent.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.registry import register_agent, agent_registry    # registry/__init__.py:12 / :7
from parrot.bots.agent import Agent, BasicAgent               # agent.py:1204 / :29
from parrot.tools.infographic_toolkit import (
    InfographicToolkit,                                       # infographic_toolkit.py:110
    InfographicRenderResult,                                  # infographic_toolkit.py:91
)
from parrot.bots.flows.crew.result_infographic import (
    merge_tab1_blocks,                                        # TASK-1777 creates this
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/agent.py
class Agent(BasicAgent):                                      # L1204
    def agent_tools(self) -> List[AbstractTool]: ...          # L1207 — override hook

class BasicAgent(Chatbot, NotificationMixin):                 # L29
    def __init__(self, ..., tools=None, use_tools=True,
                 use_llm=..., **kwargs): ...                  # L62

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):                    # L110
    return_direct: bool = True                                # L129
    def __init__(self, template_dirs=None, templates=None, ...): ...  # L134
    async def render(self, template_name: str, theme, mode,
                     data_variables: List[str], blocks=None,
                     blocks_variable=None, enhance_brief=None
                     ) -> InfographicRenderResult: ...        # L240

# packages/ai-parrot/src/parrot/registry/__init__.py
register_agent = agent_registry.register_bot_decorator        # L12 — decorator factory
```

### Does NOT Exist
- ~~`ResultAgent`~~ — does not exist yet; this task creates it.
- ~~`Agent.generate_infographic()`~~ — not a base method; this task adds it to `ResultAgent`.
- ~~`InfographicToolkit.render_crew_report()`~~ — no such shortcut; use `render(template_name="crew_report", ...)`.

---

## Implementation Notes

### Pattern to Follow
```python
# Reference: parrot/agents/demo.py:148 (agent registration pattern)
@register_agent("result-agent")
class ResultAgent(Agent):
    """Internal agent that renders a crew's ExecutionMemory into a crew_report infographic."""

    def agent_tools(self) -> List[AbstractTool]:
        toolkit = InfographicToolkit()
        return toolkit.get_tools()

    async def generate_infographic(
        self, summary: str, deterministic_blocks: List[Dict],
        crew_name: str = "AgentCrew", theme: str = "light",
    ) -> InfographicRenderResult:
        # 1. LLM-author Tab 1 blocks from summary
        # 2. merge_tab1_blocks(tab1_blocks, deterministic_blocks)
        # 3. toolkit.render(template_name="crew_report", ...)
        ...
```

### Key Constraints
- The LLM call for Tab 1 should use the agent's own `_llm` (which the caller
  sets to the crew's LLM or falls back to Gemini Flash).
- If the LLM call fails, the method should still attempt to render with a
  simple text-based Tab 1 fallback (graceful degradation).
- `render()` requires `mode="deterministic"` since blocks are pre-built.
- Confirm the exact Gemini Flash model-id string from the `google` client
  configuration before hardcoding a default.

### References in Codebase
- `packages/ai-parrot/src/parrot/agents/demo.py` — agent registration pattern
- `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` — toolkit + render API

---

## Acceptance Criteria

- [ ] `agent_registry` resolves `"result-agent"` to `ResultAgent`
- [ ] `ResultAgent().agent_tools()` returns tools from `InfographicToolkit`
- [ ] `generate_infographic()` produces an `InfographicRenderResult` with a populated `html_url` or `html_inline`
- [ ] Tab 1 is LLM-authored from the `summary` parameter (no second synthesis)
- [ ] Graceful fallback if LLM call fails (simple text Tab 1)
- [ ] Unit tests pass: `pytest tests/unit/test_result_agent.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/result_agent.py`
- [ ] Import works: `from parrot.bots.flows.result_agent import ResultAgent`

---

## Test Specification

```python
# tests/unit/test_result_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.registry import agent_registry


class TestResultAgentRegistration:
    def test_result_agent_registered(self):
        """result-agent is registered in the agent registry."""
        from parrot.bots.flows.result_agent import ResultAgent
        resolved = agent_registry.get("result-agent")
        assert resolved is not None

    def test_agent_tools_returns_infographic_toolkit(self):
        """agent_tools() yields InfographicToolkit tools."""
        from parrot.bots.flows.result_agent import ResultAgent
        agent = ResultAgent(name="test-result-agent")
        tools = agent.agent_tools()
        assert len(tools) > 0
        tool_names = [t.name if hasattr(t, 'name') else str(t) for t in tools]
        assert any("render" in n.lower() or "infographic" in n.lower() for n in tool_names)


class TestResultAgentDefaultLLM:
    def test_default_llm_when_none_supplied(self):
        """With no crew LLM, ResultAgent falls back to a default."""
        from parrot.bots.flows.result_agent import ResultAgent
        agent = ResultAgent(name="test-result-agent")
        # Should not raise — default LLM is configured internally
        assert agent is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-node-infographic.spec.md` §3 Module 3
2. **Check dependencies** — TASK-1775 must be complete (crew_report template)
3. **Verify the Codebase Contract** — confirm `Agent` base class, `register_agent` decorator, `InfographicToolkit` API
4. **Check the `google` client** for the correct Gemini Flash model-id string
5. **Implement** `ResultAgent` with registration, tools, and `generate_infographic()`
6. **Write and run** unit tests
7. **Update status** and move to completed when done

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-14
**Notes**: Implemented `ResultAgent(Agent)` in
`parrot/bots/flows/result_agent.py`, registered via
`@register_agent(name="result-agent")` (corrected from the spec/task's
positional `@register_agent("result-agent")` — the decorator is
keyword-only per `registry.py:1205-1216`). `agent_tools()` returns
`InfographicToolkit(artifact_store=...).get_tools()`. Since
`InfographicToolkit` requires a real `ArtifactStore` at construction time
(no zero-arg default) but building one is async while `agent_tools()` runs
synchronously inside `BasicAgent.__init__`, added `_LazyArtifactStore` — a
duck-typed proxy that defers `build_conversation_backend()` +
`.initialize()` + `build_overflow_store()` to the first actual
`save_artifact()` call (inside the async `render()` path). No hardcoded
Gemini model-id needed: `BasicAgent.__init__` already falls back to
`GoogleGenAIClient()` (`_default_model=GEMINI_FLASH_LATEST`) when no `llm`
is supplied — resolves spec §8's open question without guessing a literal.
`generate_infographic()` LLM-authors Tab 1 via `self.ask(..., use_tools=False)`
(reusing the crew's existing `summary`, no second synthesis), merges via
`merge_tab1_blocks` (TASK-1777), and renders via
`toolkit.render(template_name="crew_report", ...)`; falls back to the raw
summary text on any LLM exception (graceful degradation, per G7). Corrected
the task's own test spec: `agent_registry.get(name)` does not exist — the
verified API is `get_metadata(name).factory`. 5 unit tests pass, ruff clean.

**Deviations from spec**: none (contract corrections documented above; no
behavioral deviation from Module 3's scope)
