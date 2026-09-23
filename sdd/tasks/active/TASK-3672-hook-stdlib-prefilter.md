# TASK-3672: Stdlib prefilter and lazy imports for the wiki hook runtime

**Feature**: FEAT-595 — Lightweight wikitoolkit hook entry point
**Spec**: `sdd/specs/fixgroup-c3a787516a75.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:f0a40d0853f2

---

## Context

Ledger issue `issue:f0a40d0853f2` (FEAT-584 AC23b miss): the `PreToolUse` hook's warm start is
~415–425 ms against a 300 ms target. Spec §1 shows the hook module alone costs ~218 ms to import
because (a) `claude_code/__init__.py` eagerly imports `installer`, (b) `hook.py` imports
`repo_scan` (→ `languages`, `store`, `symbols`) just for two suffix constants, and (c) `hook.py`
imports `project` (pydantic + `decisions.models`, ~157 ms) at module level although most payloads
are rejected by pure-stdlib checks. This task implements spec Modules 1–3 and the prefilter tests
(Module 6, first file). TASK-3673 then adds the dedicated console entry on top.

## Scope

- Create `parrot/knowledge/wiki/file_suffixes.py` holding `CODE_SUFFIXES` / `DOC_SUFFIXES`
  (moved verbatim, with their `#:` doc comments) and make `repo_scan.py` import them from there.
- In `claude_code/hook.py`: import suffixes from `file_suffixes`; move the `project` import into
  `build_nudge` (keep `WikiProjectConfig` under `TYPE_CHECKING` for the annotation); add a stdlib
  `_prefilter_rejects(payload)` evaluated first in `build_nudge`.
- Make `claude_code/__init__.py` lazy with PEP 562 `__getattr__` over its three public names.
- Write `test_hook_prefilter.py` (decision equivalence, suffix identity, lazy package, import trace).

**NOT in scope**: `entry.py`, `pyproject.toml`, `test_hook_startup.py` (TASK-3673); changing nudge
text, throttle, matcher or config schema; touching `project.py` or `decisions/`.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/file_suffixes.py` | CREATE | Stdlib-only suffix constants |
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` | MODIFY | Import the constants from `file_suffixes` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py` | MODIFY | Prefilter + lazy `project` import |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/__init__.py` | MODIFY | PEP 562 lazy exports |
| `packages/ai-parrot/tests/knowledge/wiki/test_hook_prefilter.py` | CREATE | Equivalence + import tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.claude_code.assets import NUDGE_TEXT        # verified: claude_code/hook.py:30
from parrot.knowledge.wiki.project import (                            # verified: claude_code/hook.py:31-35
    WikiProjectConfig,
    find_project_root,
    load_effective_config,
)
from parrot.knowledge.wiki.repo_scan import CODE_SUFFIXES, DOC_SUFFIXES  # verified: claude_code/hook.py:37 (to be replaced)
from parrot.knowledge.wiki.claude_code.installer import (              # verified: claude_code/__init__.py
    install_claude_integration,
    integration_status,
    uninstall_claude_integration,
)
from parrot.knowledge.wiki.claude_code.hook import build_nudge, run_pre_tool_use_hook  # verified: hook.py:177, :222
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py
def _should_nudge_read(tool_input: dict[str, Any]) -> bool: ...          # ~L46, payload-only
def _should_nudge_bash(tool_input: dict[str, Any]) -> bool: ...          # ~L95, payload-only
def _throttled(storage: Path, cooldown_seconds: int, now: float) -> bool: ...  # ~L121
def build_nudge(
    payload: dict[str, Any],
    root: Optional[Path] = None,
    config: Optional[WikiProjectConfig] = None,
    now: Optional[float] = None,
) -> Optional[dict[str, Any]]: ...                                       # L177
def run_pre_tool_use_hook(stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None) -> int: ...  # L222

# Current build_nudge order (all AND-ed): event in (None, "PreToolUse") → root found →
# tool_name in config.claude.nudge_tools → config.is_built(root) → Read/_should_nudge_read →
# Bash/_should_nudge_bash → not _throttled(...)

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class ClaudeIntegrationConfig(BaseModel):   # L136: nudge_cooldown_seconds=60, nudge_tools=["Grep","Glob","Read","Bash"]
def find_project_root(start: Path | None = None) -> Path | None: ...   # L722
# project.py imports pydantic and parrot.knowledge.wiki.decisions.models at module level (L25, L27)

# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py
CODE_SUFFIXES: frozenset[str] = frozenset({...})   # L58-88 (with #: comments from L54)
DOC_SUFFIXES: frozenset[str] = frozenset({".md", ".rst", ".txt", ".html", ".htm"})  # L91
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.file_suffixes`~~ — created by this task.
- ~~`hook._prefilter_rejects`~~ — created by this task.
- ~~`parrot.knowledge.wiki.entry`~~ — TASK-3673, do not create here.
- There is no existing test module for `build_nudge` in `packages/ai-parrot/tests/knowledge/wiki/`
  (only `test_hook_startup.py`, which is subprocess-based and owned by TASK-3673).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/file_suffixes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_hook_prefilter.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py#build_nudge",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py#run_pre_tool_use_hook",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py#_should_nudge_read",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py#_should_nudge_bash",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_project_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#ClaudeIntegrationConfig"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)

1. Create `file_suffixes.py` and cut the two constants out of `repo_scan.py` — because `repo_scan`
   drags `languages`/`store`/`symbols` into the hook for data that is pure stdlib.
2. Re-import them in `repo_scan.py` under the same names — because other code reads
   `repo_scan.CODE_SUFFIXES`; identity must hold (AC6).
3. Rewire `hook.py` imports and add the prefilter — because non-search payloads must exit before
   pydantic/`project` load (AC2), while decisions stay identical (AC5).
4. Make `claude_code/__init__.py` lazy — because importing `claude_code.hook` executes the package
   `__init__` first, which currently imports the installer.
5. Write the tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/file_suffixes.py` (CREATE)
```python
"""File-suffix sets shared by the repo scanner and the Claude Code hook.

Stdlib-only on purpose: the ``PreToolUse`` hook imports these on every
tool call, so this module must never import pydantic, the scanners or the
store (FEAT-595).
"""

from __future__ import annotations

# FILL IN: paste the `#:` comment block + CODE_SUFFIXES frozenset from repo_scan.py L54-88
#          and DOC_SUFFIXES from L90-91 VERBATIM — bounded by AC6 (same contents).

