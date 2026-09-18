# TASK-3400: Shared console layer — `get_console()` and `LiveRegion`

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** (absorbed FEAT-519 Module 1). Today the CLI builds three independent
Rich `Console` objects, each forced to `sys.__stdout__` to dodge `prompt_toolkit.patch_stdout()`
mangling ANSI (`agent_repl.py:25`, `repl.py:128`, `renderer.py:80-82`), and the streaming
path writes raw bytes with `sys.stdout.write` (`renderer.py:257`). The sibling `parrot devloop`
already solved the "Rich `Live` vs prompt_toolkit" conflict with a modal pause/resume
discipline in `RunView` (`devloop/renderer.py:82-107`): exactly one writer owns the terminal
at a time.

This task extracts that proven pattern into a new module, `parrot/cli/console.py`:
a process-wide `get_console()` singleton (with a test seam) and a `LiveRegion` class with
`start/stop/pause/resume/update` and a `modal()` context manager. `LiveRegion` degrades to
plain sequential printing when the console is not a terminal so piped output never
contains cursor-control sequences (spec AC2, AC11, AC12, AC14; G7).

---

## Scope

- Create `parrot/cli/console.py` with `get_console()`, `set_console()`, `reset_console()`
  and `LiveRegion` exactly as the spec §3 Module 1 Interface Skeleton fixes them.
- `LiveRegion` wraps `rich.live.Live(renderable, console=..., refresh_per_second=8, transient=False)`;
  `pause()`→`Live.stop()`, `resume()`→`Live.start()`, `modal()` brackets the two; all
  idempotent.
- Non-TTY degradation: when `console.is_terminal` is `False`, `update()` prints the
  renderable once, `start/stop/pause/resume` are no-ops and `modal()` yields immediately.
- Unit tests for the singleton seam, the modal pause/resume order, and the non-TTY path
  (no `\x1b[` cursor-control sequences in captured output).

**NOT in scope**: changing `ResponseRenderer` (TASK-3405), `AgentREPL` (TASK-3407),
`agent_repl.py` (TASK-3413), `RunView`/`DevLoopConsole` (TASK-3414), agentd (TASK-3415).
Those tasks *consume* this module; this task only creates it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/console.py` | CREATE | `get_console()`, `set_console()`, `reset_console()`, `LiveRegion` |
| `packages/ai-parrot/tests/cli/test_console.py` | CREATE | Unit tests: singleton seam, modal order, non-TTY degradation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from rich.console import Console        # verified: packages/ai-parrot/src/parrot/cli/renderer.py:13
from rich.live import Live              # verified: packages/ai-parrot/src/parrot/cli/devloop/renderer.py:15
from rich.text import Text              # verified: packages/ai-parrot/src/parrot/cli/renderer.py:17
import contextlib                       # stdlib
import logging                          # stdlib (pattern: renderer.py:7)
import threading                        # stdlib
from typing import Any, Iterator, Optional   # stdlib
import io                               # stdlib (tests)
import pytest                           # verified: packages/ai-parrot/tests/cli/test_integration.py:14
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/devloop/renderer.py — REFERENCE PATTERN (do not import RunView)
class RunView:                                                     # line 26
    self._live: Optional[Live] = None                              # line 40
    self._paused = False                                           # line 41
    def pause(self) -> None:   # self._paused = True;  if self._live: self._live.stop()    # lines 82-86
    def resume(self) -> None:  # self._paused = False; if self._live: self._live.start()   # lines 88-92
    async def run_live(self, stop_event=None):                     # line 98
        # with Live(self._build_display(), console=self.console,
        #           refresh_per_second=8, transient=False) as live:   # lines 103-107

# rich (installed 15.0.0) — public API used
Console(file=<TextIO>, force_terminal: bool | None = None, width: int | None = None, record: bool = False)
Console.is_terminal -> bool            # property
Console.print(*objects, **kwargs) -> None
Live(renderable=None, *, console=None, refresh_per_second=4, transient=False, auto_refresh=True, ...)
Live.start(refresh: bool = False) -> None ; Live.stop() -> None ; Live.update(renderable, *, refresh=False) -> None
Live.is_started -> bool                # property
```

