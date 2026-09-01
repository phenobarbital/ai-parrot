# TASK-2638: ReadOnlyRepoToolkit class with read_file and list_files

**Feature**: FEAT-484 — ReadOnlyRepoToolkit — Safe Repo Grounding for Any Client
**Spec**: `sdd/specs/readonly-repo-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2637
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1** (toolkit half) — the static grounding axis.

TASK-2637 built the confinement boundary as plain helpers. This task builds the
`AbstractToolkit` subclass that exposes it to a model, plus the first two tools:
`read_file` and `list_files`. It establishes three contracts every later task
depends on:

1. **The error contract** — a rejected path returns a `RepoToolError` *as the tool
   result*, never an exception. Spec §2: rejection must be "a structured tool error
   the model can read and recover from — never an exception that aborts the loop,
   and never a silent empty result."
2. **The bounds contract** — every result respects `max_result_bytes` with an
   explicit truncation marker, so a model cannot blow its own context on one file.
3. **Read-only by construction** — the class defines no mutating method, so
   `_generate_tools()` cannot expose one. Spec §2 is emphatic that this is a
   property of construction, not configuration.

Tasks 2639–2643 add tools to this same class. Getting the base right here is what
keeps them from each re-inventing error handling.

---

## Scope

- Create `parrot/tools/repo/toolkit.py` with `ReadOnlyRepoToolkit(AbstractToolkit)`.
- Implement `__init__` with the full spec §2 constructor signature (accept and
  store **all** parameters now, even those consumed by later tasks — later tasks
  add behavior, not signature).
- Implement the `_error()` helper that converts a confinement exception into a
  `RepoToolError`, and the `_rel()` helper that renders a repo-relative path.
- Implement `async def read_file(path, start=1, end=0) -> RepoReadResult | RepoToolError`.
- Implement `async def list_files(path=".", depth=1) -> dict[str, Any]`.
- Define the Pydantic arg schemas for both tools and attach with `@tool_schema`.
- Write unit tests in `test_readonly_toolkit.py`.

### Behavior detail

`read_file`:
- Confine via `resolve_readable_path()` (TASK-2637) → `RepoToolError` on rejection
  (`error="path_outside_root"` / `"secret_file"`).
- Missing file → `RepoToolError(error="not_found")`. Directory → `error="not_a_file"`.
- `start`/`end` are **1-based inclusive** line bounds; `end=0` means "to EOF".
- Read the file **off the event loop** (`asyncio.to_thread`) — spec §7 forbids sync
  file reads in an async path.
- Truncate the returned content at `max_result_bytes`, set `truncated=True`, and
  append an explicit marker line so the model knows content was cut.
- `total_bytes` is the **full** file size on disk, not the truncated length.

`list_files`:
- Confine the directory argument the same way.
- `depth` bounds recursion (`depth=1` = immediate children only).
- Skip `.git`, `.venv`, `__pycache__`, `node_modules`, `build`, `dist`, `.mypy_cache`,
  `.ruff_cache`, `.pytest_cache`.
- **Omit deny-listed paths** (§8 Q1) from the listing.
- Bound the result count (`max_search_hits * 10`, cap 500) and report `truncated`.
- Walk off the event loop via `asyncio.to_thread`.

**NOT in scope**:
- `grep_files` → TASK-2639. `git_log`/`git_show`/`git_blame` → TASK-2640.
- `search_code`/`related_code`/`resolve_plane_root` → TASK-2641/2642.
- `web_search` → TASK-2643. Do not add it, not even disabled.
- Integration tests against a real client → TASK-2643.
- Any subprocess use whatsoever — this task is pure filesystem.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repo/toolkit.py` | CREATE | `ReadOnlyRepoToolkit` + `read_file` + `list_files` |
| `packages/ai-parrot/src/parrot/tools/repo/schemas.py` | CREATE | Pydantic arg schemas for the tools |
| `packages/ai-parrot/src/parrot/tools/repo/__init__.py` | MODIFY | Re-export `ReadOnlyRepoToolkit` |
| `packages/ai-parrot/tests/tools/repo/test_readonly_toolkit.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-08-31.

### Verified Imports

```python
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.tools.toolkit import AbstractToolkit          # tools/toolkit.py:216
from parrot.tools.decorators import tool_schema           # tools/decorators.py:39

