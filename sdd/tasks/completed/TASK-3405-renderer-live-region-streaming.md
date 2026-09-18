# TASK-3405: `ResponseRenderer` streams into a `LiveRegion`; render `TurnEvent`s and resumed history

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3400, TASK-3403
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (absorbed FEAT-519 Module 2). The root cause of the "cheap"
inline console is one function: `ResponseRenderer.render_stream_chunk`
(`renderer.py:248`) writes raw `sys.stdout.write(text)` (`:257`), so the default
streaming path loses Markdown, highlighting and wrapping. Two of the three stacked
workarounds live in this file: the `Console(file=_BlockingSafeFile(sys.__stdout__),
force_terminal=True)` bypass (`:80-82`) and `_BlockingSafeFile` itself (`:22-56`).

This task makes the renderer stream *into* the `LiveRegion` from TASK-3400 and
teaches it the `TurnEvent` vocabulary from TASK-3403, so the inline REPL
(TASK-3407) can render `TurnRunner` output without knowing about chunks.

---

## Scope

- Delete `_BlockingSafeFile` and the `import time` it needs; construct the console
  via `get_console()` (injectable) — **in the same change** as the region-based
  streaming (spec §7 ordering gotcha).
- `__init__(self, console: Optional[Console] = None, region: Optional[LiveRegion] = None)`;
  the region is created **lazily** on first `render_stream_start()` from
  `self.console`, so the existing `renderer` fixture (`tests/cli/conftest.py`
  replaces `r.console` after construction) still controls where the region paints.
- `render_stream_start/chunk/end` repaint `Markdown(_stream_buffer)` via
  `region.update()`; no `sys.stdout` access anywhere in the file (AC11).
- Add `render_turn_event(event)`, `render_tool_started(event)`,
  `render_history(turns, *, session_id)`, `render_usage_unknown()`.
- Keep `render`, `_render_tool_calls`, `_render_usage`, `render_error`,
  `render_table`, `render_info`, `print` behaviour and signatures unchanged.
- Tests in `packages/ai-parrot/tests/cli/test_renderer_stream.py`.

**NOT in scope**: `repl.py` (TASK-3407), `console.py` (TASK-3400), the TUI
renderer adapter (TASK-3411), `conftest.py` (TASK-3416), deleting
`_mute_stream_loggers` (TASK-3407).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/renderer.py` | MODIFY | region-based streaming; delete `_BlockingSafeFile`; new render methods |
| `packages/ai-parrot/tests/cli/test_renderer_stream.py` | CREATE | streaming/no-stdout/partial-markdown/usage/history tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from rich.console import Console          # verified: renderer.py:13
from rich.markdown import Markdown        # verified: renderer.py:14
from rich.panel import Panel              # verified: renderer.py:15
from rich.table import Table              # verified: renderer.py:16
from rich.text import Text                # verified: renderer.py:17
from parrot.models.responses import AIMessage   # verified: renderer.py:19
from parrot.cli.console import LiveRegion, get_console   # provided by TASK-3400 (cli/console.py)
from parrot.cli.events import (            # provided by TASK-3403 (cli/events.py)
    TurnEvent, TurnEventKind, TextDelta, ToolStarted, ToolFinished, ToolFailed,
    TurnCompleted, TurnFailed, TurnCancelled)
from parrot.cli.commands import ConversationTurn   # verified: commands.py:38
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/renderer.py  (current file, 289 lines)
import json, logging, sys, time, traceback                      # lines 6-10  (`time` used only by _BlockingSafeFile)
class _BlockingSafeFile:                                        # lines 22-56  (TO BE DELETED)
class ResponseRenderer:                                         # line 59
    def __init__(self) -> None:                                 # line 69
        self.logger = logging.getLogger(__name__)               # line 79
        self.console = Console(file=_BlockingSafeFile(sys.__stdout__), force_terminal=True)   # lines 80-82 (TO BE REPLACED)
        self._stream_buffer: str = ""                           # line 83
    def render(self, response: AIMessage) -> None               # line 89  (output/response fallback 98-112; tool panels 115-116; usage 119-122)
    def _render_tool_calls(self, tool_calls: List[Any]) -> None # line 124 (reads .arguments/.name/.result/.error)
    def _render_usage(self, usage: Any) -> None                 # line 153
    def render_error(self, error: Exception) -> None            # line 175
    def render_table(self, headers, rows, title=None) -> None   # line 195
    def render_info(self, lines: List[tuple[str, str]]) -> None # line 215
    def render_stream_start(self) -> None                       # line 233 (docstring 234-245 justifies raw writes — delete it)
    def render_stream_chunk(self, text: str) -> None            # line 248 (`import sys` :254; sys.stdout.write :257 — ROOT CAUSE)
    def render_stream_end(self, response: Optional[AIMessage] = None) -> None   # line 262 (console.print() :270; tool/usage 272-278; buffer reset :280)
    def print(self, *args: Any, **kwargs: Any) -> None          # line 282

# TASK-3400 LiveRegion (spec §3 M1): __init__(console=None, *, refresh_per_second=8, transient=False);
#   start() stop() pause() resume() update(renderable) modal() ctx-manager; is_terminal property.
#   Non-terminal console ⇒ update() prints sequentially, modal() no-op.

# tests/cli/conftest.py — `renderer` fixture: r = ResponseRenderer(); r.console = Console(file=devnull)  (must keep working)
# tests/cli/test_integration.py:304-352 monkeypatches renderer.render_stream_start/chunk/end on the instance — keep them plain methods.
```

