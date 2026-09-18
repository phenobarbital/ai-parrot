# TASK-3401: UI mode resolution and CLI state paths (`parrot/cli/modes.py`)

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 2**. `parrot agent` gains `--ui auto|inline|tui` (G2) plus two per-agent
persisted files: the composer's input history (G6, spec AC10) and a "last session" pointer
that makes `--session last` work (G5, spec AC9). Both live under the per-user parrot home
directory, honouring the existing `PARROT_HOME` convention (`knowledge/wiki/project.py:1009`,
`conf.py:556`) rather than inventing a new location.

Everything here is pure functions and one Pydantic model with no I/O beyond the state
files, so it is a root of the task graph: `TurnRunner` (TASK-3404) calls
`save_session_pointer`, `AgentREPL` (TASK-3407) uses `history_path`, `/resume` (TASK-3406)
uses `load_session_pointer`, and the Click entry point (TASK-3413) calls `resolve_ui_mode`.

---

## Scope

- Create `parrot/cli/modes.py` with `UIMode`, `UIModeError`, `SessionPointer`,
  `resolve_ui_mode`, `is_interactive`, `cli_state_dir`, `agent_slug`, `history_path`,
  `load_session_pointer`, `save_session_pointer` — signatures per spec §3 Module 2.
- Resolution rule (spec §8 resolved question 6): TUI iff `stdin_isatty and stdout_isatty and (term or "").lower() != "dumb"`;
  explicit `TUI` on a non-TTY raises `UIModeError`; never return `AUTO`.
- State directory `$PARROT_HOME`-or-`~/.parrot` + `cli`, created `0o700`; files `0o600`;
  atomic pointer writes (`tmp` + `os.replace`).
- Parametrised unit tests for the mode matrix, path/permission behaviour under a
  monkeypatched `PARROT_HOME`, slug sanitisation and pointer round-trip / corrupt-file handling.

**NOT in scope**: wiring `--ui` into Click (TASK-3413), using `FileHistory` (TASK-3407),
saving the pointer after a turn (TASK-3404), the `/resume` command (TASK-3406).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/modes.py` | CREATE | `UIMode`, `UIModeError`, `SessionPointer`, mode resolution, state paths |
| `packages/ai-parrot/tests/cli/test_modes.py` | CREATE | Mode matrix, PARROT_HOME + permissions, slug, pointer round-trip |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from pydantic import BaseModel, Field    # verified: packages/ai-parrot/src/parrot/cli/repl.py:18
from enum import Enum                    # stdlib
from datetime import datetime            # stdlib (pattern: commands.py:14)
from pathlib import Path                 # stdlib (pattern: commands.py:15)
import json, logging, os, re, tempfile   # stdlib
from typing import Callable, Optional    # stdlib
import pytest                            # verified: packages/ai-parrot/tests/cli/test_integration.py:14
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py — CONVENTION ONLY (do not import; it drags the wiki package)
def parrot_home() -> Path:                                       # line 1009
    raw = os.environ.get("PARROT_HOME") or f"~/{PARROT_DIR}"     # line 1020  (PARROT_DIR == ".parrot")
    return Path(raw).expanduser()                                # line 1021

# packages/ai-parrot/src/parrot/conf.py
_parrot_home_default = str(Path.home() / ".parrot")              # line 556
```

