# TASK-3414: devloop convergence — `RunView` and gate prompts on `LiveRegion`

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3400
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 14 (devloop convergence)**, inherited from FEAT-519 Module 6.
`LiveRegion` (TASK-3400, `parrot/cli/console.py`) is an extraction of the pause/resume discipline
that `RunView` already implements by hand (`devloop/renderer.py:82-96`, `:103-119`). This task
makes `RunView` *use* the shared class instead of carrying its own `_live`/`_paused` pair, and
replaces the manual `pause()`…`resume()` brackets around every modal prompt in
`DevLoopConsole` (`devloop/console.py:907/940/969`, `:1102/1114`, `:1119/1133`, `:1138/1146`)
with `with <view>.region.modal():`. devloop is the one console that works today: this is a
**zero-behaviour-change refactor** and `tests/cli/devloop/test_renderer.py` must pass untouched
(spec AC25, §7 "devloop is the one working console").

---

## Scope

- `RunView`: replace `self._live: Optional[Live]` and `self._paused` (`renderer.py:40-41`) with
  `self.region: LiveRegion = LiveRegion(self.console, refresh_per_second=8, transient=False)` and a
  `self._paused: bool` flag that `pause()`/`resume()` still toggle (the poll loop skips work while
  paused — that behaviour stays); `pause()` → `self.region.pause()`, `resume()` →
  `self.region.resume()`; `run_live()` → `region.start()` / `region.update(self._build_display())` /
  `region.stop()`. Keep the constructor signature `(host, console=None, *, run_id="")` and every
  `_handle_*`, `poll_once`, `_build_display`, `_build_header`, `pending_gates`, `stop` unchanged.
- Drop the now-unused `from rich.live import Live` import in `renderer.py` if nothing else uses it
  (verify with grep before deleting).
- `DevLoopConsole`: add a private helper `_view_modal(self) -> ContextManager[None]` returning
  `self._active_view.region.modal()` when a view is active and `contextlib.nullcontext()`
  otherwise; rewrite the four pause/resume brackets (`_handle_gates`, `_cmd_new`, `_cmd_feature`,
  `_cmd_revise`) as `with self._view_modal():` blocks with identical bodies and identical
  exception handling.
- Add `tests/cli/devloop/test_live_region_delegation.py` proving delegation and that the existing
  renderer tests still pass.