### Does NOT Exist
- ~~`ResponseRenderer.render_markdown()`, `.render_live()`, `.set_console()`~~ — not real methods.
- ~~`ResponseRenderer.region` before `render_stream_start()`~~ — create lazily; expose a `region` property that builds it on first access.
- ~~`rich.live.Live` used directly in renderer.py~~ — go through `LiveRegion` only.
- ~~`_mute_stream_loggers`~~ — lives in `repl.py`, not here; do not add any handler-level mutation (AC14).
- ~~`ToolCall.result` guaranteed on live events~~ — `ToolFinished` carries only `duration_ms`/`result_status`/`result_size_bytes`; results appear via `_render_tool_calls` on the final message.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/renderer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/cli/test_renderer_stream.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/renderer.py#ResponseRenderer",
    "sym:packages/ai-parrot/src/parrot/cli/renderer.py#ResponseRenderer.render_stream_chunk",
    "sym:packages/ai-parrot/src/parrot/cli/renderer.py#ResponseRenderer.render_stream_start",
    "sym:packages/ai-parrot/src/parrot/cli/renderer.py#ResponseRenderer.render_stream_end",
    "sym:packages/ai-parrot/src/parrot/cli/renderer.py#_BlockingSafeFile",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#ConversationTurn",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Delete `_BlockingSafeFile` **only together with** the region-based streaming (spec §7 "Ordering when deleting `_BlockingSafeFile`").
- Repaint cost: `render_stream_chunk` appends and calls `region.update(Markdown(buffer))`; the region's 8/s tick throttles actual paints — do not add sleeps or per-chunk `console.print`.
- Partial Markdown must not raise: wrap `Markdown(buffer)` rendering in a helper that falls back to `Text(buffer)` on exception (AC13 / spec §7).
- Unknown usage renders `tokens: n/a`, never zero (AC8).
- Keep the zero-argument construction `ResponseRenderer()` working (agentd `cli.py:158`, conftest fixture).
- Inside a worktree run tests with `PYTHONPATH=packages/ai-parrot/src pytest …`; never `uv sync` there.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/devloop/renderer.py:82-107` — the pause/resume pattern `LiveRegion` generalises.
- `packages/ai-parrot/tests/cli/test_integration.py:29-88` — existing renderer tests (must stay green).

---

## Implementation Blueprint

### Steps (in order)
1. Delete lines 22-56 (`_BlockingSafeFile`) and `import time` (line 9) — *why*: the class exists only to survive `patch_stdout()`'s non-blocking fd during raw writes, which no longer happen.
2. Replace the constructor body (lines 80-82) with injectable console + lazy region — *why*: AC12 requires one shared console; laziness keeps the conftest fixture's `r.console = …` effective.
3. Rewrite `render_stream_start/chunk/end` (lines 233-280) to use the region — *why*: AC11/AC13.
4. Append `render_turn_event`, `render_tool_started`, `render_history`, `render_usage_unknown` after `print` (line 282) — *why*: TASK-3407 renders `TurnEvent`s through these; TASK-3406's `/resume` calls `render_history`.
5. Write tests — *why*: spec §4 rows `test_renderer_*`.

### `packages/ai-parrot/src/parrot/cli/renderer.py` (MODIFY — imports and constructor)
```python
# occurrences: 1 (verified: grep -c 'import time' packages/ai-parrot/src/parrot/cli/renderer.py)
# DELETE — line 9 `import time`; also DELETE lines 22-56 (`class _BlockingSafeFile:` … `return getattr(self._wrapped, name)`)
#   (verified: grep -c 'class _BlockingSafeFile:' → 1, renderer.py:22)