### Does NOT Exist
- ~~`parrot.cli.modes`~~ — created by this task.
- ~~`parrot.cli.state`, `parrot.cli.paths`, `parrot.cli.config_dir`~~ — no such modules; do not invent alternatives.
- ~~`UIMode` anywhere in `parrot/`~~ — new enum; `REPLConfig.ui_mode` is added later by TASK-3407 and imports it from here.
- ~~`ConversationMemory.list_sessions()` / a "recent sessions" API~~ — not verified to exist; `--session last` relies solely on the pointer file this task defines.
- ~~`platformdirs`~~ — installed transitively (Textual dependency) but **not** a declared parrot dependency; do not import it. Use the `PARROT_HOME` convention.
- ~~`parrot.conf.PARROT_HOME`~~ — `conf.py` exposes `_parrot_home_default` (private) and storage paths, not a public `PARROT_HOME` constant; read the env var directly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/modes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/cli/test_modes.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#parrot_home"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# knowledge/wiki/project.py:1020-1021 — read PARROT_HOME on every call, never cache at import time
raw = os.environ.get("PARROT_HOME") or "~/.parrot"
return Path(raw).expanduser()
```

### Key Constraints
- Read `PARROT_HOME` on every call (tests `monkeypatch.setenv`); never cache at import.
- `cli_state_dir()` creates the directory with mode `0o700` (`mkdir(parents=True, exist_ok=True)` then `chmod`).
- `history_path()` only returns the path and ensures its parent exists; it does **not**
  create the file (prompt_toolkit's `FileHistory` does) — but if the file exists, `chmod 0o600`.
- `save_session_pointer()` writes JSON via `tempfile.NamedTemporaryFile(dir=..., delete=False)`
  + `os.replace`, then `chmod 0o600`.
- `agent_slug()` : lowercase, every char not in `[a-z0-9._-]` → `_`, collapse runs, strip leading dots (no hidden files).
- Inside a worktree run tests with `PYTHONPATH=packages/ai-parrot/src pytest ...`; never `uv sync` there.
- Pydantic v2, Google docstrings, strict typing, module `logger = logging.getLogger(__name__)`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1009-1021` — `PARROT_HOME` convention.
- `packages/ai-parrot/src/parrot/cli/commands.py:245-256` — existing path-safety style (`/export` guard).
- `sdd/specs/new-ui-cli-agents.spec.md` §3 Module 2, §8 resolved Q6, AC1, AC2, AC9, AC10.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker.

### Steps (in order)
1. Write the enum, error and model — *why*: `UIMode` values are the exact `--ui` choices Click will expose (TASK-3413).
2. Implement `resolve_ui_mode` / `is_interactive` as pure functions taking TTY flags and `TERM` as arguments — *why*: the Click layer passes `sys.stdin.isatty()` etc.; pure inputs make the matrix testable without a PTY.
3. Implement the state-path helpers with explicit permission bits — *why*: AC10 requires `0o600` files; the composer history may contain secrets typed by the user.
4. Write the parametrised tests under a `tmp_path` `PARROT_HOME` — *why*: never touch the developer's real `~/.parrot`.

