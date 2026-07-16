---
type: Wiki Overview
title: 'TASK-1010: Create demo agent agents/demo.py with WebHumanTool, HandoffTool,
  BookFlightTool'
id: doc:sdd-tasks-completed-task-1010-hitl-demo-agent-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task creates a registered demo agent (`hitl_demo`, "Travel Concierge")
  that demonstrates the full HITL flow on the web surface. The agent uses `WebHumanTool`,
  `HandoffTool`, and a custom `BookFlightTool` that intentionally raises `HumanInteractionInterrupt`
  on malformed date
relates_to:
- concept: mod:parrot.agents.demo
  rel: mentions
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.core.tools.handoff
  rel: mentions
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1010: Create demo agent agents/demo.py with WebHumanTool, HandoffTool, BookFlightTool

**Feature**: FEAT-146 — web-hitl-and-demo-agent
**Spec**: `sdd/specs/web-hitl-and-demo-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-1005
**Assigned-to**: unassigned

---

## Context

This task creates a registered demo agent (`hitl_demo`, "Travel Concierge") that demonstrates the full HITL flow on the web surface. The agent uses `WebHumanTool`, `HandoffTool`, and a custom `BookFlightTool` that intentionally raises `HumanInteractionInterrupt` on malformed dates, showcasing both the HITL ask and handoff mechanisms (§3 Module 7 in the spec).

The agent serves as an end-to-end example for users and QA to see web HITL in action.

---

## Scope

- Create `agents/demo.py` (new file at the repository root, alongside `agents/finance.py`).
- Define `BookFlightTool(AbstractTool)` with:
  - Name: `book_flight`.
  - Parameters: `destination` (string), `date` (string).
  - Logic: If date doesn't match a simple date pattern (e.g., YYYY-MM-DD), raise `HumanInteractionInterrupt(prompt="...")`.
  - Otherwise, return a fake confirmation string.
- Define `HITLDemoAgent(BasicAgent)` with:
  - `agent_id = "hitl_demo"`.
  - System prompt instructing the agent to:
    1. Use `WebHumanTool` (single_choice) to pick a destination from a list.
    2. Use `WebHumanTool` (free_text) to ask for the travel date.
    3. Call `BookFlightTool(destination, date)`.
    4. If successful, summarize the trip.
  - Tools: `WebHumanTool(source_agent="hitl_demo")`, `HandoffTool()`, `BookFlightTool()`.
  - Uses `use_llm="google"` (default; requires no external service beyond LLM + Redis).
- Register the agent using `@register_agent(name="hitl_demo", at_startup=True)`.
- Add Google-style docstrings to classes and methods.

**NOT in scope**:
- Frontend implementation (out of scope per spec §1 Non-Goals).
- Extended interaction types (multi_choice, form) — start with single_choice + free_text.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/demo.py` | CREATE | `HITLDemoAgent` and `BookFlightTool`. Path is at the repo root (the `AGENTS_DIR` discovery directory), NOT inside `packages/ai-parrot/`. See `agents/finance.py` for the canonical pattern. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.handlers.web_hitl import WebHumanTool                               # (created in TASK-1005)
from parrot.core.tools.handoff import HandoffTool                               # parrot/core/tools/handoff.py:18
from parrot.core.exceptions import HumanInteractionInterrupt                    # parrot/core/exceptions.py:11
from parrot.bots.agent import BasicAgent                                        # parrot/bots/agent.py:36
from parrot.tools.abstract import AbstractTool                                  # parrot/tools/abstract.py:23
from parrot.registry import register_agent                                      # parrot/registry/__init__.py:12
from typing import Any, List, Optional
import logging
import re
```

### Existing Signatures to Use

```python
# parrot/bots/agent.py:36
class BasicAgent(Chatbot, NotificationMixin):
    agent_id: Optional[str] = None                                              # line 53

    def __init__(                                                               # line 79
        self,
        name: str = 'Agent',
        agent_id: str = 'agent',
        use_llm: str = 'google',
        llm: str = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        use_tools: bool = True,
        instructions: Optional[str] = None,
        dataframes: Optional[Dict[str, pd.DataFrame]] = None,
        **kwargs,
    ): ...

# parrot/tools/abstract.py:23
class AbstractTool:
    name: str                                                                   # line NN
    async def _aexecute(self, **kwargs: Any) -> Any: ...

# parrot/core/tools/handoff.py:18
class HandoffTool(AbstractTool):
    name: str = "handoff_to_human"                                              # line 27

# parrot/core/exceptions.py:11
class HumanInteractionInterrupt(Exception):
    def __init__(self, prompt: str, ...): ...

# parrot/registry/__init__.py:12
def register_agent(name: str, *, at_startup: bool = False, startup_config: dict | None = None, ...): ...

