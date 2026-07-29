---
type: Wiki Overview
title: 'Feature Specification: Computer-Use Agent'
id: doc:sdd-specs-computer-use-agent-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot's existing browser automation (`WebScrapingToolkit`) uses **CSS
  selectors and
relates_to:
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.clients.google.client
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.scraping.driver_context
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.playwright_config
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.playwright_driver
  rel: mentions
- concept: mod:parrot_tools.scraping.toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Computer-Use Agent

**Feature ID**: FEAT-227
**Date**: 2026-06-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.next
**Proposal**: `sdd/proposals/computer-use-agent.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's existing browser automation (`WebScrapingToolkit`) uses **CSS selectors and
XPath** for element targeting. This works well for structured extraction but cannot handle
scenarios where the page layout is unknown, dynamic, or requires visual reasoning —
e.g., interacting with complex web apps, filling multi-step forms whose DOM structure
varies, or navigating sites that render content as images/canvas.

Google's Gemini computer-use models (`gemini-2.5-computer-use-preview-10-2025`,
`gemini-3-flash-preview`) enable **vision-based browser automation**: the model sees a
screenshot, decides where to click/type/scroll using pixel coordinates, and receives the
next screenshot. This is a fundamentally different — and complementary — interaction model.

### Goals
- Provide a `ComputerInteractionToolkit` exposing all 13 Gemini computer-use actions
  plus screenshot, recording, and loop/flow execution capabilities.
- Provide a `ComputerAgent` that orchestrates vision-based browser tasks with optional
  WebScrapingToolkit composition for hybrid workflows.
- Extend `GoogleGenAIClient` to support `types.ComputerUse` tool type and
  `FunctionResponseBlob` (screenshot bytes) in function responses.
- Support repetitive navigation patterns (pagination, batch forms, list processing)
  via a task/loop execution system.

### Non-Goals (explicitly out of scope)
- Modifying the existing WebScrapingToolkit or its selector-based approach.
- Browserbase backend support (can be added in a follow-up feature).
- Anthropic computer-use protocol (different API entirely).
- Non-browser environments (desktop, mobile apps) — only `ENVIRONMENT_BROWSER`.
- Auto-detecting which model supports computer-use (explicit configuration).

---

## 2. Architectural Design

### Overview

The feature adds three new components in the `parrot_tools` satellite package and
extends the Google client in core:

1. **`AsyncComputerBackend`** — Async Playwright wrapper implementing the computer-use
   action interface. Bridges AI-Parrot's existing `PlaywrightDriver` to the coordinate-based
   action model. Returns `EnvState(screenshot: bytes, url: str)` after each action.

2. **`ComputerInteractionToolkit`** — `AbstractToolkit` subclass (`tool_prefix="computer"`)
   exposing:
   - 13 predefined computer-use actions (click_at, type_text_at, navigate, etc.)
   - Screenshot/recording methods (screenshot, start_recording, start_tracing, record_har, save_pdf)
   - Task definition and loop execution (define_task, run_task, run_loop, abort_loop)

3. **`ComputerAgent`** — `Agent` subclass registered as `"computer_agent"`.
   Configured with a computer-use model. Composes `ComputerInteractionToolkit` +
   optional `WebScrapingToolkit`. Manages screenshot memory pruning and safety decisions.

4. **GoogleGenAIClient extensions** — `_build_tools()` extended for `types.ComputerUse`;
   function response handling extended for `FunctionResponseBlob`; model detection
   for thinking mode and computer-use.

### Component Diagram

```
                          ┌─────────────────────┐
                          │   ComputerAgent      │
                          │ (Agent subclass)     │
                          │                      │
                          │ • screenshot pruning  │
                          │ • safety decisions    │
                          │ • loop controller     │
                          └──────┬───────┬───────┘
                                 │       │
              ┌──────────────────┘       └──────────────────┐
              ▼                                             ▼
