---
type: Wiki Overview
title: 'TASK-1478: ComputerAgent'
id: doc:sdd-tasks-completed-task-1478-computer-agent-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §2 ComputerAgent and §3 Module 4. Agent subclass configured
  for
relates_to:
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot_tools.computer.agent
  rel: mentions
- concept: mod:parrot_tools.computer.toolkit
  rel: mentions
- concept: mod:parrot_tools.scraping.toolkit
  rel: mentions
---

# TASK-1478: ComputerAgent

**Feature**: FEAT-227 — Computer-Use Agent
**Spec**: `sdd/specs/computer-use-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1475, TASK-1477
**Assigned-to**: unassigned

---

## Context

Implements spec §2 ComputerAgent and §3 Module 4. Agent subclass configured for
computer-use models with screenshot memory pruning, safety decision handling, and
optional WebScrapingToolkit composition.

---

## Scope

- Implement `ComputerAgent(Agent)` registered as `"computer_agent"`
- Override `agent_tools()` to return ComputerInteractionToolkit tools + optional WebScrapingToolkit
- Implement screenshot memory pruning (keep last N turns, strip older screenshots)
- Implement safety decision handling with configurable `safety_mode` ("auto" / "interactive")
- Constructor: model, viewport, headless, initial_url, safety_mode, max_screenshot_turns, include_scraping

**NOT in scope**: Google client changes, model enum changes, toolkit implementation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/computer/agent.py` | CREATE | ComputerAgent |
| `packages/ai-parrot-tools/tests/computer/test_agent.py` | CREATE | Agent unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.agent import Agent                    # verified: agent.py:1256
from parrot.tools.abstract import AbstractTool         # verified: abstract.py:81
from parrot.registry import register_agent             # verified: registry/__init__.py:12
from parrot_tools.computer.toolkit import ComputerInteractionToolkit  # from TASK-1477
from parrot_tools.scraping.toolkit import WebScrapingToolkit  # verified: TOOL_REGISTRY line 63
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/agent.py
class Agent(BasicAgent):                               # line 1256
    pass  # inherits everything from BasicAgent

class BasicAgent(Chatbot, NotificationMixin):          # line 37
    def agent_tools(self) -> List[AbstractTool]:       # line 262 — override this

# packages/ai-parrot/src/parrot/registry/__init__.py
register_agent  # decorator: register_agent(name=..., at_startup=False)
```

### Does NOT Exist
- ~~`Agent.prune_screenshots()`~~ — no such method; must implement custom pruning
- ~~`Agent.safety_mode`~~ — no such attribute; must add in ComputerAgent
- ~~`Agent.conversation_history`~~ — history is managed by the client, not the agent directly

---

## Implementation Notes

### Pattern to Follow
```python
@register_agent(name="computer_agent", at_startup=False)
class ComputerAgent(Agent):
    agent_id: str = "computer_agent"

    def __init__(self, *, model="gemini-2.5-computer-use-preview-10-2025",
                 viewport=(1280, 720), headless=True,
                 initial_url="https://www.google.com",
                 safety_mode="auto", max_screenshot_turns=3,
                 include_scraping=False, **kwargs):
        self._computer_toolkit = ComputerInteractionToolkit(
            viewport=viewport, headless=headless, initial_url=initial_url
        )
        self._include_scraping = include_scraping
        self._safety_mode = safety_mode
        self._max_screenshot_turns = max_screenshot_turns
        super().__init__(model=model, **kwargs)

    def agent_tools(self) -> list[AbstractTool]:
        tools = self._computer_toolkit.get_tools()
        if self._include_scraping:
            scraping = WebScrapingToolkit(driver_type="playwright", headless=True)
            tools.extend(scraping.get_tools())
        return tools
```

### Key Constraints
- `safety_mode="auto"`: log safety decisions and auto-acknowledge
- `safety_mode="interactive"`: emit an event (use EventEmitterMixin) for external handling
- Screenshot pruning: after each model response, walk conversation history backwards,
  count turns with screenshots, strip screenshot data from turns beyond max_screenshot_turns
- Use `self.logger` for all logging

---

## Acceptance Criteria

- [ ] `ComputerAgent` registered with `@register_agent(name="computer_agent")`
- [ ] `agent_tools()` returns ComputerInteractionToolkit tools
- [ ] Optional WebScrapingToolkit composition when `include_scraping=True`
- [ ] Screenshot pruning limits conversation screenshots to last N turns
- [ ] Safety mode configurable: "auto" logs, "interactive" emits event
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/computer/test_agent.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import patch, MagicMock
from parrot_tools.computer.agent import ComputerAgent

class TestComputerAgent:
    def test_agent_tools_count(self):
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._computer_toolkit = MagicMock()
        agent._computer_toolkit.get_tools.return_value = [MagicMock()] * 25
        agent._include_scraping = False
        tools = agent.agent_tools()
        assert len(tools) == 25

    def test_agent_tools_with_scraping(self):
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._computer_toolkit = MagicMock()
        agent._computer_toolkit.get_tools.return_value = [MagicMock()] * 25
        agent._include_scraping = True
        with patch("parrot_tools.computer.agent.WebScrapingToolkit") as mock_ws:
            mock_ws.return_value.get_tools.return_value = [MagicMock()] * 7
            tools = agent.agent_tools()
            assert len(tools) == 32

    def test_safety_mode_default(self):
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._safety_mode = "auto"
        assert agent._safety_mode == "auto"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/computer-use-agent.spec.md`
2. **Check dependencies** — TASK-1475 and TASK-1477 in completed
3. **Verify** Agent class at agent.py:1256, register_agent at registry/__init__.py:12
4. **Implement** ComputerAgent with tools, pruning, safety
5. **Move this file** to completed, update index

---

## Completion Note

Implemented ComputerAgent registered as "computer_agent". agent_tools() returns ComputerInteractionToolkit tools plus optional WebScrapingToolkit. Implements prune_screenshots() for conversation history management, handle_safety_decision() for auto/interactive modes. All 14 unit tests pass.