### `packages/ai-parrot/src/parrot/cli/modes.py` (CREATE)
```python
"""UI mode resolution and per-user CLI state paths for ``parrot agent`` (FEAT-573 M2)."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field  # verified: parrot/cli/repl.py:18

logger = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


class UIMode(str, Enum):
    """Presentation mode requested on the command line."""

    AUTO = "auto"
    INLINE = "inline"
    TUI = "tui"


class UIModeError(ValueError):
    """Raised when an explicitly requested mode cannot run on this terminal."""


class SessionPointer(BaseModel):
    """Last conversation session used with an agent (for ``--session last``)."""

    agent_name: str
    last_session_id: str
    updated_at: datetime = Field(default_factory=datetime.now)


def is_interactive(*, stdin_isatty: bool, stdout_isatty: bool) -> bool:
    """True when both streams are TTYs; False selects batch/line mode."""
    return bool(stdin_isatty and stdout_isatty)


def resolve_ui_mode(requested: UIMode, *, stdin_isatty: bool, stdout_isatty: bool, term: Optional[str]) -> UIMode:
    """Resolve ``AUTO`` to ``INLINE`` or ``TUI``; pass ``INLINE``/``TUI`` through.

    Raises:
        UIModeError: when ``TUI`` is requested explicitly but the streams are not both TTYs
            (or ``TERM`` is ``dumb``).
    """
    tui_capable = is_interactive(stdin_isatty=stdin_isatty, stdout_isatty=stdout_isatty) and (term or "").lower() != "dumb"
    # FILL IN: AUTO → TUI if tui_capable else INLINE; TUI and not tui_capable → raise UIModeError
    # with a message naming `--ui inline`; INLINE → INLINE — bounded by spec §8 Q6 / AC1.
    raise NotImplementedError


def cli_state_dir() -> Path:
    """``$PARROT_HOME`` or ``~/.parrot`` (wiki/project.py:1009 convention) + ``cli``; created ``0o700``."""
    raw = os.environ.get("PARROT_HOME") or "~/.parrot"
    path = Path(raw).expanduser() / "cli"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def agent_slug(agent_name: str) -> str:
    """Filesystem-safe slug: lowercase, ``[^a-z0-9._-]`` → ``_``, no leading dots."""
    # FILL IN: apply _SLUG_RE, collapse repeated '_' and lstrip('.'); empty → 'agent' — bounded by AC10.
    raise NotImplementedError


def history_path(agent_name: str) -> Path:
    """``cli_state_dir()/history/<slug>.txt`` (prompt_toolkit FileHistory format); file mode ``0o600`` when present."""
    # FILL IN: mkdir parent 0o700; if path.exists(): os.chmod(path, 0o600); return path.


def load_session_pointer(agent_name: str) -> Optional[SessionPointer]:
    """Read ``cli_state_dir()/sessions/<slug>.json``; ``None`` when absent or invalid."""
    # FILL IN: try json.loads + SessionPointer.model_validate; on (OSError, ValueError) log at debug and return None.


def save_session_pointer(agent_name: str, session_id: str) -> None:
    """Atomic write (tmp + ``os.replace``) of the pointer file, mode ``0o600``."""
    # FILL IN: build SessionPointer(agent_name=..., last_session_id=session_id); write model_dump_json()
    # to tempfile.NamedTemporaryFile(dir=parent, delete=False); os.replace; os.chmod 0o600 — bounded by AC9/AC10.
```
**Why this shape**: every name and signature is fixed by spec §3 Module 2 and consumed
by four other tasks; changing one breaks their blueprints. `resolve_ui_mode` never returns
`AUTO` so callers can `if mode is UIMode.TUI` without a third branch.

### `packages/ai-parrot/tests/cli/test_modes.py` (CREATE)
```python
"""Unit tests for parrot.cli.modes (FEAT-573 TASK-3401)."""
from __future__ import annotations

import os
import stat

import pytest  # verified: packages/ai-parrot/tests/cli/test_integration.py:14

from parrot.cli.modes import (
    SessionPointer, UIMode, UIModeError, agent_slug, cli_state_dir, history_path,
    is_interactive, load_session_pointer, resolve_ui_mode, save_session_pointer,
)


@pytest.fixture
def parrot_home(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    ("requested", "stdin", "stdout", "term", "expected"),
    [
        (UIMode.AUTO, True, True, "xterm-256color", UIMode.TUI),
        (UIMode.AUTO, True, True, "dumb", UIMode.INLINE),
        (UIMode.AUTO, False, True, "xterm", UIMode.INLINE),
        (UIMode.AUTO, True, False, "xterm", UIMode.INLINE),
        (UIMode.AUTO, True, True, None, UIMode.TUI),
        (UIMode.INLINE, True, True, "xterm", UIMode.INLINE),
        (UIMode.TUI, True, True, "xterm", UIMode.TUI),
    ],
)
def test_resolve_ui_mode_matrix(requested, stdin, stdout, term, expected) -> None:
    assert resolve_ui_mode(requested, stdin_isatty=stdin, stdout_isatty=stdout, term=term) is expected


def test_explicit_tui_on_non_tty_raises() -> None:
    with pytest.raises(UIModeError):
        resolve_ui_mode(UIMode.TUI, stdin_isatty=False, stdout_isatty=True, term="xterm")


def test_state_paths_honour_parrot_home_and_perms(parrot_home) -> None:
    d = cli_state_dir()
    assert d == parrot_home / "cli"
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    save_session_pointer("My Agent!", "sess-1")
    p = parrot_home / "cli" / "sessions" / "my_agent_.json"
    assert p.exists() and stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert history_path("My Agent!") == parrot_home / "cli" / "history" / "my_agent_.txt"


def test_session_pointer_roundtrip_and_invalid_json(parrot_home) -> None:
    save_session_pointer("a", "s1")
    ptr = load_session_pointer("a")
    assert isinstance(ptr, SessionPointer) and ptr.last_session_id == "s1"
    (parrot_home / "cli" / "sessions" / "a.json").write_text("{not json", encoding="utf-8")
    assert load_session_pointer("a") is None
    assert load_session_pointer("never-saved") is None
    # FILL IN: agent_slug edge cases ("", "..hidden", "A/B") — bounded by the slug rule in Key Constraints.
```
**Why**: rows map to spec §4 (`test_resolve_ui_mode_matrix`, `test_state_paths_honour_parrot_home_and_perms`,
`test_session_pointer_roundtrip_and_invalid_json`). The slug expectation `my_agent_` pins
the sanitisation rule so `history_path` and `save_session_pointer` agree on the file name.