┌─────────────────────────────┐           ┌──────────────────────────┐
│ ComputerInteractionToolkit  │           │ WebScrapingToolkit       │
│ (AbstractToolkit)           │           │ (existing, optional)     │
│                             │           │                          │
│ Actions:                    │           │ • plan_create / scrape   │
│ • click_at / hover_at       │           │ • crawl                  │
│ • type_text_at / navigate   │           │ • selector-based extract │
│ • scroll / key_combination  │           └──────────────────────────┘
│ • drag_and_drop / wait      │
│                             │
│ Capture:                    │
│ • screenshot / save_pdf     │
│ • start/stop_recording      │
│ • start/stop_tracing        │
│ • record_har                │
│                             │
│ Loops:                      │
│ • define_task / run_task    │
│ • run_loop / abort_loop     │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ AsyncComputerBackend        │
│                             │
│ • Wraps PlaywrightDriver    │
│ • Coordinate denormalization│
│ • Returns EnvState          │
│   (screenshot + url)        │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ PlaywrightDriver (existing) │
│ (async, playwright.async_api)│
└─────────────────────────────┘

    ─── Google Client Side ───

┌─────────────────────────────┐
│ GoogleGenAIClient           │
│                             │
│ _build_tools() ──► emits    │
│   types.Tool(computer_use=  │
│     ComputerUse(...))       │
│                             │
│ FunctionResponse ──► wraps  │
│   FunctionResponseBlob      │
│   (screenshot PNG bytes)    │
└─────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | ComputerInteractionToolkit inherits; auto-discovers async methods |
| `Agent` / `BasicAgent` | extends | ComputerAgent subclass with agent_tools() override |
| `PlaywrightDriver` | wraps | AsyncComputerBackend delegates browser actions to existing driver |
| `GoogleGenAIClient._build_tools()` | modifies | Adds ComputerUse tool type emission path |
| `GoogleGenAIClient` (FunctionResponse) | modifies | Supports FunctionResponseBlob for screenshots |
| `GoogleModel` enum | extends | New computer-use model entries |
| `WebScrapingToolkit` | composes | Optional composition in ComputerAgent for hybrid workflows |
| `ToolResult` | uses | Returns screenshots via `images` field |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal

class EnvState(BaseModel):
    """State returned after each computer-use action."""
    screenshot: bytes  # PNG format
    url: str

class ComputerUseConfig(BaseModel):
    """Configuration for computer-use tool type in GoogleGenAIClient."""
    environment: str = "ENVIRONMENT_BROWSER"
    excluded_actions: list[str] = Field(default_factory=list)

class ComputerTask(BaseModel):
    """A reusable sequence of natural-language instructions."""
    name: str
    description: str
    steps: list[str]
    params_schema: Optional[dict] = None

class TaskResult(BaseModel):
    """Result of a single task execution."""
    task_name: str
    success: bool
    screenshots: list[bytes] = Field(default_factory=list)
    extracted_data: Optional[dict] = None
    error: Optional[str] = None
    url: str = ""