# occurrences: 1 (verified: grep -c 'from parrot.models.responses import AIMessage' packages/ai-parrot/src/parrot/cli/renderer.py)
# AFTER — insert below `from parrot.models.responses import AIMessage` (verified: renderer.py:19)
from parrot.cli.commands import ConversationTurn              # verified: commands.py:38
from parrot.cli.console import LiveRegion, get_console        # provided by TASK-3400
from parrot.cli.events import (                               # provided by TASK-3403
    TextDelta, ToolFailed, ToolFinished, ToolStarted, TurnCancelled, TurnCompleted, TurnEvent, TurnFailed)

# occurrences: 1 (verified: grep -c 'def __init__(self) -> None:' packages/ai-parrot/src/parrot/cli/renderer.py)
# REPLACE — lines 69-83 (`def __init__(self) -> None:` through `self._stream_buffer: str = ""`)
    def __init__(self, console: Optional[Console] = None, region: Optional[LiveRegion] = None) -> None:
        """Initialise the renderer.

        Args:
            console: Rich console; defaults to the process-wide ``get_console()``.
            region: Live region for streaming; created lazily from ``self.console`` when omitted,
                so a console swapped in after construction (tests) is honoured.
        """
        self.logger = logging.getLogger(__name__)
        self.console: Console = console or get_console()
        self._region: Optional[LiveRegion] = region
        self._stream_buffer: str = ""

    @property
    def region(self) -> LiveRegion:
        """The streaming region, built on first access from ``self.console``."""
        if self._region is None:
            self._region = LiveRegion(self.console)
        return self._region
```
**Why**: `self.console` stays a public attribute (conftest and `_cmd_create_agent` read `renderer.console`, commands.py:373). Removing `force_terminal=True` and the `sys.__stdout__` bypass is AC11/AC12 — rendering now happens inside a managed region instead of racing `patch_stdout()`.

### `packages/ai-parrot/src/parrot/cli/renderer.py` (MODIFY — streaming methods)
```python
# occurrences: 1 (verified: grep -c 'def render_stream_start(self) -> None:' packages/ai-parrot/src/parrot/cli/renderer.py)
# REPLACE — lines 233-280 (`def render_stream_start` … `self._stream_buffer = ""` at the end of render_stream_end)
    def render_stream_start(self) -> None:
        """Begin a streaming session: reset the buffer and start the live region."""
        self._stream_buffer = ""
        self.region.start()

    def _stream_renderable(self) -> Any:
        """``Markdown`` of the buffer; falls back to plain ``Text`` when the partial document cannot parse."""
        try:
            return Markdown(self._stream_buffer)
        except Exception:  # noqa: BLE001 — unclosed fence/table mid-stream (spec §7)
            return Text(self._stream_buffer)

    def render_stream_chunk(self, text: str) -> None:
        """Append a streamed chunk and repaint the region (throttled by its refresh tick). Never touches stdout."""
        self._stream_buffer += text
        self.region.update(self._stream_renderable())

    def render_stream_end(self, response: Optional[AIMessage] = None) -> None:
        """Stop the region, then tool panels and usage exactly as before (renderer.py:272-278)."""
        self.region.update(self._stream_renderable())
        self.region.stop()
        if response is not None:
            if getattr(response, "tool_calls", None):
                self._render_tool_calls(response.tool_calls)
            usage = getattr(response, "usage", None)
            if usage and (usage.prompt_tokens or usage.completion_tokens):
                self._render_usage(usage)
            else:
                self.render_usage_unknown()
        self._stream_buffer = ""