# From TASK-2637 (this feature):
from parrot.tools.repo.confinement import (
    PathOutsideRootError,
    SecretFileError,
    is_secret_path,
    resolve_readable_path,
    resolve_within_root,
)
from parrot.tools.repo.models import RepoReadResult, RepoToolError
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                          # line 216
    input_class: Optional[Type[BaseModel]] = None
    return_direct: bool = False
    exclude_tools: tuple[str, ...] = ()      # public async names to HIDE from the LLM
    tool_prefix: str                          # namespace applied to every tool name
    def get_tools(...)                                               # line 484
    def _generate_tools(self) -> None                                # line 537
    async def get_tools_filtered(...)                                # line 574
    def get_tools_sync(...)                                          # line 594

# _generate_tools() behaviour, VERIFIED at toolkit.py:537-570 — this is the
# whole basis of "read-only by construction":
#   for name in dir(self):
#       if name.startswith('_'): continue            # underscore = never a tool
#       if name in ('get_tools', 'get_tools_filtered', 'get_tools_sync',
#                   'get_tool', 'list_tool_names', 'start', 'stop', 'cleanup',
#                   *self.exclude_tools): continue
#       if not inspect.iscoroutinefunction(attr): continue   # sync = never a tool
#       -> becomes an LLM-callable tool named self._resolve_tool_name(name)
# CONSEQUENCES you must respect:
#   * Every helper MUST be underscore-prefixed or sync, or it becomes a tool.
#   * Only `async def` public methods become tools.

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None)  # line 39
```

### Does NOT Exist

- ~~`ReadOnlyRepoToolkit`~~ — new in this task.
- ~~`parrot.tools.repo.schemas`~~ — new in this task.
- ~~`AbstractToolkit.__init__` accepting a `repo_root`~~ — it does not. Call
  `super().__init__()` and store your own attributes.
- ~~`AbstractToolkit.read_only` / `.confine_to` / `.root` config~~ — no such
  options exist. Confinement is entirely your code.
- ~~a `write_file` / `apply_patch` / `run_command` method to disable~~ — there is
  nothing to disable. **Do not add one.** Spec §1 Non-Goals: "Not behind a flag,
  not behind a permission mode — absent."
- ~~`AbstractToolkit` exposing sync methods as tools~~ — it does not
  (`inspect.iscoroutinefunction` gate at `toolkit.py:558`). A sync helper is safe,
  but prefer underscore-prefixing anyway for clarity.
- ~~`RepoReadResult.lines` / `.start` / `.end`~~ — the model has exactly
  `path`, `content`, `truncated`, `total_bytes` (spec §2). Do not add fields
  without updating the spec.

---

## Implementation Notes

### Pattern to Follow

The constructor takes the **full** spec §2 signature now, so no later task has to
change it:

```python
class ReadOnlyRepoToolkit(AbstractToolkit):
    """Cwd-confined, write-free repository access for any AbstractClient."""

    def __init__(
        self,
        *,
        repo_root: Path,
        wiki_store: Optional[object] = None,
        wiki_name: str = "parrot",
        enable_web_search: bool = False,
        default_search_mode: Literal["lexical", "vector", "combined"] = "lexical",
        deny_secret_files: bool = True,
        max_result_bytes: int = 64_000,
        max_search_hits: int = 12,
        search_budget_tokens: int = 4_000,
        command_timeout: float = 20.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._repo_root = Path(repo_root).resolve()
        self._wiki_store = wiki_store
        self._wiki_name = wiki_name
        self._enable_web_search = enable_web_search
        self._default_search_mode = default_search_mode
        self._deny_secret_files = deny_secret_files
        self._max_result_bytes = max_result_bytes
        self._max_search_hits = max_search_hits
        self._search_budget_tokens = search_budget_tokens
        self._command_timeout = command_timeout
        self.logger = logging.getLogger(__name__)
```

The error-conversion helper — this is the contract every later tool reuses:

```python
    def _error(self, exc: Exception, path: str = "") -> RepoToolError:
        """Convert a confinement exception into a model-readable error.

        NEVER re-raises: spec §2 requires a structured tool error the model
        can recover from, not an exception that aborts the dispatch loop.
        """
        if isinstance(exc, SecretFileError):
            code = "secret_file"
        elif isinstance(exc, PathOutsideRootError):
            code = "path_outside_root"
        elif isinstance(exc, FileNotFoundError):
            code = "not_found"
        elif isinstance(exc, IsADirectoryError):
            code = "not_a_file"
        else:
            code = "error"
        self.logger.warning("repo tool rejected %r: %s", path, exc)
        return RepoToolError(error=code, detail=str(exc), path=path)
```

Write tool docstrings **for the model** (spec §7: "Every tool docstring is the
LLM's tool description"). Say what the tool is for and when to prefer it:

```python
    @tool_schema(ReadFileInput)
    async def read_file(
        self, path: str, start: int = 1, end: int = 0,
    ) -> RepoReadResult | RepoToolError:
        """Read a text file from the repository, optionally a line range.

        Use this after `search_code` has told you which file to open. Paths are
        relative to the repository root; paths outside it are refused, as are
        secret files such as `.env` or private keys. Large files are truncated —
        pass `start`/`end` to page through one instead.

        Args:
            path: Repository-relative path, e.g. "pkg/sub/mod.py".
            start: 1-based first line to return. Defaults to the file start.
            end: 1-based last line, inclusive. 0 (the default) means end of file.

        Returns:
            RepoReadResult with the content, or RepoToolError if refused.
        """
```

Reading must not block the loop:

```python
        try:
            target = resolve_readable_path(self._repo_root, path) \
                if self._deny_secret_files \
                else resolve_within_root(self._repo_root, path)
        except (PathOutsideRootError, SecretFileError) as exc:
            return self._error(exc, path)

        def _read() -> tuple[str, int]:
            total = target.stat().st_size
            with open(target, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read(), total

        try:
            raw, total_bytes = await asyncio.to_thread(_read)
        except (FileNotFoundError, IsADirectoryError, OSError) as exc:
            return self._error(exc, path)
```

### Key Constraints

- **Async, non-blocking**: wrap every filesystem call in `asyncio.to_thread`.
  Spec §5 asserts "no sync file reads in any async path".
- **No subprocess** in this task at all.
- Every non-tool method underscore-prefixed (`_error`, `_rel`, `_read`) — see the
  `_generate_tools()` contract above.
- `truncated=True` must be accompanied by a visible marker in `content`, e.g.
  `\n... [truncated: 200000 bytes total, 64000 returned] ...\n`. A silently short
  file is worse than an error.
- Return type is a union (`RepoReadResult | RepoToolError`); both are Pydantic
  models so either serializes for the tool-result payload.
- `self.logger`, never `print`. Google-style docstrings, strict type hints.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/toolkit.py:216,537` — base class and the
  tool-generation rules.
- `packages/ai-parrot/src/parrot/tools/decorators.py:39` — `tool_schema`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:740,755` —
  pattern source for read/list shape (private; do not import). **Note**: it uses
  blocking `open()` and `os.walk` directly — you must NOT copy that part, since
  those are sync calls in an async dispatcher. Wrap them.
- `packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py` — an existing
  example of asserting over generated tool sets.

---

## Acceptance Criteria

- [ ] `from parrot.tools.repo import ReadOnlyRepoToolkit` works
- [ ] **No write tool exists**: `get_tools()` contains no name matching
      `write|edit|patch|apply|run|exec|delete|remove|create|mkdir|chmod` —
      asserted under **every** constructor configuration, including
      `enable_web_search=True` and `deny_secret_files=False`
- [ ] `get_tools()` at this stage contains exactly `read_file` and `list_files`
- [ ] `read_file` returns `RepoReadResult` for a valid file
- [ ] `read_file` returns `RepoToolError(error="path_outside_root")` for `../..` and
      for the symlink escape — **and does not raise**
- [ ] `read_file` returns `RepoToolError(error="secret_file")` for `.env` and
      `config/.env`; reads `.env.example` normally
- [ ] `read_file` honours `deny_secret_files=False` (reads `.env`) — the flag
      controls the deny-list only, never containment
- [ ] `read_file` returns `RepoToolError(error="not_found")` for a missing path
- [ ] `read_file` respects `start`/`end` line bounds, 1-based inclusive
- [ ] `read_file` truncates at `max_result_bytes` with `truncated=True`, a visible
      marker, and `total_bytes` = full on-disk size
- [ ] `list_files` does not escape the root and respects `depth`
- [ ] `list_files` omits deny-listed paths and skipped directories
- [ ] No blocking filesystem call in any async method (`asyncio.to_thread` used)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/repo/ -v`
- [ ] Clean: `ruff check` + `mypy` on `packages/ai-parrot/src/parrot/tools/repo/`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/repo/test_readonly_toolkit.py
import re
import pytest
from pathlib import Path

from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.tools.repo.models import RepoReadResult, RepoToolError

WRITE_SHAPED = re.compile(
    r"write|edit|patch|apply|run|exec|delete|remove|create|mkdir|chmod",
    re.I,
)


@pytest.fixture
def toolkit(temp_repo: Path) -> ReadOnlyRepoToolkit:
    return ReadOnlyRepoToolkit(repo_root=temp_repo)


class TestReadOnlyByConstruction:
    @pytest.mark.parametrize("kwargs", [
        {},
        {"enable_web_search": True},
        {"deny_secret_files": False},
        {"enable_web_search": True, "deny_secret_files": False},
    ])
    def test_no_write_tool_under_any_config(self, temp_repo: Path, kwargs):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, **kwargs)
        names = [t.name for t in tk.get_tools()]
        assert not [n for n in names if WRITE_SHAPED.search(n)], names

    def test_expected_tool_set(self, toolkit):
        assert {t.name for t in toolkit.get_tools()} == {"read_file", "list_files"}


class TestReadFile:
    async def test_reads_file(self, toolkit):
        out = await toolkit.read_file("pkg/sub/mod.py")
        assert isinstance(out, RepoReadResult)
        assert "def alpha" in out.content

    async def test_line_range_inclusive(self, toolkit):
        out = await toolkit.read_file("pkg/sub/mod.py", start=1, end=1)
        assert out.content.strip() == "def alpha():"

    @pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd",
                                     "escape/secret.txt"])
    async def test_rejects_outside_without_raising(self, toolkit, bad):
        out = await toolkit.read_file(bad)
        assert isinstance(out, RepoToolError)
        assert out.error == "path_outside_root"

    @pytest.mark.parametrize("secret", [".env", "config/.env", "server.pem"])
    async def test_rejects_secret(self, toolkit, secret):
        out = await toolkit.read_file(secret)
        assert isinstance(out, RepoToolError) and out.error == "secret_file"

    async def test_allows_example(self, toolkit):
        assert isinstance(await toolkit.read_file(".env.example"), RepoReadResult)

    async def test_deny_flag_off_reads_env(self, temp_repo):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, deny_secret_files=False)
        out = await tk.read_file(".env")
        assert isinstance(out, RepoReadResult) and "hunter2" in out.content

    async def test_deny_flag_off_still_confines(self, temp_repo):
        """The flag governs the deny-list ONLY — never containment."""
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, deny_secret_files=False)
        out = await tk.read_file("escape/secret.txt")
        assert isinstance(out, RepoToolError)

    async def test_not_found(self, toolkit):
        out = await toolkit.read_file("nope.py")
        assert isinstance(out, RepoToolError) and out.error == "not_found"

    async def test_truncates_at_byte_bound(self, temp_repo):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, max_result_bytes=1000)
        out = await tk.read_file("big.txt")
        assert out.truncated is True
        assert len(out.content.encode()) < 200_000
        assert out.total_bytes == 200_000
        assert "truncated" in out.content.lower()


