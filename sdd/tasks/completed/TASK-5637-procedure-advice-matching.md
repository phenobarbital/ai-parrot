# TASK-5637: Hook-side advice module — roots, index loading and command matching

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (first half) and design research S2: everything a pre-tool guard needs must be on
a **stdlib-only** fast path, because a hook runs on every tool call. This task creates
`procedure_advice.py` with the parts that do not decide anything: locating the primary checkout,
loading the compiled index, and matching a Bash command against the index guards. TASK-5638 adds
the probes and the decision.

---

## Scope

- Create `parrot/sdd/scripts/procedure_advice.py` with: `INDEX_SCHEMA_VERSION`, `ESCAPE_ENV`,
  `LAUNCHER_MARKERS`, `Advice`, `shared_root`, `checkout_root`, `load_index`, `command_segments`,
  `leading_command`, `match_guards`.
- **stdlib imports only** at module level; no `parrot` import; no `main()`; never raise.
- Create `tests/sdd/test_procedure_advice.py`.

**NOT in scope**: `LOCAL_PROBES`, `apply_check`, `evaluate_command` (TASK-5638); the guards that
call this module (TASK-5645, TASK-5646); writing the index (TASK-5639).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` | CREATE | stdlib-only hook helper (first half) |
| `packages/ai-parrot/tests/sdd/test_procedure_advice.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev).

### Verified Imports
```python
# Standard library only: fnmatch, json, os, shlex, dataclasses, pathlib, typing.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py — the pattern to follow (stdlib only,
# no parrot import at module level, never a non-zero exit)   module docstring :1-12, imports :14-24
def find_root(cwd: str | Path | None) -> Path | None: ...      # :58  walks up to a `.git` entry, no subprocess

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py
LAUNCHER_MARKERS = ("PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_CACHE_DIR")   # :624  (copy the VALUES; do not import)

# A linked worktree, as modelled by packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py:41-50:
#   <worktree>/.git            is a FILE containing "gitdir: <main>/.git/worktrees/<name>\n"
#   <gitdir>/commondir         contains a path relative to <gitdir>, e.g. "../..\n"  -> <main>/.git
```

Compiled index shape this module reads (spec §2 "Compiled index"; written by TASK-5639):
```json
{"schema_version": 1, "generation": "<sha1>", "sources": [{"path": "sdd/procedures/x.yaml", "sha1": "<hex>"}],
 "guards": [{"procedure": "sdd:task-close", "kind": "entry", "executable": "parrot",
             "argv_prefix": ["sdd", "task", "close"], "path_globs": [],
             "scope": {"task": {"argv": 0}, "feature": {"argv": 1}}}],
 "procedures": {"sdd:task-close": {"title": "...", "mode": "mandatory", "command": "...", "use_instead": "...",
                "advice": "...", "preconditions": [{"probe": "task.status", "expect": "in-progress", "args": {}, "cost": "local"}]}}}
```

### Does NOT Exist
- ~~`parrot.sdd.scripts.procedure_advice`~~ — this task creates it.
- ~~An import of `parrot.knowledge.wiki.project.find_shared_root` here~~ — forbidden: it would
  import pydantic and the wiki package. `shared_root` re-states the logic with the stdlib.
- ~~`pydantic`, `yaml`, `sqlite3`, `subprocess` in this module~~ — forbidden (spec §5; a test
  enforces the first three).
- ~~A `main()` in this module~~ — it must not have one (a helper with `main()` has to be mounted in
  the `parrot sdd` CLI; `test_sdd_cli_mounts_every_helper` enforces it).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_procedure_advice.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py#find_root"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- **Never raise**: every public function catches its own errors and returns the "nothing" value
  (`None`, `[]`, `("", [])`).
- **Segments** (spec rev 0.3 decision 7): a compound command is split into segments on the shell
  operators `&&`, `||`, `;`, `|` and on newlines, respecting quotes. Use
  `shlex.shlex(line, posix=True, punctuation_chars=True)` with `whitespace_split=True`: it returns
  operator tokens separately. An unbalanced quote (`ValueError`) yields no segments.
- **`leading_command`** looks at the segments in order and returns the first one that is a real
  command: it drops leading `NAME=value` assignments, then the wrappers `rtk`, `sudo` (and its
  `-x` options), `timeout` (its options and one duration token) and `uv run` (and its `-x`
  options); a segment whose command is `cd` is skipped. The executable is returned as a basename
  (`/usr/bin/git` -> `git`).