### Does NOT Exist
- ~~`parrot.cli.console`~~ — the module this task creates; nothing imports it yet.
- ~~`parrot.cli.theme`, `parrot.cli.live`, `parrot.console`~~ — no such modules.
- ~~`class ConsoleLayer`, `ParrotConsole`, `SharedConsole`~~ — do not invent alternative names; the spec fixes `get_console` / `LiveRegion`.
- ~~`RunView` as a reusable base class~~ — it is coupled to dev-loop `SessionHost`; copy the *pattern* (`Live.stop()/start()`), never subclass or instantiate it here.
- ~~`_BlockingSafeFile`~~ — exists in `renderer.py:22-56` but is being **deleted** by TASK-3405; do not wrap the console file with it.
- ~~`Console(file=sys.__stdout__, force_terminal=True)` as the shared console~~ — the spec forbids the bypass; `get_console()` constructs `Console()` normally.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/console.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/cli/test_console.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/devloop/renderer.py#RunView",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/renderer.py#RunView.pause",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/renderer.py#RunView.resume",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/renderer.py#RunView.run_live"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# devloop/renderer.py:82-92 — the exact discipline to extract
def pause(self) -> None:
    self._paused = True
    if self._live:
        self._live.stop()

def resume(self) -> None:
    self._paused = False
    if self._live:
        self._live.start()
```

### Key Constraints
- Keep `refresh_per_second=8, transient=False` defaults (spec §7 "Homologate, don't invent").
- `get_console()` must be lazy and thread-safe enough for a CLI (a module lock around first
  construction is sufficient); `set_console(None)` behaves like `reset_console()`.
- No `sys.__stdout__` bypass, no `force_terminal=True` in the production path — tests pass
  their own `Console(file=io.StringIO(), force_terminal=True)`.
- `LiveRegion` must never raise on double `start()`/`stop()`; `resume()` before `start()` is a no-op.
- Inside a worktree run tests with `PYTHONPATH=packages/ai-parrot/src pytest ...`; never `uv sync` there.
- Google-style docstrings, strict typing, `self.logger = logging.getLogger(__name__)`.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/devloop/renderer.py:26-120` — the pattern being extracted.
- `packages/ai-parrot/src/parrot/cli/renderer.py:69-83` — the three-console problem this replaces (edited by TASK-3405, not here).
- `sdd/specs/new-ui-cli-agents.spec.md` §3 Module 1, §7 Patterns/Gotchas, AC11–AC14.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker.

### Steps (in order)
1. Write `console.py` with the module-level singleton and its two seams — *why*: AC12 needs exactly one `Console(` construction in `parrot/cli/`, and tests need to swap it.
2. Implement `LiveRegion` around `rich.live.Live` with the four state methods + `update` — *why*: this is the FEAT-519 "one writer at a time" discipline every presenter will rely on.
3. Add the non-terminal branch to every method — *why*: AC2 — piped output must contain no cursor-control sequences.
4. Write the tests, including the `\x1b[` scan on a non-TTY console — *why*: AC2/AC14 are verified by test, not by inspection.

### `packages/ai-parrot/src/parrot/cli/console.py` (CREATE)
```python
"""Shared Rich console and the modal ``LiveRegion`` discipline for the Parrot CLI (FEAT-573 M1).

Extracts the pause/resume pattern proven in ``parrot.cli.devloop.renderer.RunView``
(devloop/renderer.py:82-107): exactly one writer owns the terminal at a time.
"""
from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any, Iterator, Optional

from rich.console import Console  # verified: parrot/cli/renderer.py:13
from rich.live import Live        # verified: parrot/cli/devloop/renderer.py:15

_console: Optional[Console] = None
_console_lock = threading.Lock()


def get_console() -> Console:
    """Return the process-wide shared Rich Console (created on first call)."""
    global _console
    with _console_lock:
        if _console is None:
            _console = Console()
        return _console


def set_console(console: Optional[Console]) -> None:
    """Override (or clear, with ``None``) the shared console. Test seam."""
    global _console
    with _console_lock:
        _console = console


def reset_console() -> None:
    """Restore lazy creation on the next ``get_console()`` call."""
    set_console(None)
```