class LoopResult(BaseModel):
    """Result of a loop execution."""
    task_name: str
    iterations_completed: int
    stop_reason: Literal["count", "condition_met", "max_reached", "aborted", "error"]
    results: list[TaskResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
```

### New Public Interfaces

```python
# --- AsyncComputerBackend ---
class AsyncComputerBackend:
    def __init__(self, viewport: tuple[int, int] = (1280, 720),
                 headless: bool = True, browser_type: str = "chromium"):
        ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def screen_size(self) -> tuple[int, int]: ...

    # 13 predefined actions — all accept denormalized (pixel) coordinates
    async def click_at(self, x: int, y: int) -> EnvState: ...
    async def hover_at(self, x: int, y: int) -> EnvState: ...
    async def type_text_at(self, x: int, y: int, text: str,
                           press_enter: bool = False,
                           clear_before_typing: bool = True) -> EnvState: ...
    async def scroll_document(self, direction: str) -> EnvState: ...
    async def scroll_at(self, x: int, y: int, direction: str,
                        magnitude: int = 800) -> EnvState: ...
    async def wait_seconds(self, seconds: int = 5) -> EnvState: ...
    async def go_back(self) -> EnvState: ...
    async def go_forward(self) -> EnvState: ...
    async def search(self) -> EnvState: ...
    async def navigate(self, url: str) -> EnvState: ...
    async def key_combination(self, keys: list[str]) -> EnvState: ...
    async def drag_and_drop(self, x: int, y: int,
                            dest_x: int, dest_y: int) -> EnvState: ...
    async def open_web_browser(self) -> EnvState: ...
    async def current_state(self) -> EnvState: ...

    # Screenshot / capture
    async def screenshot(self, full_page: bool = False) -> bytes: ...


# --- ComputerInteractionToolkit ---
class ComputerInteractionToolkit(AbstractToolkit):
    tool_prefix: str = "computer"

    def __init__(self, viewport: tuple[int, int] = (1280, 720),
                 headless: bool = True, browser_type: str = "chromium",
                 initial_url: str = "https://www.google.com",
                 search_engine_url: str = "https://www.google.com",
                 **kwargs): ...

    # Actions (normalized 0-1000 coordinates, denormalized internally)
    async def click_at(self, x: int, y: int) -> dict: ...
    async def hover_at(self, x: int, y: int) -> dict: ...
    async def type_text_at(self, x: int, y: int, text: str,
                           press_enter: bool = False,
                           clear_before_typing: bool = True) -> dict: ...
    async def scroll_document(self, direction: str) -> dict: ...
    async def scroll_at(self, x: int, y: int, direction: str,
                        magnitude: int = 800) -> dict: ...
    async def wait(self, seconds: int = 5) -> dict: ...
    async def go_back(self) -> dict: ...
    async def go_forward(self) -> dict: ...
    async def search(self) -> dict: ...
    async def navigate(self, url: str) -> dict: ...
    async def key_combination(self, keys: str) -> dict: ...
    async def drag_and_drop(self, x: int, y: int,
                            destination_x: int, destination_y: int) -> dict: ...
    async def open_browser(self) -> dict: ...

    # Screenshot & recording
    async def screenshot(self, full_page: bool = False) -> dict: ...
    async def screenshot_element(self, selector: str) -> dict: ...
    async def start_recording(self, output_dir: str = "./recordings") -> dict: ...
    async def stop_recording(self) -> dict: ...
    async def start_tracing(self, screenshots: bool = True) -> dict: ...
    async def stop_tracing(self, output_path: str) -> dict: ...
    async def record_har(self, output_path: str) -> dict: ...
    async def save_pdf(self, output_path: str) -> dict: ...

    # Task / loop execution
    async def define_task(self, name: str, description: str,
                          steps: list[str]) -> dict: ...
    async def run_task(self, task: str,
                       params: Optional[dict] = None) -> dict: ...
    async def run_loop(self, task: str,
                       iterations: Optional[int] = None,
                       until: Optional[str] = None,
                       params_list: Optional[list[dict]] = None,
                       max_iterations: int = 100,
                       collect_results: bool = True) -> dict: ...
    async def abort_loop(self) -> dict: ...


# --- ComputerAgent ---
@register_agent(name="computer_agent", at_startup=False)
class ComputerAgent(Agent):
    agent_id: str = "computer_agent"

    def __init__(self, *,
                 model: str = "gemini-2.5-computer-use-preview-10-2025",
                 viewport: tuple[int, int] = (1280, 720),
                 headless: bool = True,
                 initial_url: str = "https://www.google.com",
                 safety_mode: Literal["auto", "interactive"] = "auto",
                 max_screenshot_turns: int = 3,
                 include_scraping: bool = False,
                 **kwargs): ...

    def agent_tools(self) -> list[AbstractTool]: ...
```

---

## 3. Module Breakdown

### Module 1: Data Models
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/computer/models.py`
- **Responsibility**: Pydantic models — `EnvState`, `ComputerUseConfig`, `ComputerTask`,
  `TaskResult`, `LoopResult`.
- **Depends on**: None (pure data models).

### Module 2: AsyncComputerBackend
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/computer/backend.py`
- **Responsibility**: Async Playwright wrapper implementing the computer-use action
  interface. Handles browser lifecycle (start/stop), coordinate denormalization, and
  returns `EnvState` (screenshot + URL) after each action.
- **Depends on**: Module 1 (models), existing `PlaywrightDriver` and `PlaywrightConfig`.

### Module 3: ComputerInteractionToolkit
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/computer/toolkit.py`
- **Responsibility**: AbstractToolkit subclass exposing computer-use actions, screenshot/
  recording capabilities, and task/loop execution as agent tools. Handles coordinate
  normalization (0-1000 → viewport), lifecycle hooks (`_pre_execute` ensures browser
  is started), and result formatting.
- **Depends on**: Module 1 (models), Module 2 (backend).

### Module 4: ComputerAgent
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/computer/agent.py`
- **Responsibility**: Agent subclass configured for computer-use models. Manages
  screenshot memory pruning (keep last N turns), safety decision handling
  (auto/interactive), loop controller for managing conversation history across
  iterations, and optional WebScrapingToolkit composition.
- **Depends on**: Module 1 (models), Module 3 (toolkit), existing `Agent`, `WebScrapingToolkit`.

### Module 5: GoogleGenAIClient Computer-Use Support
- **Path**: `packages/ai-parrot/src/parrot/clients/google/client.py` (modifications)
- **Responsibility**: Extend `_build_tools()` to emit `types.Tool(computer_use=...)`,
  extend function response handling to support `FunctionResponseBlob`, extend
  `_requires_thinking()` for computer-use models, add `_is_computer_use_model()` helper.
- **Depends on**: None (modifies existing code).

### Module 6: GoogleModel Entries
- **Path**: `packages/ai-parrot/src/parrot/models/google.py` (modifications)
- **Responsibility**: Add `GEMINI_COMPUTER_USE` and related model enum entries.
- **Depends on**: None.

### Module 7: Package Registration & Init
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/computer/__init__.py` and
  `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (update TOOL_REGISTRY)
- **Responsibility**: Package init, exports, and toolkit registration in TOOL_REGISTRY.
- **Depends on**: Modules 1-4.

### Module 8: Tests
- **Path**: `packages/ai-parrot-tools/tests/computer/`
- **Responsibility**: Unit tests for models, backend, toolkit, agent; integration tests
  for the full loop with mocked Playwright and mocked Gemini responses.
- **Depends on**: All modules.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_env_state_model` | Module 1 | EnvState accepts bytes + url |
| `test_computer_task_model` | Module 1 | ComputerTask validates name, steps |
| `test_loop_result_model` | Module 1 | LoopResult serialization with stop_reason enum |
| `test_backend_coordinate_denormalize` | Module 2 | 0-1000 → viewport pixel mapping accuracy |
| `test_backend_start_stop` | Module 2 | Browser lifecycle with mocked PlaywrightDriver |
| `test_backend_click_at` | Module 2 | Dispatches to PlaywrightDriver.click with correct pixel coords |
| `test_backend_type_text_at` | Module 2 | Fill + optional enter + clear_before |
| `test_backend_screenshot` | Module 2 | Returns PNG bytes from PlaywrightDriver.screenshot |
| `test_toolkit_tool_discovery` | Module 3 | All public async methods discovered as tools |
| `test_toolkit_tool_prefix` | Module 3 | Tools prefixed with "computer_" |
| `test_toolkit_click_normalizes` | Module 3 | Toolkit normalizes 0-1000 → backend pixel coords |
| `test_toolkit_define_task` | Module 3 | Creates and stores ComputerTask |
| `test_toolkit_run_loop_count` | Module 3 | Count-based loop runs N iterations |
| `test_toolkit_run_loop_max_cap` | Module 3 | max_iterations prevents runaway |
| `test_toolkit_abort_loop` | Module 3 | abort_loop stops a running loop |
| `test_toolkit_recording_lifecycle` | Module 3 | start_recording → stop_recording returns path |
| `test_agent_tools_composition` | Module 4 | agent_tools() includes computer + optional scraping tools |
| `test_agent_screenshot_pruning` | Module 4 | Old screenshots stripped from conversation history |
| `test_agent_safety_auto` | Module 4 | Safety decisions auto-acknowledged in "auto" mode |
| `test_agent_safety_interactive` | Module 4 | Safety decisions raise event in "interactive" mode |
| `test_client_build_tools_computer_use` | Module 5 | _build_tools emits types.Tool(computer_use=...) |
| `test_client_function_response_blob` | Module 5 | FunctionResponse includes screenshot blob |
| `test_client_requires_thinking_computer_use` | Module 5 | Computer-use models detected |
| `test_model_enum_entries` | Module 6 | New GoogleModel entries resolve to correct strings |

### Integration Tests

| Test | Description |
|---|---|
| `test_computer_agent_navigate_and_click` | Full loop: agent sends query → model returns click_at → backend executes → screenshot returned |
| `test_computer_agent_loop_pagination` | Define task + run_loop with condition — mock pagination scenario |
| `test_computer_agent_with_scraping` | Hybrid: computer actions + WebScrapingToolkit extraction |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_playwright_page():
    """Mock Playwright page with screenshot, click, fill methods."""
    page = AsyncMock()
    page.screenshot.return_value = b"\x89PNG..."  # minimal PNG header
    page.url = "https://example.com"
    page.viewport_size = {"width": 1280, "height": 720}
    return page

@pytest.fixture
def computer_backend(mock_playwright_page):
    """AsyncComputerBackend with mocked Playwright."""
    backend = AsyncComputerBackend(viewport=(1280, 720))
    backend._driver._page = mock_playwright_page
    return backend

@pytest.fixture
def mock_gemini_response():
    """Mocked Gemini response with computer-use function calls."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `ComputerInteractionToolkit` exposes all 13 predefined actions as async tools with `computer_` prefix
- [ ] All toolkit actions accept normalized (0-1000) coordinates and return `EnvState`-derived dicts
- [ ] `AsyncComputerBackend` correctly denormalizes coordinates to viewport pixels
- [ ] Screenshot, recording, tracing, HAR, and PDF capture methods work via toolkit
- [ ] `define_task` / `run_loop` supports count-based, condition-based, and data-driven loops
- [ ] `run_loop` respects `max_iterations` safety cap
- [ ] `ComputerAgent` composes `ComputerInteractionToolkit` and optionally `WebScrapingToolkit`
- [ ] `ComputerAgent` prunes screenshots from conversation history (keep last N turns)
- [ ] `ComputerAgent.safety_mode` configurable: "auto" (default) logs and acknowledges, "interactive" raises event
- [ ] `GoogleGenAIClient._build_tools()` emits `types.Tool(computer_use=ComputerUse(...))` when configured
- [ ] `GoogleGenAIClient` function response correctly wraps `FunctionResponseBlob(mime_type="image/png", data=...)`
- [ ] `GoogleGenAIClient._requires_thinking()` returns True for computer-use models
- [ ] `GoogleModel` enum includes `GEMINI_COMPUTER_USE` entry
- [ ] All unit tests pass (`pytest packages/ai-parrot-tools/tests/computer/ -v`)
- [ ] No breaking changes to existing WebScrapingToolkit or GoogleGenAIClient
- [ ] `ComputerInteractionToolkit` registered in `TOOL_REGISTRY` as `"computer_interaction"`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# --- Core (packages/ai-parrot/src/parrot/) ---
from parrot.tools.toolkit import AbstractToolkit       # verified: toolkit.py:191
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: abstract.py:81, :46
from parrot.bots.agent import Agent, BasicAgent        # verified: agent.py:1256, :37
from parrot.registry import register_agent             # verified: registry/__init__.py:12
from parrot.models.google import GoogleModel           # verified: models/google.py:9
from parrot.clients.google.client import GoogleGenAIClient  # verified: client.py:96

# --- Google GenAI SDK (google-genai==1.75.0) ---
from google.genai import types
# types.ComputerUse             — fields: environment, excluded_predefined_functions
# types.Environment             — values: ENVIRONMENT_BROWSER, ENVIRONMENT_UNSPECIFIED
# types.FunctionResponsePart    — fields: inline_data, file_data
# types.FunctionResponseBlob    — fields: mime_type, data, display_name
# types.ThinkingConfig          — field: include_thoughts
# types.Tool                    — accepts: computer_use=ComputerUse(...), function_declarations=[...]
# types.FunctionResponse        — fields: id, name, response
# types.FunctionCall            — fields: name, args

# --- Scraping infrastructure (packages/ai-parrot-tools/src/parrot_tools/) ---
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver  # verified: playwright_driver.py:15
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig  # verified: playwright_config.py:9
from parrot_tools.scraping.drivers.abstract import AbstractDriver  # verified: abstract.py:11
from parrot_tools.scraping.driver_context import DriverRegistry, driver_context  # verified: driver_context.py:21, :235
```

### Existing Class Signatures

```python
# --- parrot/tools/toolkit.py ---
class AbstractToolkit(ABC):                            # line 191
    tool_prefix: Optional[str] = None                  # line 242
    exclude_tools: tuple[str, ...] = ()                # line 228
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]:  # line 337
    def _generate_tools(self) -> None:                 # line 390
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:  # line 306
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any:  # line 321

# --- parrot/tools/abstract.py ---
class AbstractTool(EventEmitterMixin, ABC):            # line 81
    args_schema: Type[BaseModel] = AbstractToolArgsSchema  # line 98
    @abstractmethod
    async def _execute(self, **kwargs) -> Any:         # line 238
    async def execute(self, *args, **kwargs) -> ToolResult:  # line 473

class ToolResult(BaseModel):                           # line 46
    success: bool                                      # line 48
    status: str                                        # line 49
    result: Any                                        # line 50
    error: Optional[str]                               # line 51
    metadata: Dict[str, Any]                           # line 52
    timestamp: str                                     # line 53
    files: Optional[list]                              # line 56

…(truncated)…