**NOT in scope**: `LiveRegion` itself (TASK-3400); any change to envelope handlers, `SessionHost`
polling, wizard behaviour (`cli/wizard.py`, FEAT-519 M5 is deferred), `devloop/console.py`'s
`patch_stdout()` usage at `:816` (stays); the agent console (`repl.py`, TASK-3407).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/renderer.py` | MODIFY | `RunView` delegates `pause/resume/run_live` to a `LiveRegion` |
| `packages/ai-parrot/src/parrot/cli/devloop/console.py` | MODIFY | `_view_modal()` helper; four pause/resume brackets → `with self._view_modal():` |
| `packages/ai-parrot/tests/cli/devloop/test_live_region_delegation.py` | CREATE | delegation + regression tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# devloop/renderer.py (existing header, lines 7-18)
from __future__ import annotations                       # verified: packages/ai-parrot/src/parrot/cli/devloop/renderer.py:7
import asyncio                                           # verified: renderer.py:9
import logging                                           # verified: renderer.py:10
import time                                              # verified: renderer.py:11
from typing import Any, Dict, List, Optional, Type       # verified: renderer.py:12
from rich.console import Console, Group                  # verified: renderer.py:14
from rich.live import Live                               # verified: renderer.py:15  (REMOVE if unused after the change)
from rich.panel import Panel                             # verified: renderer.py:16
from rich.table import Table                             # verified: renderer.py:17
from rich.text import Text                               # verified: renderer.py:18
from parrot.cli.console import LiveRegion                # provided by TASK-3400 (packages/ai-parrot/src/parrot/cli/console.py)

# devloop/console.py (existing header, lines 7-22)
import contextlib                                        # stdlib — ADD
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set   # verified: console.py:14  (ADD ContextManager)
from prompt_toolkit import PromptSession                 # verified: console.py:16
from prompt_toolkit.patch_stdout import patch_stdout     # verified: console.py:17
from rich.console import Console                         # verified: console.py:18
from parrot.cli.devloop.renderer import RunView          # verified: console.py:22

# tests
import pytest
from rich.console import Console                         # verified: tests/cli/devloop/test_renderer.py:9
from parrot.cli.devloop.renderer import RunView          # verified: tests/cli/devloop/test_renderer.py:11
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/devloop/renderer.py
_POLL_INTERVAL = 0.15                                                   # line 22
class RunView:                                                          # line 26
    def __init__(self, host: Any, console: Optional[Console] = None, *, run_id: str = "") -> None   # line 29
        self.console = console or Console()                             # line 37
        self._live: Optional[Live] = None                               # line 40  (TO BE REPLACED)
        self._paused = False                                            # line 41  (KEEP as the poll-skip flag)
        self._stop = False                                              # line 42
    def poll_once(self) -> List[Any]                                    # line 47
    def pause(self) -> None:   # self._paused = True;  if self._live: self._live.stop()    # lines 82-86
    def resume(self) -> None:  # self._paused = False; if self._live: self._live.start()   # lines 88-92
    def stop(self) -> None:    # self._stop = True                                        # lines 94-96
    async def run_live(self, stop_event: Optional[asyncio.Event] = None) -> None          # line 98
        # with Live(self._build_display(), console=self.console, refresh_per_second=8, transient=False) as live:   # 103-108
        #     self._live = live                                                             # 109
        #     while not self._stop and not stop.is_set():                                   # 110
        #         if not self._paused: self.poll_once(); live.update(self._build_display())  # 111-113
        #         try: await asyncio.wait_for(stop.wait(), timeout=_POLL_INTERVAL); break   # 114-116
        #         except asyncio.TimeoutError: pass                                         # 117-118
        #     self._live = None                                                             # 119
    def _build_display(self) -> Group                                   # line 121
# grep counts (verified today): 'self._live' → 7 occurrences (lines 40, 85, 86, 91, 92, 109, 119); 'self._paused' → 4 (41, 84, 90, 111)

# packages/ai-parrot/src/parrot/cli/devloop/console.py
class DevLoopConsole:                                                   # (self._active_view: Optional[RunView] = None at line 61)
    async def _handle_gates(self, gates: Dict[str, Any]) -> None        # line ~903
        # if self._active_view: self._active_view.pause()               # lines 906-907  (inside `for gate_id, gate in gates.items():`)
        # ... resolution = await self._session.prompt_async("  Approve or reject? [a/r]: ")   # 929
        # else: ... if self._active_view: self._active_view.resume(); continue                # 938-941
        # comment = await self._session.prompt_async("  Comment (optional): ")               # 943
        # except (EOFError, KeyboardInterrupt): self.console.print("[dim]Gate skipped.[/dim]") # 964-965
        # if self._active_view: self._active_view.resume()              # lines 968-969
    async def _cmd_new(self, args: str) -> None                         # line 1099; pause 1101-1102, resume 1113-1114
    async def _cmd_feature(self, args: str) -> None                     # line 1116; pause 1118-1119, resume 1132-1133
    async def _cmd_revise(self, args: str) -> None                      # line 1135; pause 1137-1138, resume 1145-1146
# grep counts (verified today): 'self._active_view.pause()' → 4 (907, 1102, 1119, 1138); 'self._active_view.resume()' → 5 (940, 969, 1114, 1133, 1146)

# packages/ai-parrot/src/parrot/cli/console.py  (TASK-3400 — fixed by spec §3 M1)
class LiveRegion:
    def __init__(self, console: Optional[Console] = None, *, refresh_per_second: int = 8, transient: bool = False) -> None
    def start(self) -> None ; def stop(self) -> None ; def pause(self) -> None ; def resume(self) -> None
    def update(self, renderable: Any) -> None
    @contextlib.contextmanager
    def modal(self) -> Iterator[None]
    @property
    def is_terminal(self) -> bool

# packages/ai-parrot/tests/cli/devloop/test_renderer.py  (MUST STAY GREEN, UNTOUCHED)
def _make_view(envelopes) -> RunView:   # console = Console(record=True, force_terminal=True, width=120); RunView(host, console, run_id="run-test")   # lines 73-76
```