- **`match_guards`** applies the same cleaning to **every** segment and returns, for each index
  guard that matches a segment, a **copy** of the guard entry with one extra key `"argv"`: the
  segment's arguments after the executable and the `argv_prefix`. A guard matches when the
  executable equals `guard["executable"]`, the arguments start with `guard["argv_prefix"]`, and —
  when `path_globs` is not empty — at least one remaining argument, normalized to a repo-relative
  POSIX path (strip a leading `./`), matches one glob with `fnmatch.fnmatchcase`.
- Fixtures are local to the test file (no `conftest.py`).

---

## Implementation Blueprint

### Steps (in order)
1. Write the constants, `Advice`, `shared_root`, `checkout_root`, `load_index` — *why*: the guards
   need a plane location without a subprocess.
2. Write `command_segments`, `leading_command`, `match_guards` — *why*: matching is pure text
   work and is the only cost a non-matching command pays.
3. Write the tests, including the subprocess import test.

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` (CREATE)
```python
"""Hook-side procedure advice (FEAT-891): stdlib only, no parrot import, never raises.

Loads both as ``parrot.sdd.scripts.procedure_advice`` and as a script sibling of the guards.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

INDEX_SCHEMA_VERSION = 1
ESCAPE_ENV = "PARROT_ALLOW_PROCEDURE"
LAUNCHER_MARKERS = ("PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_CACHE_DIR")  # same values as worktree_environment.py
PLANE_DIR = Path(".parrot") / "procedure"
INDEX_FILE = "procedures.json"
MAX_INDEX_BYTES = 262144
_OPERATORS = frozenset({"&&", "||", ";", "|", "&"})


@dataclass(frozen=True)
class Advice:
    """Outcome of the procedure check for one command."""

    decision: Literal["none", "advise", "deny"]
    text: str = ""


def checkout_root(cwd: Path) -> Path | None:
    """Nearest ancestor of ``cwd`` holding a ``.git`` entry (directory or file); None when there is none."""
    # FILL IN: same walk as dangerous_actions.find_root, but return None when nothing is found.


def shared_root(cwd: Path) -> Path | None:
    """Primary checkout for ``cwd``, without a subprocess.

    Walk up to ``.git``; when it is a file, follow its ``gitdir:`` line and that directory's
    ``commondir`` file to the main ``.git`` and return its parent.
    """
    # FILL IN: checkout_root(cwd); `.git` directory -> that root. `.git` file -> parse "gitdir: <p>"
    # (relative to the worktree root when not absolute), read <p>/commondir (relative to <p>),
    # resolve, return its parent. Any OSError / malformed content -> None.


def load_index(root: Path) -> dict[str, Any] | None:
    """Return ``<root>/.parrot/procedure/procedures.json`` when it parses, has INDEX_SCHEMA_VERSION
    and is at most MAX_INDEX_BYTES; else None. Never raises."""
    # FILL IN: stat first (size cap), json.loads, isinstance dict, schema_version check.


def command_segments(command: str) -> list[list[str]]:
    """Split a shell command into token lists, one per simple command, respecting quotes."""
    # FILL IN: per Implementation Notes "Segments". Empty segments are dropped.


def _clean(tokens: list[str]) -> tuple[str, list[str]]:
    """(executable basename, argv) of one segment after dropping assignments and wrappers; ('', []) for `cd`."""
    # FILL IN: per Implementation Notes "leading_command".


def leading_command(command: str) -> tuple[str, list[str]]:
    """(executable basename, argv after it) of the first real command segment; ('', []) when unknown."""
    for tokens in command_segments(command):
        executable, argv = _clean(tokens)
        if executable:
            return executable, argv
    return "", []


def match_guards(index: Mapping[str, Any], command: str) -> list[dict[str, Any]]:
    """Index guard entries matching any segment of ``command``; each is a copy with an extra
    ``"argv"`` key (the arguments after the executable and the argv_prefix)."""
    # FILL IN: per Implementation Notes "match_guards". Preserve index order; never raise.
```
**Why this shape**: constants and names are fixed by spec §3 M5. `checkout_root` and
`command_segments` are small additions the later tasks reuse (state probes read the *current*
checkout while the plane is read from the *shared* root). `PLANE_DIR` / `INDEX_FILE` are restated
here on purpose: this module must not import the Pydantic model package of the plane (that would
load pydantic in the hook). A contract test (TASK-5639) ties the two copies together.

### `packages/ai-parrot/tests/sdd/test_procedure_advice.py` (CREATE)
```python
"""Tests for the hook-side procedure advice module (FEAT-891)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.sdd.scripts import procedure_advice as advice