```
**Why**: the region owns its screen area, so log records land above it (AC14 by construction); `_stream_renderable` is the AC13 partial-Markdown guard. `render_stream_end` keeps its `Optional[AIMessage]` contract for `test_integration.py:333-344`.

### `packages/ai-parrot/src/parrot/cli/renderer.py` (MODIFY — new event/history methods)
```python
# occurrences: 1 (verified: grep -c 'def print(self, \*args: Any, \*\*kwargs: Any) -> None:' packages/ai-parrot/src/parrot/cli/renderer.py)
# AFTER — append after the `print` method body (verified: renderer.py:282-289, end of class)
    def render_usage_unknown(self) -> None:
        """Unknown usage is never shown as zero (AC8)."""
        self.console.print("[dim]tokens: n/a[/dim]")

    def render_tool_started(self, event: ToolStarted) -> None:
        """One dim status line per live tool start; arguments only as the event's summary."""
        self.console.print(f"[dim]⏵ tool [bold]{event.tool_name}[/bold] …[/dim]")

    def render_turn_event(self, event: TurnEvent) -> None:
        """Dispatch a ``TurnEvent`` to the inline rendering primitives."""
        if isinstance(event, TextDelta):
            self.render_stream_chunk(event.text)
        elif isinstance(event, ToolStarted):
            self.region.pause(); self.render_tool_started(event); self.region.resume()
        elif isinstance(event, (ToolFinished, ToolFailed)):
            # FILL IN: dim "✓ <tool> <ms> ms" / "✗ <tool>: <error_type>" line, bracketed by pause()/resume() — bounded by AC6/AC8
            pass
        elif isinstance(event, TurnCompleted):
            self.render_stream_end(event.message)
        elif isinstance(event, TurnCancelled):
            self.region.stop()
            self.console.print("[yellow]Interrupted — partial answer kept above.[/yellow]")
        elif isinstance(event, TurnFailed):
            self.region.stop()
            # FILL IN: red panel with error_type/error_message; partial text stays on screen — bounded by AC19
            pass

    def render_history(self, turns: List[ConversationTurn], *, session_id: str) -> None:
        """Resumed transcript: header, then each turn as ``you> …`` plus Markdown of the response."""
        self.console.print(f"[bold]Resumed session[/bold] {session_id} [dim]({len(turns)} turns)[/dim]")
        for turn in turns:
            self.console.print(f"[bold cyan]you>[/bold cyan] {turn.query}")
            # FILL IN: render turn.response via self.render() (it handles output/response/tool_calls) — bounded by AC9
```
**Why**: the inline presenter (TASK-3407) calls only `render_turn_event`; batch mode still uses `render()`. Live tool lines are printed outside the region (pause/resume) so they scroll above the streaming Markdown instead of being overwritten by the next repaint.

### `packages/ai-parrot/tests/cli/test_renderer_stream.py` (CREATE)
```python
"""Streaming renderer tests (FEAT-573 TASK-3405, spec §4)."""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.console import Console                       # verified: renderer.py:13

from parrot.cli.console import LiveRegion              # provided by TASK-3400
from parrot.cli.renderer import ResponseRenderer


@pytest.fixture
def buf_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=True, width=100)


@pytest.fixture
def renderer_with_spy(buf_console):
    region = MagicMock(spec=LiveRegion)
    return ResponseRenderer(console=buf_console, region=region), region


def test_renderer_stream_chunk_never_writes_stdout(renderer_with_spy, capsys):
    renderer, region = renderer_with_spy
    renderer.render_stream_start()
    renderer.render_stream_chunk("# hi")
    assert capsys.readouterr().out == ""
    region.update.assert_called()
    # FILL IN: assert the renderable passed to update() is a rich Markdown — AC11/AC13


def test_renderer_partial_markdown_does_not_raise(buf_console):
    r = ResponseRenderer(console=buf_console)
    r.render_stream_start()
    r.render_stream_chunk("```python\nprint(1")
    r.render_stream_chunk("\n| a | b\n| --")
    r.render_stream_end(None)  # must not raise


def test_renderer_usage_unknown_not_zero(buf_console):
    r = ResponseRenderer(console=buf_console)
    r.render_stream_start()
    r.render_stream_end(SimpleNamespace(tool_calls=[], usage=None))
    out = buf_console.file.getvalue()
    assert "n/a" in out and "total=0" not in out