### FILL IN checklist
- [ ] `modes.py::resolve_ui_mode` — AUTO/TUI/INLINE branches; bounded by spec §8 Q6, AC1.
- [ ] `modes.py::agent_slug` — sanitisation + empty fallback; bounded by AC10.
- [ ] `modes.py::history_path/load_session_pointer/save_session_pointer` — permission bits and atomic write; bounded by AC9/AC10.
- [ ] `test_modes.py` — slug edge cases.

---

## Acceptance Criteria

- [ ] `from parrot.cli.modes import UIMode, UIModeError, SessionPointer, resolve_ui_mode, is_interactive, cli_state_dir, agent_slug, history_path, load_session_pointer, save_session_pointer` works.
- [ ] `resolve_ui_mode` never returns `UIMode.AUTO`; `TERM=dumb` and any non-TTY stream yield `INLINE`; explicit `TUI` on a non-TTY raises `UIModeError` (spec AC1).
- [ ] With `PARROT_HOME=<tmp>`, `cli_state_dir()` is `<tmp>/cli` with mode `0o700`; pointer files are `0o600` (spec AC10).
- [ ] Corrupt or missing pointer files yield `None`, never an exception (spec AC9).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/test_modes.py -v`
- [ ] `ruff check` and `mypy` clean on `modes.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_modes.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_modes.py — see blueprint
def test_resolve_ui_mode_matrix(requested, stdin, stdout, term, expected): ...
def test_explicit_tui_on_non_tty_raises(): ...
def test_state_paths_honour_parrot_home_and_perms(parrot_home): ...
def test_session_pointer_roundtrip_and_invalid_json(parrot_home): ...
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
7. **Move this file** to `tasks/completed/TASK-3401-ui-modes-and-state-paths.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-coder native `sonnet` seat (attempt ac7f46b1ebca4ebd90eec44439cdc416)
**Date**: 2026-09-18
**Notes**: Implemented `parrot/cli/modes.py` exactly per blueprint —
`UIMode`, `UIModeError`, `SessionPointer`, `resolve_ui_mode` (never returns
`AUTO`; explicit `TUI` on a non-TTY raises), `is_interactive`,
`cli_state_dir` (`0o700`), `agent_slug` (sanitize + collapse `_` + strip
leading dots, empty → `"agent"`), `history_path` (`0o600` when present,
never creates the file), `load_session_pointer`/`save_session_pointer`
(atomic tmp+`os.replace`, `0o600`). Guard test covers the mode matrix,
non-TTY `UIModeError`, path/permission behaviour under a monkeypatched
`PARROT_HOME`, slug edge cases, and pointer round-trip/corrupt-JSON.

Merge was clean (`coder_merge` outcome=merged, no unexpected files); engine
lint autofix (black) applied automatically. The native attempt could not
itself run the mandated `pytest` (its sandboxed sub-worktree lacks the
compiled `parrot.utils.types` Cython extension — a pre-existing,
documented worktree limitation, not a defect); it reported `blocked`
without committing after independently sanity-checking the logic via a
standalone module load. The orchestrator verified the delivered content
line-by-line against the blueprint, committed it in the sub-worktree,
merged it, and ran `pytest packages/ai-parrot/tests/cli/test_modes.py -v`
in the top-level worktree (which has the compiled extension): **14
passed**.

**Feedback recorded**: none — clean, correct delivery; the stop was a
confirmed environment limitation, not a modeling defect.
**Deviations from spec**: none.