GUARDS = [
    {"procedure": "sdd:task-close", "kind": "entry", "executable": "parrot", "argv_prefix": ["sdd", "task", "close"],
     "path_globs": [], "scope": {"task": {"argv": 0}, "feature": {"argv": 1}}},
    {"procedure": "sdd:task-close", "kind": "bypass", "executable": "git", "argv_prefix": ["mv"],
     "path_globs": ["sdd/tasks/active/*"], "scope": {}},
]


def test_advice_stdlib_only() -> None:
    """Importing the module in a fresh interpreter loads no pydantic, yaml or sqlite3."""
    code = (
        "import sys\n"
        "from parrot.sdd.scripts import procedure_advice\n"
        "print(sorted(m for m in ('pydantic', 'yaml', 'sqlite3') if m in sys.modules))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.stdout.strip() == "[]", proc.stdout + proc.stderr


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("cd x && rtk git mv a b", ("git", ["mv", "a", "b"])),
        ("FOO=1 BAR=2 /usr/bin/git push", ("git", ["push"])),
        ("uv run pytest -q", ("pytest", ["-q"])),
        ("timeout 30 gh pr create --base dev", ("gh", ["pr", "create", "--base", "dev"])),
        ("echo 'unbalanced", ("", [])),
    ],
)
def test_leading_command_wrappers(command: str, expected: tuple[str, list[str]]) -> None:
    """Assignments, `cd … &&` and the known wrappers are skipped."""
    assert advice.leading_command(command) == expected


def test_match_guards_every_segment() -> None:
    """A guarded command is found in any segment, and the match carries its argv."""
    # FILL IN: "mkdir -p x && git mv sdd/tasks/active/TASK-1-a.md sdd/tasks/completed/" matches the
    # bypass guard with argv == ["sdd/tasks/active/TASK-1-a.md", "sdd/tasks/completed/"];
    # "git mv README.md docs/" matches nothing; "parrot sdd task close TASK-1 demo verified" matches
    # the entry guard with argv == ["TASK-1", "demo", "verified"].


def test_shared_root_plain_and_worktree(tmp_path: Path) -> None:
    """A plain checkout is its own shared root; a linked worktree resolves to the primary checkout."""
    # FILL IN: build the layout described in the Codebase Contract (main/.git dir; worktree/.git file +
    # admin/commondir) and assert both results; a directory with no .git anywhere -> None is not
    # testable under a repo, so assert checkout_root(worktree / "src") == worktree instead.


def test_load_index_rejects_bad_files(tmp_path: Path) -> None:
    """Absent, unparsable, oversized and wrong-version files all return None."""
    # FILL IN
```

### FILL IN checklist
- [ ] `procedure_advice.py::checkout_root`, `shared_root`, `load_index` — bounded by the docstrings
- [ ] `procedure_advice.py::command_segments`, `_clean`, `match_guards` — bounded by the Implementation Notes
- [ ] `test_procedure_advice.py` — three test bodies

---

## Acceptance Criteria

- [ ] Importing the module loads no `pydantic`, `yaml` or `sqlite3` (subprocess test).
- [ ] The module has no `main()` and no module-level `parrot` import.
- [ ] `leading_command` returns the expected pair for every parametrized case.
- [ ] `match_guards` finds a guarded command in any segment of a compound command.
- [ ] No public function raises on malformed input.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_procedure_advice.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
3. Implement only the files listed above; complete every `FILL IN`; never change a name the blueprint fixes.
4. Run `ruff check --fix` on the touched files and the Validation Commands.
5. Commit the code, then close with `parrot sdd task close TASK-5637 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note


- Task: TASK-5637
- Feature: procedural-graph-plane
- Implementation SHA: 3e1b132dbf8f38d6dac3c6fbd618f0a18a1df1db
- Closed at (UTC): 2026-11-13T21:58:02+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-luna · Backend: codex · Model: gpt-5.6-luna · Attempts: 1 · Duration: 441.5s · Tokens: n/a |