# parrot/handlers/web_hitl.py
class WebHumanTool(HumanTool):
    def __init__(
        self,
        *,
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...
```

### Does NOT Exist

- ~~`agents/demo.py`~~ — to be created.
- ~~`BookFlightTool`~~ — to be created (custom to this agent).

---

## Implementation Notes

### Pattern to Follow

Mirror the agent structure from `parrot/agents/` directory (if examples exist):
- Class extends `BasicAgent`.
- System prompt is descriptive and instructs the agent's behavior.
- Tools are instantiated in the constructor or via `agent_tools()` method.
- Agent is registered with `@register_agent` decorator.

For the custom `BookFlightTool`:
- Extend `AbstractTool`.
- Implement `_aexecute` (async) or `_execute`.
- Validate input; raise exceptions when appropriate.

### Key Constraints

- `WebHumanTool(source_agent="hitl_demo")` so the question payload identifies its source.
- `HandoffTool()` for the handoff demonstration.
- `BookFlightTool` raises `HumanInteractionInterrupt` on invalid dates (to demo the Handoff resume path).
- System prompt must be clear and guide the agent through the flow.
- Use `use_llm="google"` which supports interrupt resume.

---

## Acceptance Criteria

- [ ] `agents/demo.py` exists with `HITLDemoAgent` class.
- [ ] `HITLDemoAgent` extends `BasicAgent` with `agent_id = "hitl_demo"`.
- [ ] `HITLDemoAgent` is registered via `@register_agent(name="hitl_demo", at_startup=True)`.
- [ ] System prompt instructs the agent to use `ask_human` (WebHumanTool), `book_flight`, and `handoff_to_human`.
- [ ] `BookFlightTool` is defined with `destination` and `date` parameters.
- [ ] `BookFlightTool` raises `HumanInteractionInterrupt` on malformed dates (regex check: e.g., `\d{4}-\d{2}-\d{2}`).
- [ ] `BookFlightTool` returns a confirmation string on valid dates.
- [ ] Agent tools list includes `WebHumanTool`, `HandoffTool`, `BookFlightTool`.
- [ ] Agent can be imported and instantiated: `from parrot.agents.demo import HITLDemoAgent`
- [ ] Agent is registered in the agent registry: `parrot.registry.agent_registry['hitl_demo']`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/agents/test_demo.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/agents/demo.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/agents/test_demo.py
import pytest
from parrot.agents.demo import HITLDemoAgent, BookFlightTool
from parrot.registry import agent_registry
from parrot.core.exceptions import HumanInteractionInterrupt


@pytest.fixture
def demo_agent():
    return HITLDemoAgent()


@pytest.fixture
def book_flight_tool():
    return BookFlightTool()


class TestHITLDemoAgent:
    def test_demo_agent_registers(self):
        """demo agent is registered in the agent_registry."""
        assert "hitl_demo" in agent_registry
        assert agent_registry["hitl_demo"] is HITLDemoAgent

    def test_demo_agent_has_tools(self, demo_agent):
        """demo agent has WebHumanTool, HandoffTool, and BookFlightTool."""
        tool_names = [t.name for t in demo_agent.agent_tools()]
        assert "ask_human" in tool_names
        assert "handoff_to_human" in tool_names
        assert "book_flight" in tool_names

    def test_demo_agent_agent_id(self, demo_agent):
        """demo agent has agent_id set to 'hitl_demo'."""
        assert demo_agent.agent_id == "hitl_demo"


class TestBookFlightTool:
    async def test_book_flight_raises_on_bad_date(self, book_flight_tool):
        """BookFlightTool raises HumanInteractionInterrupt on malformed date."""
        with pytest.raises(HumanInteractionInterrupt):
            await book_flight_tool._aexecute(
                destination="Paris",
                date="next year",
            )

    async def test_book_flight_succeeds_on_valid_date(self, book_flight_tool):
        """BookFlightTool returns confirmation on valid date."""
        result = await book_flight_tool._aexecute(
            destination="Paris",
            date="2026-05-15",
        )
        assert result is not None
        assert isinstance(result, str)
        assert "confirmation" in result.lower()

    def test_book_flight_tool_name(self, book_flight_tool):
        """BookFlightTool has name 'book_flight'."""
        assert book_flight_tool.name == "book_flight"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-hitl-and-demo-agent.spec.md` for full context
2. **Check dependencies** — verify TASK-1005 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports and agent patterns in existing `parrot/agents/` files
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — create the agent and tools following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1010-hitl-demo-agent.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-05
**Notes**: Implemented HITLDemoAgent (Travel Concierge) in
`packages/ai-parrot/src/parrot/agents/demo.py` with BookFlightTool raising
HumanInteractionInterrupt on invalid YYYY-MM-DD dates. All 7 tests pass.
Root-level `agents/demo.py` discovery wrapper was created but is gitignored
(the `/agents/` directory is in .gitignore); the canonical implementation in
the parrot package is what the tests import from `parrot.agents.demo`.

**Deviations from spec**: The `/agents/` root directory is gitignored so the
discovery wrapper cannot be committed. The canonical implementation at
`packages/ai-parrot/src/parrot/agents/demo.py` satisfies all acceptance
criteria including `from parrot.agents.demo import HITLDemoAgent`.