### Does NOT Exist
- ~~`RunView.region` today~~ — this task adds it.
- ~~`LiveRegion.is_paused`~~ — not in the TASK-3400 skeleton; keep `RunView._paused` as the poll-skip flag instead of inventing a property.
- ~~`DevLoopConsole._view_modal`~~ — added by this task.
- ~~`RunView.run_live` returning the `Live` object or exposing `_live` to callers~~ — grep shows `_live` is used only inside `renderer.py`; nothing in `console.py` reads it.
- ~~a `pause()`/`resume()` call in `devloop/console.py` outside the four brackets listed~~ — the 5th `resume()` (line 940) is the "skip gate" `continue` path inside `_handle_gates` and is covered by the same `with` block.
- ~~`from parrot.cli.devloop.console import ...` in tests~~ — the new test only needs `RunView`; do not import the console (heavy).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/cli/devloop/renderer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/devloop/console.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/cli/devloop/test_live_region_delegation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/devloop/renderer.py#RunView",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/renderer.py#RunView.pause",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/renderer.py#RunView.resume",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/renderer.py#RunView.run_live",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/console.py#DevLoopConsole._handle_gates",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/console.py#DevLoopConsole._cmd_new",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/console.py#DevLoopConsole._cmd_feature",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/console.py#DevLoopConsole._cmd_revise"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Zero behaviour change.** Same `refresh_per_second=8, transient=False`, same poll cadence
  (`_POLL_INTERVAL`), same skip-while-paused semantics, same messages. Any diff in
  `tests/cli/devloop/` output is a defect (spec AC25).
- The `_handle_gates` loop pauses per gate and resumes both on the "skip" `continue` path and
  at the end of each iteration: express that as one `with self._view_modal():` wrapping the body
  from the panel print to the final resume, keeping `continue` inside the `with` (the context
  manager resumes on exit either way).
- Keep `patch_stdout()` (`console.py:816`) — `LiveRegion` cooperates with it as the old code did.
- Run tests inside the worktree with `PYTHONPATH=packages/ai-parrot/src`; never `uv sync` there.
- `black` 120 cols, `ruff` clean, Google docstrings on the new helper.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/devloop/renderer.py:82-119` — the pattern being replaced by delegation.
- `packages/ai-parrot/tests/cli/devloop/test_renderer.py` — the regression suite (12 tests) that must stay green.
- `packages/ai-parrot/tests/cli/devloop/test_console.py` — existing console tests; also must stay green.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. In `renderer.py`, import `LiveRegion` and replace `self._live = None` with `self.region = LiveRegion(...)` — *why*: the region now owns the `Live` object.
2. Rewrite `pause`/`resume`/`run_live` to delegate — *why*: one discipline shared with the agent console (spec G7/AC12).
3. Remove `from rich.live import Live` only if `grep -c "Live(" renderer.py` is 0 afterwards — *why*: `ruff` F401 otherwise.
4. In `console.py`, add `import contextlib`, add `_view_modal()`, then rewrite the four brackets — *why*: modal discipline replaces manual pairs (FEAT-519 AC3 → this spec AC12/AC14).
5. Run `pytest packages/ai-parrot/tests/cli/devloop/test_renderer.py packages/ai-parrot/tests/cli/devloop/test_console.py -q` before and after — *why*: the refactor must be invisible.

### `packages/ai-parrot/src/parrot/cli/devloop/renderer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from rich.text import Text' packages/ai-parrot/src/parrot/cli/devloop/renderer.py)
# AFTER — insert below `from rich.text import Text` (verified: renderer.py:18)
from parrot.cli.console import LiveRegion  # provided by TASK-3400