__all__ = ["CODE_SUFFIXES", "DOC_SUFFIXES"]
```
**Why:** a single source of truth keeps the scanner and the hook in lock-step.

### `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` (MODIFY)
```python
# REPLACE — the block from `#: File suffixes treated as source code (category ``module``).`
#           through `DOC_SUFFIXES: frozenset[str] = frozenset({".md", ".rst", ".txt", ".html", ".htm"})`
# occurrences: 1 (verified: grep -c 'DOC_SUFFIXES: frozenset\[str\] = frozenset' repo_scan.py)
# WITH (placed with the other parrot imports near L37-41, keep the "Defaults" banner if other defaults follow):
from parrot.knowledge.wiki.file_suffixes import CODE_SUFFIXES, DOC_SUFFIXES
```
**Why:** re-export by import keeps `repo_scan.CODE_SUFFIXES is file_suffixes.CODE_SUFFIXES`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py` (MODIFY)
```python
# REPLACE (verified: hook.py:28-37; `from parrot.knowledge.wiki.project import (` occurrences: 1)
from typing import TYPE_CHECKING, Any, Optional, TextIO

from parrot.knowledge.wiki.claude_code.assets import NUDGE_TEXT
from parrot.knowledge.wiki.file_suffixes import CODE_SUFFIXES, DOC_SUFFIXES

if TYPE_CHECKING:
    from parrot.knowledge.wiki.project import WikiProjectConfig
```
Check `claude_code/assets.py` imports while here: if it imports anything beyond stdlib, report it
in the Completion Note (AC2's trace test will show it) — do not refactor `assets.py`.

```python
# INSERT above `def build_nudge(` (occurrences: 1)
def _prefilter_rejects(payload: dict[str, Any]) -> bool:
    """Payload-only rejection evaluated before any config is loaded.

    Mirrors the payload-dependent clauses of :func:`build_nudge`
    (event name, Read suffix, Bash search-ness). Because every clause of
    ``build_nudge`` is AND-ed, rejecting here first yields the same
    decision while skipping the pydantic/``project`` import (FEAT-595).
    Tools other than ``Read``/``Bash`` are never rejected here — the
    config may list arbitrary ``nudge_tools``.

    Args:
        payload: Parsed PreToolUse hook payload.

    Returns:
        ``True`` when no config could make this payload nudge.
    """
    # FILL IN: event check `payload.get("hook_event_name") not in (None, "PreToolUse")`;
    #          normalize tool_input exactly like build_nudge (non-dict → {});
    #          Read → not _should_nudge_read; Bash → not _should_nudge_bash; else False — bounded by AC5.


# INSIDE build_nudge, first statements:
    if _prefilter_rejects(payload):
        return None
    from parrot.knowledge.wiki.project import find_project_root, load_effective_config
# FILL IN: remove the now-redundant event check and the Read/Bash checks further down ONLY if
#          they are exactly covered by the prefilter; keeping them is also acceptable — bounded by AC5.
```
**Why:** the lazy import is what turns the common path into stdlib-only; the annotation stays
valid thanks to `from __future__ import annotations` + `TYPE_CHECKING`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/__init__.py` (MODIFY)
```python
# REPLACE the eager `from parrot.knowledge.wiki.claude_code.installer import (...)` block
# (occurrences: 1) — keep the module docstring and __all__ as-is.
from typing import Any

def __getattr__(name: str) -> Any:
    """Resolve the installer API lazily (PEP 562) — keeps the hook import light."""
    if name in __all__:
        from parrot.knowledge.wiki.claude_code import installer

        return getattr(installer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```
**Why:** `from parrot.knowledge.wiki.claude_code import install_claude_integration` keeps working;
`import parrot.knowledge.wiki.claude_code.hook` no longer pays for the installer.

### `packages/ai-parrot/tests/knowledge/wiki/test_hook_prefilter.py` (CREATE)
```python
"""FEAT-595: prefilter decision-equivalence and lazy-import guarantees for the wiki hook."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.knowledge.wiki.claude_code import hook


def _build_project(root: Path) -> None:
    """Built sqlite fixture: `.git` + `.parrot/wiki/wiki.db` (same as test_hook_startup)."""
    # FILL IN: mirror test_hook_startup._build_project — bounded by is_built() being an existence check.


@pytest.mark.parametrize("payload, expect_nudge", [
    # FILL IN: ≥ 12 rows — Grep, Glob, Read .py, Read .png, Read no path, Bash `rg foo`,
    #          Bash `git status`, Bash `cat README.md`, Bash `cat /etc/hosts`, Bash `FOO=1 grep x`,
    #          unknown tool, PostToolUse event, tool_input not a dict — bounded by AC5.
])
def test_build_nudge_decisions(tmp_path: Path, payload: dict, expect_nudge: bool) -> None:
    """build_nudge decides as before, with cooldown 0 and a built fixture repo."""
    # FILL IN: build fixture; pass root + a config with nudge_cooldown_seconds=0 (so throttling never
    #          interferes); assert (result is not None) == expect_nudge.


def test_prefilter_never_rejects_configurable_tools() -> None:
    """Grep/Glob/unknown tools pass the prefilter; config decides them."""
    # FILL IN


def test_unbuilt_repo_never_nudges(tmp_path: Path) -> None:
    """A repo without a plane yields None for a search payload (config path still consulted)."""
    # FILL IN


def test_suffix_identity() -> None:
    """repo_scan re-exports the very same frozensets (AC6)."""
    from parrot.knowledge.wiki import file_suffixes, repo_scan

    assert repo_scan.CODE_SUFFIXES is file_suffixes.CODE_SUFFIXES
    assert repo_scan.DOC_SUFFIXES is file_suffixes.DOC_SUFFIXES


def test_lazy_package_exports() -> None:
    """Public installer names still resolve through the package; bad names raise AttributeError."""
    # FILL IN


def test_hook_import_is_light() -> None:
    """Importing claude_code.hook in a fresh process loads neither installer, repo_scan, project nor pydantic."""
    # FILL IN: subprocess `sys.executable -c "import parrot.knowledge.wiki.claude_code.hook, sys; print(...)"`
    #          with PYTHONPATH pointing at this checkout's packages/ai-parrot/src (see test_hook_startup
    #          _SRC_ROOTS/_subprocess_env) and assert the banned modules are absent from sys.modules.
```

### FILL IN checklist
- [ ] `file_suffixes.py` constants pasted verbatim
- [ ] `repo_scan.py` block replaced by the import; no other change
- [ ] `_prefilter_rejects` body; `build_nudge` lazy import; redundant checks decision
- [ ] `__getattr__` in `claude_code/__init__.py`
- [ ] every test body (≥ 12 parametrized rows)

---

## Acceptance Criteria

- [ ] Spec AC5 (decision equivalence) covered by `test_build_nudge_decisions`.
- [ ] Spec AC6 (suffix identity, lazy package exports) covered.
- [ ] `import parrot.knowledge.wiki.claude_code.hook` in a fresh process loads none of
      `parrot.knowledge.wiki.claude_code.installer`, `parrot.knowledge.wiki.repo_scan`,
      `parrot.knowledge.wiki.project`, `pydantic`.
- [ ] `test_hook_startup.py`, `test_installer_mcp.py` still pass unchanged.
- [ ] `ruff check` clean on the touched files.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_hook_prefilter.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -q`

## Completion Note
(Agent fills this in when done)