class TestListFiles:
    async def test_lists_and_respects_depth(self, toolkit):
        shallow = await toolkit.list_files(".", depth=1)
        assert not any("sub/mod.py" in f for f in shallow["files"])
        deep = await toolkit.list_files(".", depth=5)
        assert any("mod.py" in f for f in deep["files"])

    async def test_omits_secrets(self, toolkit):
        out = await toolkit.list_files(".", depth=5)
        assert not any(f.endswith(".env") for f in out["files"])
        assert not any(f.endswith(".pem") for f in out["files"])
        assert any(f.endswith(".env.example") for f in out["files"])

    async def test_confined(self, toolkit):
        out = await toolkit.list_files("../..")
        assert isinstance(out, RepoToolError) or out.get("error")
```

> Note: this repo's pytest config must collect `async def` tests
> (`pytest-asyncio`). Follow whatever mode the existing
> `packages/ai-parrot/tests/tools/` suite uses — check
> `pyproject.toml`/`pytest.ini` for `asyncio_mode` before adding markers.

---

## Agent Instructions

1. **Read the spec** — §2 (Overview, Data Models, New Public Interfaces),
   §3 Module 1, §5, §7, §8 Q1.
2. **Check dependencies** — TASK-2637 must be in `sdd/tasks/completed/`.
   You depend on its `confinement.py` and `models.py`.
3. **Verify the Codebase Contract**, especially the `_generate_tools()` rules —
   a stray public `async def` helper becomes an LLM-callable tool.
4. Update the index → `"in-progress"`.
5. **Implement** per scope. Take the full constructor signature now.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-31
**Notes**: Implemented `ReadOnlyRepoToolkit(AbstractToolkit)` in
`toolkit.py` with the full spec §2 constructor signature, `_error()` /
`_rel()` / `_resolve_for_read()` helpers (all underscore-prefixed, sync —
never exposed as tools), and the `read_file` / `list_files` tools with
`@tool_schema`-attached Pydantic arg schemas in `schemas.py`. Re-exported
`ReadOnlyRepoToolkit` from `parrot.tools.repo.__init__`. All 56 unit tests
(35 confinement + 21 toolkit) pass; `ruff check` and `mypy` clean. Verified
`get_tools()` is exactly `{read_file, list_files}` and contains no
write-shaped name under any constructor configuration.

**Deviations from spec**: none

**Post-completion fix (2026-09-01, commit c47a252e3)**: the feature-level
adversarial code review (after TASK-2643) found that `list_files`'s
bespoke recursion (`entry.is_dir()`) followed symlinked directories out
of `repo_root` without a containment check — a CRITICAL confinement
bypass reachable in every deployment. Fixed by resolving each entry and
skipping it (never listing, never recursing) when its real target is
outside `repo_root`, reusing the same containment rule
`resolve_within_root` already enforces. Regression test added:
`test_rejects_symlinked_directory_escape`.

Same review pass (IMPORTANT): `ReadOnlyRepoToolkit.__init__` did not
update `self._init_kwargs` with its named constructor arguments, so
`build_envelope_from_tool` could not reconstruct this toolkit for
remote/off-process execution (a bare `ReadOnlyRepoToolkit()` would raise
`TypeError` for the missing `repo_root`). Fixed by updating
`_init_kwargs` with the serializable subset (mirroring
`VectorStoreSearchTool`'s convention); `wiki_store` is deliberately
excluded since a live store object cannot cross a process boundary.