# occurrences: 1 (verified: grep -c 'self._live: Optional\[Live\] = None' renderer.py)
# REPLACE `        self._live: Optional[Live] = None` (verified: renderer.py:40)
        self.region: LiveRegion = LiveRegion(self.console, refresh_per_second=8, transient=False)

# occurrences: 1 (verified: grep -c '"""Pause the live display (for modal prompts)."""' renderer.py)
# REPLACE the bodies of pause()/resume() (verified: renderer.py:82-92)
    def pause(self) -> None:
        """Pause the live display (for modal prompts) — delegates to ``LiveRegion.pause``."""
        self._paused = True
        self.region.pause()

    def resume(self) -> None:
        """Resume the live display after a modal prompt — delegates to ``LiveRegion.resume``."""
        self._paused = False
        self.region.resume()

# occurrences: 1 (verified: grep -c 'with Live(' renderer.py)
# REPLACE from `        with Live(` (renderer.py:103) through `            self._live = None` (renderer.py:119)
        self.region.update(self._build_display())
        self.region.start()
        try:
            while not self._stop and not stop.is_set():
                if not self._paused:
                    self.poll_once()
                    self.region.update(self._build_display())
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_POLL_INTERVAL)
                    break
                except asyncio.TimeoutError:
                    pass
        finally:
            self.region.stop()
        # FILL IN: delete `from rich.live import Live` (renderer.py:15) iff `grep -c "Live(" renderer.py` is now 0 — bounded by ruff F401
```
**Why this shape**: `LiveRegion` wraps `Live(..., refresh_per_second=8, transient=False)` with `start/stop/pause/resume`
(spec §3 M1), so the loop body is unchanged except that `live.update` becomes `region.update`. `_paused` stays
because the poll skip is `RunView` behaviour, not display behaviour.

### `packages/ai-parrot/src/parrot/cli/devloop/console.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c '^import asyncio' packages/ai-parrot/src/parrot/cli/devloop/console.py)
# AFTER — insert below `import asyncio` (verified: console.py:9)
import contextlib

# occurrences: 1 (verified: grep -c 'from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set' console.py)
# REPLACE line 14 (verified: console.py:14)
from typing import TYPE_CHECKING, Any, ContextManager, Dict, List, Optional, Set

# occurrences: 1 (verified: grep -c '    async def _handle_gates(self, gates: Dict\[str, Any\]) -> None:' console.py)
# BEFORE — insert above `    async def _handle_gates(...)` (verified: console.py:903)
    def _view_modal(self) -> ContextManager[None]:
        """Yield the terminal to a modal prompt.

        Returns ``self._active_view.region.modal()`` when a run view owns the
        display (pausing it for the block and resuming afterwards, even on
        exception) and a no-op ``contextlib.nullcontext()`` otherwise — the
        exact behaviour of the former ``if self._active_view: pause()`` /
        ``resume()`` pairs.
        """
        if self._active_view is not None:
            return self._active_view.region.modal()
        return contextlib.nullcontext()
```
**Why**: every former bracket was guarded by `if self._active_view:`; the helper preserves that guard in one place.

### `packages/ai-parrot/src/parrot/cli/devloop/console.py` (MODIFY — four brackets)
```python
# occurrences: 4 for 'self._active_view.pause()' (verified: grep -c) → each block below quotes surrounding context.

