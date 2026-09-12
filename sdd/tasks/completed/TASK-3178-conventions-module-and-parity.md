# TASK-3178: `parrot/flows/conventions.py`, packaged rule copies and parity tests

**Feature**: FEAT-553 — sdd-coder Shared Conventions & Turn Budget
**Spec**: `sdd/specs/sdd-coder-shared-conventions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3177
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (code half) and the loader contract restated in §3 M2. The
loader must live in a **stdlib-only leaf module** because importing anything
under `parrot.flows.dev_loop` costs ~2.2 s (its `__init__` eagerly imports
every dispatcher) while `parrot.flows` costs ~8 ms; `coding_agents.py`
(TASK-3181) and the parity tests depend on that (spec §10 R6, AC-14). The
package-shipped copies keep dispatch working from a wheel outside the repo,
mirroring `_subagent_data/`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/conventions.py` with
  `CODER_RULE_NAMES`, `RULES_DIRNAME`, `CONVENTIONS_PREAMBLE`,
  `_strip_frontmatter`, `load_project_conventions`.
- Create `packages/ai-parrot/src/parrot/flows/_rules_data/{codebase-conventions,python-development}.md`
  as byte-identical copies of `.agent/rules/`.
- Add the package-data entry so the wheel ships them.
- Create `tests/flows/test_conventions.py` (loader behaviour + import-light) and
  `tests/flows/dev_loop/test_rules_parity.py` (three-way byte parity + size cap).

**NOT in scope**: the `_subagent_defs` re-export and the prompt builders
(TASK-3179); any installer (TASK-3180/3181); rule content (TASK-3177).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/conventions.py` | CREATE | stdlib-only loader |
| `packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md` | CREATE | copy of `.agent/rules/codebase-conventions.md` |
| `packages/ai-parrot/src/parrot/flows/_rules_data/python-development.md` | CREATE | copy of `.agent/rules/python-development.md` |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `"parrot.flows" = ["_rules_data/*.md"]` package-data entry |
| `packages/ai-parrot/tests/flows/test_conventions.py` | CREATE | loader tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py` | CREATE | parity + size tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from importlib.resources import files          # stdlib; same call shape as _subagent_defs.py:48/111
from pathlib import Path                       # stdlib
# nothing from parrot.* may be imported by conventions.py (AC-14)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/__init__.py — docstring only, no imports (verified 2026-09-12) → `files("parrot.flows")` is cheap
# packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py
def _strip_frontmatter(text: str) -> str:      # line 64 — copy its 8-line body verbatim into conventions.py (a leaf may not import _subagent_defs)
    # returns text unchanged when no leading '---' fence; drops the block between the first two '---' lines; lstrip("\n") the rest
data_dir = files("parrot.flows.dev_loop") / "_subagent_data"   # line 111 — the resource-lookup idiom to mirror with "parrot.flows" / "_rules_data"

# packages/ai-parrot/pyproject.toml  [tool.setuptools.package-data] (line 894)
"parrot.flows.dev_loop" = ["_subagent_data/*.md"]              # line 906 — insert the new entry directly ABOVE this line
"parrot.flows.dev_flow" = ["_subagent_data/*.md"]              # line 909

# packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py — pattern to mirror
_REPO_ROOT = Path(__file__).resolve().parents[5]               # line 20
def _repo_agents_dir() -> Path | None:                         # line 29 — walk parents for `.claude/agents`; return None if absent
    ...
pytest.skip("...")                                             # line 49 — skip (not fail) when the repo dir is absent (wheel install)

# .agent/rules/codebase-conventions.md, .agent/rules/python-development.md — created/edited by TASK-3177 (must be in tasks/completed/)
# tests/flows/__init__.py exists; there is NO tests/flows/conftest.py (verified) — the new test needs no fixture wiring
```

### Does NOT Exist
- ~~`parrot.flows.conventions`~~ — created here.
- ~~`parrot/flows/_rules_data/`~~ — created here; without the package-data entry it is NOT in the wheel.
- ~~`_subagent_defs.load_project_conventions`~~ — TASK-3179 adds the re-export; do not touch `_subagent_defs.py` here.
- ~~`_rules_data/cython-development.md` / `rust-development.md`~~ — deliberately not shipped (spec §8 Q5).
- ~~`RULES_DIR` / `load_rules` / `load_rule`~~ — the names are `RULES_DIRNAME` and `load_project_conventions`, no aliases.

---

## Implementation Notes

### Pattern to Follow
```python
# _subagent_defs.py:89-115 — same dual-sourcing idea, but here the WORKTREE copy wins when present
```

### Key Constraints
- `conventions.py` imports: `os`, `pathlib`, `importlib.resources`, `typing` only. Test asserts `parrot.flows.dev_loop` never lands in `sys.modules`.
- Never raise for a missing worktree file; raise `FileNotFoundError` only for a missing package copy; `ValueError` for a name outside `CODER_RULE_NAMES`.
- Output format is fixed by the spec: `## Project rule: <name>\n\n<body>` blocks joined by `\n\n---\n\n`.

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` — parity test shape.

---

## Implementation Blueprint

### Steps (in order)
1. Copy the two rule files: `cp .agent/rules/{codebase-conventions,python-development}.md packages/ai-parrot/src/parrot/flows/_rules_data/` — *why*: byte parity is tested; never hand-edit the copies.
2. Add the package-data line — *why*: `files("parrot.flows") / "_rules_data"` reads from the installed package; without the glob a wheel build drops the files.
3. Write `conventions.py` from the CREATE block — *why*: it is the one loader every consumer (dispatchers, installers, tests) uses.
4. Write both test modules, run `pytest packages/ai-parrot/tests/flows/test_conventions.py packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py -v` — *why*: AC-2/3/4/10/14.

### `packages/ai-parrot/src/parrot/flows/conventions.py` (CREATE)
```python
"""Project conventions injected into every external ``sdd-coder`` seat (FEAT-553).

Stdlib-only LEAF module: it must never import ``parrot.flows.dev_loop`` (that
package's ``__init__`` eagerly imports every dispatcher, ~2.2 s) so that
``parrot.knowledge.wiki.coding_agents`` and the parity tests stay cheap.
"""
from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Sequence