**Part 2 of the same file** — continue appending to `packages/ai-parrot/src/parrot/cli/console.py` (split only to respect the 80-line block cap):
```python
class LiveRegion:
    """Managed ``rich.live.Live`` area with 'one writer at a time' discipline.

    When ``console.is_terminal`` is False every ``update()`` prints the renderable once,
    sequentially, and ``modal()`` is a no-op — piping stays clean.
    """

    def __init__(self, console: Optional[Console] = None, *, refresh_per_second: int = 8, transient: bool = False) -> None:
        self.console = console or get_console()
        self._refresh_per_second = refresh_per_second
        self._transient = transient
        self._live: Optional[Live] = None
        self._paused = False
        self._renderable: Any = ""
        self.logger = logging.getLogger(__name__)

    @property
    def is_terminal(self) -> bool:
        """``console.is_terminal`` of the bound console."""
        return bool(self.console.is_terminal)

    def start(self) -> None:
        """Start the Live display (idempotent; no-op on non-terminals)."""
        # FILL IN: if not is_terminal → return; if self._live is None → build
        # Live(self._renderable, console=self.console, refresh_per_second=..., transient=...)
        # and call .start() — bounded by spec §7 defaults (8/s, transient=False).

    def stop(self) -> None:
        """Stop the Live display, leaving the last frame on screen (idempotent)."""
        # FILL IN: if self._live is not None → self._live.stop(); self._live = None; self._paused = False

    def pause(self) -> None:
        """``Live.stop()`` so another writer may own the terminal."""
        # FILL IN: mirror RunView.pause (devloop/renderer.py:82-86): set _paused, stop if started.

    def resume(self) -> None:
        """``Live.start()`` after a pause; no-op if never started."""
        # FILL IN: mirror RunView.resume (devloop/renderer.py:88-92); guard `if self._live is not None`.

    def update(self, renderable: Any) -> None:
        """Replace the region content (repainted on the next refresh tick)."""
        self._renderable = renderable
        # FILL IN: non-terminal → self.console.print(renderable) once — bounded by AC2;
        # terminal with live started and not paused → self._live.update(renderable).

    @contextlib.contextmanager
    def modal(self) -> Iterator[None]:
        """Pause for the duration of a prompt/modal interaction, then resume."""
        self.pause()
        try:
            yield
        finally:
            self.resume()
```
**Why this shape**: signatures are fixed by spec §3 Module 1 and consumed verbatim by
TASK-3405/3407/3414. The singleton lives at module level (not on a class) so AC12 can be
checked with a single grep. `modal()` always resumes in `finally` so an exception inside a
prompt cannot leave the region stopped.

