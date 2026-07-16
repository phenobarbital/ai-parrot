---
type: Wiki Overview
title: 'TASK-1482: Integration Tests'
id: doc:sdd-tasks-completed-task-1482-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 8 and §4 Integration Tests. End-to-end tests that
  verify
relates_to:
- concept: mod:parrot.clients.google.client
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
- concept: mod:parrot_tools.computer.agent
  rel: mentions
- concept: mod:parrot_tools.computer.backend
  rel: mentions
- concept: mod:parrot_tools.computer.models
  rel: mentions
- concept: mod:parrot_tools.computer.toolkit
  rel: mentions
---

# TASK-1482: Integration Tests

**Feature**: FEAT-227 — Computer-Use Agent
**Spec**: `sdd/specs/computer-use-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1475, TASK-1476, TASK-1477, TASK-1478, TASK-1479, TASK-1480, TASK-1481
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 8 and §4 Integration Tests. End-to-end tests that verify
the full chain: ComputerAgent → ComputerInteractionToolkit → AsyncComputerBackend,
plus GoogleGenAIClient computer-use tool building.

---

## Scope

- Write integration test: agent navigates and clicks (mocked Playwright + mocked Gemini)
- Write integration test: loop pagination scenario with condition-based termination
- Write integration test: hybrid agent with ComputerInteraction + WebScrapingToolkit
- Write integration test: GoogleGenAIClient builds tools with ComputerUse + FunctionDeclarations
- Verify all components integrate cleanly

**NOT in scope**: live browser tests (those are manual), implementation fixes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/computer/test_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.computer.agent import ComputerAgent
from parrot_tools.computer.toolkit import ComputerInteractionToolkit
from parrot_tools.computer.backend import AsyncComputerBackend
from parrot_tools.computer.models import EnvState, ComputerTask, TaskResult, LoopResult
from parrot.clients.google.client import GoogleGenAIClient
from parrot.models.google import GoogleModel
```

### Does NOT Exist
- ~~`ComputerAgent.run(query)`~~ — verify the actual method name for running the agent

---

## Acceptance Criteria

- [ ] Integration test: navigate + click flow with mocked Playwright and mocked Gemini response
- [ ] Integration test: loop pagination with condition-based stop
- [ ] Integration test: hybrid agent with both toolkits
- [ ] Integration test: GoogleGenAIClient tool building with ComputerUse
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/computer/test_integration.py -v`
- [ ] No regressions in existing test suites

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_tools.computer.agent import ComputerAgent
from parrot_tools.computer.toolkit import ComputerInteractionToolkit
from parrot_tools.computer.models import EnvState

class TestComputerAgentIntegration:
    @pytest.mark.asyncio
    async def test_navigate_and_click_flow(self):
        """Full loop: toolkit receives action, dispatches to backend, returns screenshot."""
        toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        toolkit._backend = AsyncMock()
        toolkit._backend.screen_size.return_value = (1280, 720)
        toolkit._backend.navigate.return_value = EnvState(screenshot=b"png", url="https://example.com")
        toolkit._backend.click_at.return_value = EnvState(screenshot=b"png2", url="https://example.com/page")
        toolkit._started = True

        nav_result = await toolkit.navigate(url="https://example.com")
        assert nav_result["url"] == "https://example.com"

        click_result = await toolkit.click_at(x=500, y=300)
        assert click_result["url"] == "https://example.com/page"

    @pytest.mark.asyncio
    async def test_loop_pagination(self):
        """Loop runs multiple iterations and stops on max_iterations."""
        toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        toolkit._backend = AsyncMock()
        toolkit._backend.screen_size.return_value = (1280, 720)
        toolkit._backend.current_state.return_value = EnvState(screenshot=b"png", url="https://e.com")
        toolkit._started = True

        await toolkit.define_task(name="next_page", description="Click next", steps=["Click Next button"])
        result = await toolkit.run_loop(task="next_page", iterations=5, collect_results=True)
        assert result["iterations_completed"] == 5
        assert result["stop_reason"] == "count"
```

---

## Completion Note

Created `test_integration.py` with 18 tests across 4 test classes: `TestNavigateAndClickFlow` (4 tests — navigate/click dispatching and coordinate denormalization), `TestLoopPagination` (4 tests — count-based loops, max_iterations cap, abort signalling, undefined task error), `TestHybridAgentToolComposition` (4 tests — tool listing, graceful WebScrapingToolkit failure, screenshot pruning, safety mode), `TestGoogleClientComputerUseIntegration` (6 tests — computer_use tool building, excluded actions, custom_functions non-regression, model detection). All 18 tests pass. Full suite: 114 tests in ai-parrot-tools/computer + 21 in ai-parrot/clients, all passing.