# (1) _handle_gates — REPLACE lines 906-907 (`            if self._active_view:` / `                self._active_view.pause()`
#     immediately after `        for gate_id, gate in gates.items():`) with:
            with self._view_modal():
#     then INDENT the loop body from `kind = getattr(gate, "kind", "")` (908) through `self.console.print("[dim]Gate skipped.[/dim]")` (965)
#     one level, DELETE lines 939-940 (`if self._active_view:` / `self._active_view.resume()` before `continue`) and
#     DELETE lines 968-969 (`if self._active_view:` / `self._active_view.resume()` after the try/except).
#     `continue` stays inside the `with` block — the context manager resumes on exit.

# (2) _cmd_new — REPLACE lines 1101-1102 (`if self._active_view:` / `self._active_view.pause()` right after the docstring
#     `"""Start a new run with the wizard."""`) with `with self._view_modal():`, indent the try/except that follows
#     (`brief = await self._collect_work_brief()` … `self.console.print(f"[bold red]Brief error:[/bold red] {exc}")`),
#     and DELETE lines 1113-1114 (`if self._active_view:` / `self._active_view.resume()`).

# (3) _cmd_feature — same transformation for lines 1118-1119 / 1132-1133 (docstring `"""Start a new feature-mode run via free-text intake (``/feature``, G3/G4)."""`).

