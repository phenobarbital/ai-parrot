---
type: Wiki Overview
title: 'TASK-1477: ComputerInteractionToolkit'
id: doc:sdd-tasks-completed-task-1477-computer-interaction-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §2 ComputerInteractionToolkit and §3 Module 3. This is the
  AbstractToolkit
relates_to:
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.computer.backend
  rel: mentions
- concept: mod:parrot_tools.computer.models
  rel: mentions
- concept: mod:parrot_tools.computer.toolkit
  rel: mentions
---

# TASK-1477: ComputerInteractionToolkit

**Feature**: FEAT-227 — Computer-Use Agent
**Spec**: `sdd/specs/computer-use-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1475, TASK-1476
**Assigned-to**: unassigned

---

## Context

Implements spec §2 ComputerInteractionToolkit and §3 Module 3. This is the AbstractToolkit
subclass that exposes computer-use actions, screenshot/recording capabilities, and task/loop
execution as agent-callable tools. Handles coordinate normalization (0-1000 → pixel).

---

## Scope

- Implement `ComputerInteractionToolkit(AbstractToolkit)` with `tool_prefix="computer"`
- 13 action methods accepting normalized (0-1000) coordinates, delegating to backend
- Screenshot/recording methods: `screenshot`, `screenshot_element`, `start_recording`,
  `stop_recording`, `start_tracing`, `stop_tracing`, `record_har`, `save_pdf`
- Task/loop methods: `define_task`, `run_task`, `run_loop`, `abort_loop`
- `_pre_execute` lifecycle hook to lazily start the browser
- Coordinate denormalization: `int(coord / 1000 * backend.screen_size()[dim])`
- Result formatting: convert `EnvState` to dict for tool response

**NOT in scope**: ComputerAgent, Google client changes, model enum changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/computer/toolkit.py` | CREATE | ComputerInteractionToolkit |
| `packages/ai-parrot-tools/tests/computer/test_toolkit.py` | CREATE | Toolkit unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit       # verified: toolkit.py:191
from parrot_tools.computer.models import EnvState, ComputerTask, TaskResult, LoopResult  # from TASK-1475
from parrot_tools.computer.backend import AsyncComputerBackend  # from TASK-1476
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                            # line 191
    tool_prefix: Optional[str] = None                  # line 242
    exclude_tools: tuple[str, ...] = ()                # line 228
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:  # line 306
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any:  # line 321
```

### Does NOT Exist
- ~~`AbstractToolkit.start_browser()`~~ — no such method; use `_pre_execute` for lazy init
- ~~`AbstractToolkit.tool_name_prefix`~~ — the attribute is `tool_prefix`, not `tool_name_prefix`

---

## Implementation Notes

### Pattern to Follow
```python
# Follow FileManagerToolkit pattern: tool_prefix + static async methods
class ComputerInteractionToolkit(AbstractToolkit):
    tool_prefix: str = "computer"

    def __init__(self, viewport=(1280, 720), headless=True, **kwargs):
        self._backend = AsyncComputerBackend(viewport=viewport, headless=headless)
        self._started = False
        self._tasks: dict[str, ComputerTask] = {}
        self._loop_abort = False
        super().__init__(**kwargs)

    async def _pre_execute(self, tool_name: str, **kwargs) -> None:
        if not self._started:
            await self._backend.start()
            self._started = True

    def _denormalize_x(self, x: int) -> int:
        return int(x / 1000 * self._backend.screen_size()[0])

    def _denormalize_y(self, y: int) -> int:
        return int(y / 1000 * self._backend.screen_size()[1])

    async def click_at(self, x: int, y: int) -> dict:
        """Click at coordinates (x, y) on the page. Coordinates are 0-1000 normalized."""
        result = await self._backend.click_at(self._denormalize_x(x), self._denormalize_y(y))
        return {"url": result.url, "screenshot_taken": True}
```

### Key Constraints
- All action methods return dicts (not EnvState directly) — AbstractToolkit tools return serializable results
- Docstrings on every public method — they become the LLM tool descriptions
- `run_loop` must support three modes: count-based, condition-based, data-driven
- `run_loop` must respect `max_iterations` safety cap
- `abort_loop` sets a flag checked between iterations
- `_pre_execute` ensures browser is started lazily (not in `__init__`)

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/filemanager.py` — FileManagerToolkit pattern with tool_prefix
- `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` — WebScrapingToolkit as complex toolkit example

---

## Acceptance Criteria

- [ ] All 13 action methods exposed as tools with `computer_` prefix
- [ ] Actions accept 0-1000 normalized coordinates, denormalize to pixel
- [ ] Screenshot/recording/tracing/HAR/PDF methods functional
- [ ] `define_task` creates and stores a `ComputerTask`
- [ ] `run_loop` supports count-based (`iterations=N`), condition-based (`until=...`), and data-driven (`params_list=[...]`) modes
- [ ] `run_loop` respects `max_iterations` safety cap
- [ ] `abort_loop` stops a running loop
- [ ] `_pre_execute` lazily starts browser on first tool call
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/computer/test_toolkit.py -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/computer/test_toolkit.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot_tools.computer.toolkit import ComputerInteractionToolkit

@pytest.fixture
def toolkit():
    tk = ComputerInteractionToolkit(viewport=(1280, 720), headless=True)
    tk._backend = AsyncMock()
    tk._backend.screen_size.return_value = (1280, 720)
    tk._started = True
    return tk

class TestComputerInteractionToolkit:
    def test_tool_prefix(self, toolkit):
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.name.startswith("computer_")

    def test_tool_count(self, toolkit):
        tools = toolkit.get_tools()
        # 13 actions + 8 capture + 4 loop = 25 minimum
        assert len(tools) >= 25

    @pytest.mark.asyncio
    async def test_click_at_denormalization(self, toolkit):
        from parrot_tools.computer.models import EnvState
        toolkit._backend.click_at.return_value = EnvState(screenshot=b"png", url="https://example.com")
        result = await toolkit.click_at(x=500, y=500)
        toolkit._backend.click_at.assert_called_once_with(640, 360)

    @pytest.mark.asyncio
    async def test_define_and_run_task(self, toolkit):
        await toolkit.define_task(name="test", description="Test task", steps=["step1"])
        assert "test" in toolkit._tasks

    @pytest.mark.asyncio
    async def test_run_loop_max_iterations(self, toolkit):
        await toolkit.define_task(name="test", description="d", steps=["s"])
        toolkit._backend.current_state.return_value = EnvState(screenshot=b"png", url="https://e.com")
        result = await toolkit.run_loop(task="test", max_iterations=3)
        assert result["iterations_completed"] <= 3
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/computer-use-agent.spec.md`
2. **Check dependencies** — TASK-1475 and TASK-1476 must be in completed
3. **Verify** AbstractToolkit signature at toolkit.py:191
4. **Implement** the full toolkit with actions, capture, and loop methods
5. **Verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`

---

## Completion Note

Implemented ComputerInteractionToolkit with tool_prefix="computer". All 13 actions, 8 capture/recording methods, and 4 loop methods exposed as prefixed tools. Coordinate denormalization (0-1000 to viewport pixels). _pre_execute lazy-starts the browser. Loop modes: count-based, condition-based (deferred to model), data-driven. All 35 unit tests pass.