CODER_RULE_NAMES: tuple[str, ...] = ("codebase-conventions", "python-development")  # v1 Python only (spec §8 Q5)
RULES_DIRNAME: str = ".agent/rules"
CONVENTIONS_PREAMBLE: str = (
    "Project conventions — binding for every file you touch; a banned import fails "
    "this attempt at the merge gate:"
)
_SEPARATOR: str = "\n\n---\n\n"


def _strip_frontmatter(text: str) -> str:
    """Drop a leading ``---`` YAML frontmatter block; return ``text`` unchanged when there is none."""
    # FILL IN: copy the body of parrot/flows/dev_loop/_subagent_defs.py:64-86 verbatim — bounded by byte-identical behaviour

def _package_rule(name: str) -> str:
    """Read the package-shipped copy ``_rules_data/<name>.md``; FileNotFoundError means a packaging error."""
    return (files("parrot.flows") / "_rules_data" / f"{name}.md").read_text(encoding="utf-8")


def load_project_conventions(
    cwd: str | os.PathLike[str] | None = None,
    *,
    names: Sequence[str] = CODER_RULE_NAMES,
) -> str:
    """Return the coder rule set as ONE Markdown block for prompt injection.

    Lookup order per name: ``<cwd>/.agent/rules/<name>.md`` when ``cwd`` is given and the file
    exists (the worktree copy wins), else the package copy. Frontmatter is stripped; each rule
    becomes ``## Project rule: <name>\\n\\n<body>``; blocks are joined by ``\\n\\n---\\n\\n``.

    Raises:
        ValueError: ``name`` not in ``CODER_RULE_NAMES``.
        FileNotFoundError: a package copy is missing (packaging error).
    """
    blocks: list[str] = []
    for name in names:
        if name not in CODER_RULE_NAMES:
            raise ValueError(f"Unknown rule {name!r}; expected one of {CODER_RULE_NAMES}")
        text: str | None = None
        if cwd is not None:
            candidate = Path(cwd) / RULES_DIRNAME / f"{name}.md"
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8")
        if text is None:
            text = _package_rule(name)
        blocks.append(f"## Project rule: {name}\n\n{_strip_frontmatter(text).strip()}")
    return _SEPARATOR.join(blocks)


__all__ = ["CODER_RULE_NAMES", "RULES_DIRNAME", "CONVENTIONS_PREAMBLE", "load_project_conventions"]
```
**Why this shape**: signature, lookup order and output format are the spec §3 M2 skeleton — not negotiable, TASK-3179/3180/3181 build on them. `_strip_frontmatter` is duplicated (not imported) precisely to keep the module a leaf.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '"parrot.flows.dev_loop" = \["_subagent_data/\*.md"\]' packages/ai-parrot/pyproject.toml)
# BEFORE — insert directly above `"parrot.flows.dev_loop" = ["_subagent_data/*.md"]` (verified: packages/ai-parrot/pyproject.toml:906)
# FEAT-553: coder rule files read via importlib.resources by parrot.flows.conventions.
"parrot.flows" = ["_rules_data/*.md"]
```
**Why**: setuptools package-data is per-package; `parrot` (line 895) does not glob `*.md`.