# (4) _cmd_revise — same transformation for lines 1137-1138 / 1145-1146 (docstring `"""Start a revision-mode run."""`).
# FILL IN: perform the four edits with the bodies byte-identical apart from indentation — bounded by AC25 (tests/cli/devloop green)
```
**Why**: `modal()` pauses on enter and resumes on exit including exceptions (spec §3 M1), which is exactly what the
`try/except` + trailing `resume()` achieved; folding the `continue` path removes the duplicated resume at line 940.

### `packages/ai-parrot/tests/cli/devloop/test_live_region_delegation.py` (CREATE)
```python
"""RunView delegates its Live handling to LiveRegion (FEAT-573 TASK-3414, spec M14)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from parrot.cli.console import LiveRegion   # provided by TASK-3400
from parrot.cli.devloop.renderer import RunView


class _Host:
    def __init__(self) -> None:
        self.state = MagicMock(run_id="run-x", phase="running", summary="", jira_issue_key="", pr_url="", gates={})

    def replay_since(self, last_seq: int):
        return []


def _view() -> RunView:
    return RunView(_Host(), Console(record=True, force_terminal=True, width=100), run_id="run-x")


def test_runview_owns_a_live_region():
    view = _view()
    assert isinstance(view.region, LiveRegion)
    assert not hasattr(view, "_live")


def test_pause_resume_delegate(monkeypatch):
    view = _view()
    calls = []
    monkeypatch.setattr(view.region, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(view.region, "resume", lambda: calls.append("resume"))
    view.pause(); view.resume()
    assert calls == ["pause", "resume"]
    # FILL IN: assert view._paused toggles True then False — bounded by "poll skip semantics unchanged"


async def test_run_live_starts_updates_and_stops(monkeypatch):
    view = _view()
    events = []
    monkeypatch.setattr(view.region, "start", lambda: events.append("start"))
    monkeypatch.setattr(view.region, "stop", lambda: events.append("stop"))
    monkeypatch.setattr(view.region, "update", lambda r: events.append("update"))
    stop = asyncio.Event()
    task = asyncio.create_task(view.run_live(stop))
    await asyncio.sleep(0.2)
    stop.set()
    await task
    # FILL IN: assert events[0] == "start", events[-1] == "stop", events.count("update") >= 2 — bounded by _POLL_INTERVAL=0.15
```
**Why**: the test asserts delegation (the only thing that changed) while `test_renderer.py` continues to assert
envelope rendering (the thing that must not change).

### FILL IN checklist
- [ ] `renderer.py` — remove `from rich.live import Live` iff unused; bounded by ruff F401
- [ ] `console.py::_handle_gates/_cmd_new/_cmd_feature/_cmd_revise` — the four re-indentations with byte-identical bodies; bounded by AC25
- [ ] `test_live_region_delegation.py` — the three FILL IN assertions

---

## Acceptance Criteria

- [ ] `RunView` has a `region: LiveRegion` attribute and no `_live` attribute; `pause()`/`resume()` call the region (spec AC12)
- [ ] `grep -c "self._active_view.pause()\|self._active_view.resume()" packages/ai-parrot/src/parrot/cli/devloop/console.py` is `0`; all four modal sites use `with self._view_modal():`
- [ ] `pytest packages/ai-parrot/tests/cli/devloop/test_renderer.py -v` passes **without any edit to that file** (spec AC25)
- [ ] `pytest packages/ai-parrot/tests/cli/devloop/test_console.py -v` passes unchanged
- [ ] New tests pass: `pytest packages/ai-parrot/tests/cli/devloop/test_live_region_delegation.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/cli/devloop/renderer.py packages/ai-parrot/src/parrot/cli/devloop/console.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/devloop/test_live_region_delegation.py -q`
- `pytest packages/ai-parrot/tests/cli/devloop/test_renderer.py -q`
- `pytest packages/ai-parrot/tests/cli/devloop/test_console.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/devloop/test_live_region_delegation.py — see blueprint; minimum set:
# test_runview_owns_a_live_region          → region attribute present, _live gone
# test_pause_resume_delegate               → RunView.pause/resume → region.pause/resume, _paused flag toggles
# test_run_live_starts_updates_and_stops   → start → update* → stop ordering
```

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
4. **Update status** in `sdd/tasks/index/new-ui-cli-agents.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3414-devloop-live-region-convergence.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-coder native `sonnet` seat (attempt a735ac8dd8bc455f9bba3bf0c2c3abf2)
**Date**: 2026-09-18
**Notes**: `RunView.pause()`/`resume()` now delegate to a `LiveRegion` instance
(TASK-3400, already merged) instead of hand-rolled `Live` management;
`run_live()` uses `region.start()`/`region.update()`/`region.stop()`.
`DevLoopConsole` replaced 9 manual pause/resume call sites with a single
`_view_modal()` context manager delegating to `region.modal()`. Applied
the `unscoped-removal-reuses-full-uninstall-helper` pattern directly: read
`LiveRegion`'s actual `start/stop/pause/resume/modal` bodies before
delegating, confirmed semantics match exactly (and `modal()` is a strict
superset — also resumes on exception types the original code didn't
catch, matching the blueprint's stated intent).

**Blueprint inconsistency found and resolved soundly**: the Scope section
and Test Specification table implied `start → update → stop` ordering,
but the Implementation Blueprint's own code block calls `update()` before
`start()`. The coder verified `LiveRegion.start()`'s actual body (builds
`Live` from whatever `self._renderable` currently holds) and implemented
the literal blueprint code (update-before-start) since starting first
would show one blank frame — a real, if tiny, behavior change violating
AC25's "zero behaviour change" mandate. Wrote its own test assertions
against the actually-correct implemented behavior rather than the
blueprint's contradictory literal assertion suggestion.

Merge clean (`coder_merge` outcome=merged); 2 residual pre-existing lint
findings (B007/F841, confirmed via `git show HEAD:<file>` byte-identical
rule sets before/after) deferred to `/sdd-done`. Orchestrator ran the full
`packages/ai-parrot/tests/cli/devloop/` suite: **100 passed**, no
regressions.

**Feedback recorded**: none — clean delivery; `hasattr-duck-typing`
pattern correctly judged not applicable (identity check, not multi-shape
duck-typing); `unisolated-real-home-in-tests` correctly judged not
applicable (no filesystem convention path in scope).
**Deviations from spec**: test assertions verify actual correct behavior
rather than the blueprint's self-contradictory literal suggestion
(documented above).
