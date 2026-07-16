---
type: Wiki Overview
title: 'TASK-1132: Response Renderer'
id: doc:sdd-tasks-completed-task-1132-response-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: tool call panels, usage stats
relates_to:
- concept: mod:parrot.cli.renderer
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1132: Response Renderer

**Feature**: FEAT-168 — Console CLI Agents
**Spec**: `sdd/specs/console-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1131
**Assigned-to**: unassigned

---

## Context

> Implements Module 5 from the spec: the `ResponseRenderer` class that renders
> `AIMessage` objects to the terminal via Rich.  Supports both streaming mode
> (tokens via `rich.live.Live`) and batch mode (full markdown + panels).
> Used by the REPL engine and slash commands to display agent output.

---

## Scope

- Create `packages/ai-parrot/src/parrot/cli/renderer.py`
- Implement `ResponseRenderer` class with:
  - `render(response: AIMessage)` — batch render with Rich markdown, code blocks,
    tool call panels, usage stats
  - `render_stream_start()` — begin live streaming display
  - `render_stream_chunk(text: str)` — append chunk to live display
  - `render_stream_end(response: AIMessage)` — finalize stream, show metadata
  - `render_error(error: Exception)` — render errors in a Rich panel
  - `render_table(headers, rows)` — render tabular data (for `/tools`, `--list`)
- Handle `AIMessage.tool_calls` display (show tool name + args in a panel)
- Handle `AIMessage.usage` display (token counts)
- Use `rich.console.Console`, `rich.markdown.Markdown`, `rich.panel.Panel`,
  `rich.live.Live`, `rich.table.Table`

**NOT in scope**: REPL loop, slash commands, agent loading

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/renderer.py` | CREATE | ResponseRenderer class |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.responses import AIMessage      # responses.py:72
from parrot.models.outputs import OutputMode       # outputs.py:39
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):  # line 72
    input: str
    output: Any
    response: Optional[str]
    data: Optional[Any]
    tool_calls: List[ToolCall]
    usage: CompletionUsage
    model: str
    provider: str
    output_mode: OutputMode
    metadata: Dict[str, Any]
    created_at: datetime
    response_time: Optional[float]
```

### Does NOT Exist
- ~~`AIMessage.format()`~~ — no format method on AIMessage
- ~~`AIMessage.to_terminal()`~~ — no terminal rendering method
- ~~`OutputMode.CONSOLE`~~ — use `TERMINAL`
- ~~`OutputMode.CLI`~~ — does not exist

---

## Implementation Notes

### Pattern to Follow
```python
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live
from rich.table import Table

class ResponseRenderer:
    def __init__(self) -> None:
        self.console = Console()
        self._live: Optional[Live] = None

    def render(self, response: AIMessage) -> None:
        # Render response.output as Markdown
        # If tool_calls, show each in a panel
        # If usage, show token stats
        ...
```

### Key Constraints
- Use `rich.live.Live` for streaming — do NOT print line by line
- `response.output` can be `str`, `dict`, or other types — handle gracefully
- Use `prompt_toolkit.patch_stdout.patch_stdout()` awareness — the renderer
  must work correctly when wrapped in patch_stdout context

---

## Acceptance Criteria

- [ ] `ResponseRenderer` renders markdown content from `AIMessage.output`
- [ ] Tool calls displayed in Rich panels with tool name and arguments
- [ ] Token usage stats displayed when `AIMessage.usage` is present
- [ ] Streaming mode: `render_stream_start/chunk/end` works with `rich.live.Live`
- [ ] Error rendering shows traceback in a styled panel
- [ ] Table rendering works for agent listing
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/cli/renderer.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_renderer.py
import pytest
from unittest.mock import MagicMock
from parrot.cli.renderer import ResponseRenderer
from parrot.models.responses import AIMessage


class TestResponseRenderer:
    def test_render_markdown(self, mock_agent_response):
        renderer = ResponseRenderer()
        renderer.render(mock_agent_response)  # should not raise

    def test_render_tool_calls(self, response_with_tools):
        renderer = ResponseRenderer()
        renderer.render(response_with_tools)  # should show tool panels

    def test_render_error(self):
        renderer = ResponseRenderer()
        renderer.render_error(ValueError("test error"))

    def test_render_table(self):
        renderer = ResponseRenderer()
        renderer.render_table(
            headers=["Name", "Tools"],
            rows=[["agent1", "3"], ["agent2", "5"]],
        )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/console-cli-agents.spec.md` §2 (Data Models)
2. **Read `packages/ai-parrot/src/parrot/models/responses.py`** to understand AIMessage fields
3. **Implement** `ResponseRenderer` with all render methods
4. **Test** rendering with mock AIMessage objects

---

## Completion Note

Completed 2026-05-13. Implemented `ResponseRenderer` in `parrot/cli/renderer.py`
with full batch rendering (Markdown, JSON, tool call panels, usage stats), streaming
via `rich.live.Live` (`render_stream_start/chunk/end`), error panels, table rendering,
and info display. Verified import and table rendering work correctly. All linting passed.