def test_renderer_lazy_region_uses_swapped_console():
    r = ResponseRenderer()
    swapped = Console(file=io.StringIO(), force_terminal=True)
    r.console = swapped
    assert r.region.console is swapped  # FILL IN: adjust attribute name to LiveRegion's console attr from TASK-3400


def test_renderer_render_history(buf_console):
    # FILL IN: two ConversationTurn(query, SimpleNamespace(output=..., response=..., tool_calls=[], usage=None));
    # assert header contains "Resumed session" and both queries — AC9
    pass


def test_blocking_safe_file_removed():
    import parrot.cli.renderer as mod
    assert not hasattr(mod, "_BlockingSafeFile")
    import inspect
    assert "sys.stdout.write" not in inspect.getsource(mod)  # AC11
```
**Why**: the spy region proves no stdout writes without depending on Rich `Live` internals; the source-inspection test is the literal AC11 grep.

### FILL IN checklist
- [ ] `renderer.py::render_turn_event` — ToolFinished/ToolFailed line format and TurnFailed panel; bounded by AC6/AC8/AC19.
- [ ] `renderer.py::render_history` — per-turn body via `render()`; bounded by AC9.
- [ ] `test_renderer_stream.py` — Markdown-type assertion, history test body, region console attribute name (from TASK-3400).

---

## Acceptance Criteria

- [ ] `grep -n 'sys.stdout.write' packages/ai-parrot/src/parrot/cli/renderer.py` empty; `_BlockingSafeFile` and `import time` gone (spec AC11).
- [ ] Exactly zero `Console(` constructions in `renderer.py` (spec AC12).
- [ ] Partial Markdown mid-stream never raises (spec AC13).
- [ ] Unknown usage renders `n/a` (spec AC8).
- [ ] `ResponseRenderer()` still constructs with no arguments; `tests/cli/test_integration.py::TestResponseRenderer` and `TestAgentREPLStream` stay green (AC25).
- [ ] `ruff check packages/ai-parrot/src/parrot/cli/renderer.py` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_renderer_stream.py -q`
- `pytest packages/ai-parrot/tests/cli/test_integration.py::TestResponseRenderer -q`

---

## Test Specification

See the CREATE block above; required names: `test_renderer_stream_chunk_never_writes_stdout`,
`test_renderer_partial_markdown_does_not_raise`, `test_renderer_usage_unknown_not_zero`,
`test_renderer_lazy_region_uses_swapped_console`, `test_renderer_render_history`,
`test_blocking_safe_file_removed`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3405-renderer-live-region-streaming.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-coder native `sonnet` seat (attempt 27e15146bb1f4aae837abf3e29e46440)
**Date**: 2026-09-18
**Notes**: Removed `_BlockingSafeFile` and all `sys.stdout`/`Console(file=...)`
workarounds; `ResponseRenderer(console=None, region=None)` now defaults to
`get_console()`, with a lazily-built `region` property honouring a console
swapped in after construction. `render_stream_start/chunk/end` repaint via
`region.update(Markdown(buffer))` with a `Text` fallback if Markdown
construction raises. Added `render_usage_unknown`, `render_tool_started`,
`render_turn_event` (dispatches every `TurnEventKind`), `render_history`.
Checked the TASK-3374 reuse-helper pattern for the `TurnFailed` branch: read
`render_error`'s body first, found it appends a live traceback (wrong for a
structured error_type/error_message pair) and built a dedicated `Panel`
instead of reusing it.

Merge clean (`coder_merge` outcome=merged); engine lint autofix (black)
applied. Orchestrator ran `pytest test_renderer_stream.py`: 6 passed; then
the full `packages/ai-parrot/tests/cli/` suite: 192 passed, 5 failures
confirmed pre-existing on `dev` itself (unrelated `TestStandaloneAgentLoader`
+ `test_wizard_workbrief_roundtrip`), 1 known `uv sync` gap
(`test_textual_is_importable`) — no regressions from this change.

**Feedback recorded**: none — clean delivery, TASK-3374 pattern correctly
judged and applied (checked before reusing, decided not to reuse).
**Deviations from spec**: none.