### `packages/ai-parrot/tests/cli/test_console.py` (CREATE)
```python
"""Unit tests for parrot.cli.console (FEAT-573 TASK-3400)."""
from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest  # verified: packages/ai-parrot/tests/cli/test_integration.py:14
from rich.console import Console  # verified: parrot/cli/renderer.py:13
from rich.text import Text  # verified: parrot/cli/renderer.py:17

from parrot.cli.console import LiveRegion, get_console, reset_console, set_console


@pytest.fixture(autouse=True)
def _isolated_console():
    reset_console()
    yield
    reset_console()


def _tty_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=True, width=100)


def _pipe_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=100)


def test_get_console_singleton_and_override() -> None:
    first = get_console()
    assert get_console() is first
    override = _tty_console()
    set_console(override)
    assert get_console() is override
    reset_console()
    assert get_console() is not override


def test_live_region_non_tty_prints_sequentially() -> None:
    console = _pipe_console()
    region = LiveRegion(console)
    assert region.is_terminal is False
    region.start()
    region.update(Text("hello"))
    with region.modal():
        pass
    region.stop()
    out = console.file.getvalue()
    assert "hello" in out
    assert "\x1b[" not in out  # no cursor-control sequences on a pipe (AC2)


def test_live_region_modal_pauses_and_resumes(monkeypatch: pytest.MonkeyPatch) -> None:
    region = LiveRegion(_tty_console())
    fake_live = MagicMock()
    region._live = fake_live  # inject a started Live
    with region.modal():
        fake_live.stop.assert_called_once()
        fake_live.start.assert_not_called()
    fake_live.start.assert_called_once()
    # FILL IN: assert stop() is idempotent (second call does not raise) and resume()
    # before start() is a no-op — bounded by spec §3 M1 "idempotent".
```
**Why**: each test maps to a §4 row (`test_get_console_singleton_and_override`,
`test_live_region_non_tty_prints_sequentially`, `test_live_region_modal_pauses_and_resumes`).
The autouse fixture protects other test modules from a leaked override.

### FILL IN checklist
- [ ] `console.py::LiveRegion.start/stop/pause/resume/update` — state transitions per `RunView` pattern; bounded by spec §7 defaults and AC2.
- [ ] `test_console.py::test_live_region_modal_pauses_and_resumes` — idempotency assertions; bounded by spec §3 M1.

---

## Acceptance Criteria

- [ ] `from parrot.cli.console import get_console, set_console, reset_console, LiveRegion` works.
- [ ] `get_console()` returns the same object on repeated calls; `set_console`/`reset_console` behave as tested (spec AC12 precondition).
- [ ] On a non-terminal console, `LiveRegion.update()` prints once and the output contains no `\x1b[` sequences (spec AC2).
- [ ] `modal()` calls `Live.stop()` on entry and `Live.start()` on exit, also when the body raises (spec AC14 precondition).
- [ ] `grep -c 'Console(' packages/ai-parrot/src/parrot/cli/console.py` is exactly 1 (spec AC12).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/test_console.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/cli/console.py packages/ai-parrot/tests/cli/test_console.py` clean; `mypy` clean on `console.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_console.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_console.py — see blueprint
def test_get_console_singleton_and_override(): ...
def test_live_region_non_tty_prints_sequentially(): ...
def test_live_region_modal_pauses_and_resumes(monkeypatch): ...
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
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3400-shared-console-live-region.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-coder native `sonnet` seat (attempt f90862da9c0447fabaedca003eba2f6a), via sdd-worker orchestrator
**Date**: 2026-09-18
**Notes**: Implemented `packages/ai-parrot/src/parrot/cli/console.py` per the
blueprint: module-level `get_console()`/`set_console()`/`reset_console()`
singleton seam plus `LiveRegion` (start/stop/pause/resume/update + `modal()`
contextmanager) wrapping `rich.live.Live`, mirroring
`devloop/renderer.py:82-107`'s `RunView.pause/resume` pattern. Degrades to
sequential printing when the console is not a terminal (AC2): `start()`/
`pause()`/`resume()` are no-ops and `update()` falls back to a single
`console.print()`. `modal()` always resumes in a `finally` block. Guard test
`test_console.py` covers singleton/override, non-TTY sequential print + ANSI
scan, and modal pause/resume/idempotency.

`ruff check` and `mypy` clean. `pytest packages/ai-parrot/tests/cli/test_console.py
-q`: 3 passed (verified directly by the orchestrator after merge). The
broader merge-tier `select_tests` sweep hits the same pre-existing, repo-wide
test-collection failure on ~25 unrelated files (confirmed present on `dev`
itself, independent of this change — see TASK-3399's Completion Note for the
root cause) and is out of scope here.

Merge was clean (`coder_merge` outcome=merged, no unexpected files); engine
lint autofix (black) applied automatically.

**Feedback recorded**: none — clean delivery, no confirmed defect.
**Deviations from spec**: none.