### `packages/ai-parrot/tests/flows/test_conventions.py` (CREATE)
```python
"""Loader contract for parrot.flows.conventions (FEAT-553, spec AC-4/AC-14)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.flows.conventions import CODER_RULE_NAMES, load_project_conventions


@pytest.fixture
def rules_worktree(tmp_path: Path) -> Path:
    d = tmp_path / ".agent" / "rules"
    d.mkdir(parents=True)
    (d / "codebase-conventions.md").write_text("---\nname: x\n---\nSENTINEL-WORKTREE-RULE\n")
    return tmp_path


def test_conventions_prefer_worktree_copy(rules_worktree):
    out = load_project_conventions(rules_worktree, names=("codebase-conventions",))
    assert "SENTINEL-WORKTREE-RULE" in out and "name: x" not in out


def test_conventions_fall_back_to_package_copy(tmp_path):
    # FILL IN: assert load_project_conventions(None) == load_project_conventions(tmp_path) and both contain "## Project rule: python-development" — bounded by AC-4


def test_conventions_strip_frontmatter_and_join():
    # FILL IN: assert every name in CODER_RULE_NAMES yields a "## Project rule: <name>" heading, blocks are separated by "\n\n---\n\n", and "trigger: always_on" does not survive — bounded by spec §3 M2 output format


def test_conventions_reject_unknown_name():
    with pytest.raises(ValueError):
        load_project_conventions(names=("nope",))


def test_conventions_module_is_import_light():
    code = "import sys, parrot.flows.conventions; assert 'parrot.flows.dev_loop' not in sys.modules"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
```
**Why**: one test per spec §4 row for M1; the subprocess test is the only reliable way to observe import side effects (AC-14).

### `packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py` (CREATE)
```python
"""Three-way byte parity for the coder rule files (FEAT-553, spec AC-2/AC-3, mirrors test_subagent_parity.py)."""
from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest

from parrot.flows.conventions import CODER_RULE_NAMES


def _repo_rules_dir(sub: str) -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / sub / "rules"
        if candidate.is_dir():
            return candidate
    return None


@pytest.mark.parametrize("name", CODER_RULE_NAMES)
def test_claude_rules_twin_is_identical(name: str) -> None:
    # FILL IN: skip when _repo_rules_dir(".agent") is None; assert (.claude/rules/<name>.md).read_bytes() == (.agent/rules/<name>.md).read_bytes() — bounded by AC-2


@pytest.mark.parametrize("name", CODER_RULE_NAMES)
def test_package_rules_copy_is_identical(name: str) -> None:
    # FILL IN: same skip; compare resources.files("parrot.flows") / "_rules_data" / f"{name}.md" bytes with .agent/rules — bounded by AC-2/AC-10


def test_coder_rules_fit_the_prompt_budget() -> None:
    total = sum(len((resources.files("parrot.flows") / "_rules_data" / f"{n}.md").read_bytes()) for n in CODER_RULE_NAMES)
    assert total <= 8_000, total
```
**Why**: the package copy is what a wheel dispatches; drift between the three copies is the failure this guards.

### FILL IN checklist
- [ ] `conventions.py::_strip_frontmatter` — verbatim copy of `_subagent_defs.py:64-86`; bounded by identical behaviour
- [ ] `test_conventions.py::test_conventions_fall_back_to_package_copy` / `test_conventions_strip_frontmatter_and_join` — bodies; bounded by AC-4
- [ ] `test_rules_parity.py::test_claude_rules_twin_is_identical` / `test_package_rules_copy_is_identical` — bodies with the skip guard; bounded by AC-2

---

## Acceptance Criteria

- [ ] `python -c "import parrot.flows.conventions as c; print(c.CODER_RULE_NAMES)"` prints `('codebase-conventions', 'python-development')`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/test_conventions.py packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/conventions.py packages/ai-parrot/tests/flows/test_conventions.py packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py` clean
- [ ] `pyproject.toml` carries `"parrot.flows" = ["_rules_data/*.md"]` (spec AC-10)
- [ ] Import-light: `parrot.flows.dev_loop` absent from `sys.modules` after importing the module (spec AC-14)

---

## Test Specification

See the two CREATE test blocks above — they are the scaffold; complete the `FILL IN` bodies.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M1/M2, §6 contract, §10 R6)
2. **Check dependencies** — `TASK-3177` must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `_subagent_defs.py:64` and `pyproject.toml:906` anchors
4. **Update status** in `sdd/tasks/index/sdd-coder-shared-conventions.json` → `"in-progress"`
5. **Implement** — from the blueprint; never import `parrot.flows.dev_loop` in `conventions.py`
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3178-conventions-module-and-parity.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (orchestrated via parrot-sdd-coder MCP)
**Date**: 2026-09-12
**Notes**: Created the stdlib-only leaf module `parrot/flows/conventions.py`
(`CODER_RULE_NAMES`, `RULES_DIRNAME`, `CONVENTIONS_PREAMBLE`,
`_strip_frontmatter`, `load_project_conventions` — worktree copy wins,
falls back to the package copy, never raises for a missing worktree
file); byte-identical `_rules_data/{codebase-conventions,python-development}.md`;
`pyproject.toml` package-data entry `"parrot.flows" = ["_rules_data/*.md"]`;
`test_conventions.py` (5 tests) and `test_rules_parity.py` (5
parametrized/plain tests) — all 10 pass. Verified: `CODER_RULE_NAMES`
prints correctly, `ruff check` clean on all three files, import-light
(`parrot.flows.dev_loop` absent from `sys.modules`).

**Deviations from spec**: none

Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 · Duration: 168.4s · Tokens: 568029 in / 6955 out
