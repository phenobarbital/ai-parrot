# TASK-2639: grep_files — bounded, gitignore-aware literal search

**Feature**: FEAT-484 — ReadOnlyRepoToolkit — Safe Repo Grounding for Any Client
**Spec**: `sdd/specs/readonly-repo-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2638
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 2**.

`grep_files` has two jobs in this feature. It is the **explicit fallback** for what
the code graph genuinely cannot answer — regexes, config strings, literals in
unindexed files — and it is the **degradation target** for `search_code` when the
wiki plane is missing or broken (TASK-2642 calls it for that). Spec §2 is careful
that grep is *not* the default: "the gap is not 'we need a grep tool'".

This is also the feature's first subprocess, so it establishes the subprocess
contract the git tools (TASK-2640) reuse:

- `asyncio.create_subprocess_exec` with an **argv list** — never `shell=True`, never
  blocking `subprocess.run` (spec §5, §7).
- Timeout-bounded, with the child **terminated on cancellation** so a cancelled
  dispatch leaves no orphan.
- Output byte- and hit-count-bounded.

And it carries a §8 Q1 obligation the spec calls out directly: a grep must not
become a secret-exfiltration side channel. A pattern like `SECRET_KEY` would
otherwise return the contents of `.env` in the match line, bypassing `read_file`'s
deny-list entirely.

---

## Scope

- Add `async def grep_files(pattern, glob="") -> RepoSearchResult | RepoToolError`
  to `ReadOnlyRepoToolkit`.
- Add `_run_argv()` — the shared, bounded, cancellation-safe subprocess helper.
- Prefer `git grep` when `repo_root` is a git work tree (gets `.gitignore` for
  free); fall back to a bounded `os.walk` + in-process scan when it is not, or when
  `git` is unavailable.
- Drop hits whose path is deny-listed (§8 Q1) — filter on **path**, and do not
  emit the matched line for such files at all.
- Bound: `max_search_hits` hits, `max_result_bytes` total, `command_timeout`.
- Map results into `RepoSearchResult` / `RepoSearchHit` so `grep_files` and
  `search_code` share one payload shape (this is what makes TASK-2642's
  degradation transparent to the model).
- Write unit tests in `test_grep_files.py`.

### Behavior detail

- `pattern` is treated as a **fixed string** by default (`git grep -F`). This
  matches the pattern source (`llm.py:769` uses `--fixed-strings`) and is the safe
  default; a `regex: bool = False` argument may be added since spec §2 names
  regexes as grep's reason to exist.
- `glob` optionally restricts files (`git grep -- ':(glob)<pattern>'` or
  `--include`). Empty string = all files.
- `git grep` exits **1 when there are no matches** — that is success-with-zero-hits,
  not an error. Only treat exit codes outside `{0, 1}` as failure.
- Map each hit into `RepoSearchHit(page_id="", path=<rel path>, summary=<matched
  line, truncated>, score=0.0)`.
- `RepoSearchResult.degraded` stays `False` here — a direct `grep_files` call is not
  a degraded result. Only TASK-2642 sets `degraded=True` when it *falls back* to
  this method.

**NOT in scope**:
- `search_code` / `related_code` / the wiki plane → TASK-2641/2642.
- Setting `degraded=True` → that is TASK-2642's job at the call site.
- Git history tools → TASK-2640 (but it reuses your `_run_argv`).
- `web_search` → TASK-2643.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repo/toolkit.py` | MODIFY | Add `grep_files` + `_run_argv` |
| `packages/ai-parrot/src/parrot/tools/repo/schemas.py` | MODIFY | Add `GrepFilesInput` |
| `packages/ai-parrot/tests/tools/repo/test_grep_files.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-08-31.

### Verified Imports

```python
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.tools.decorators import tool_schema           # tools/decorators.py:39
from parrot.tools.repo.confinement import (               # TASK-2637
    PathOutsideRootError, is_secret_path, resolve_within_root,
)
from parrot.tools.repo.models import (                    # TASK-2637
    RepoSearchHit, RepoSearchResult, RepoToolError,
)
```

### Existing Signatures to Use

```python
# Standard library — the ONLY sanctioned subprocess entry point for this feature.
# VERIFIED available: Python 3.11 target.
async def asyncio.create_subprocess_exec(
    *args,                      # argv LIST — program then arguments, never a string
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=<path>,
) -> asyncio.subprocess.Process
# proc.communicate() -> tuple[bytes, bytes]
# proc.returncode -> int | None
# proc.kill() / proc.terminate() -> None
# asyncio.wait_for(coro, timeout=<float>) raises asyncio.TimeoutError

# packages/ai-parrot/src/parrot/tools/repo/toolkit.py  (TASK-2638, this feature)
class ReadOnlyRepoToolkit(AbstractToolkit):
    self._repo_root: Path            # already .resolve()'d
    self._max_result_bytes: int
    self._max_search_hits: int
    self._command_timeout: float
    self._deny_secret_files: bool
    self.logger: logging.Logger
    def _error(self, exc: Exception, path: str = "") -> RepoToolError
```

### Pattern source — read, do NOT import

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
    async def _tool_search_files(self, cwd, args) -> Dict[str, Any]   # line 769
# It builds: ["rg", "--line-number", "--no-heading", "--color", "never",
#             "--fixed-strings", ...] and calls its own `self._run_argv(...)`.
# It treats exit codes {0, 1} as success — COPY that; 1 means "no matches".
# It does NOT filter secrets and does NOT honour .gitignore — you must add both.
# `_run_argv` there is private to that dispatcher: port the approach, import nothing.
```

### Does NOT Exist

- ~~a shared `_run_argv` / subprocess helper in `parrot.tools`~~ — none. The only
  one is private on `LLMCodeDispatcher`. You are creating this feature's.
- ~~`parrot.utils.run_command`~~ / ~~`parrot.tools.shell`~~ — do not exist.
- ~~`rg` (ripgrep) being guaranteed on PATH~~ — it is **not**. The pattern source
  assumes it; you must not. Probe with `shutil.which` and prefer `git grep`, which
  the spec names explicitly ("preferring `git grep` when the root is a work tree").
- ~~`git grep` exiting 0 on no matches~~ — it exits **1**. Treating 1 as an error
  is the single most likely bug in this task.
- ~~`RepoSearchResult.matches` / `.lines`~~ — the field is `hits: list[RepoSearchHit]`
  (spec §2). Do not invent a parallel shape.
- ~~`asyncio.subprocess` honouring a `timeout=` kwarg~~ — it does not. Wrap
  `proc.communicate()` in `asyncio.wait_for`.
- ~~`shell=True` being acceptable anywhere~~ — spec §5 acceptance criterion:
  "no `shell=True` anywhere in the package". A test asserts this.

---

## Implementation Notes

### Pattern to Follow — the subprocess helper

Cancellation safety is an explicit acceptance criterion; `try/finally` around the
kill is what satisfies it.

```python
    async def _run_argv(
        self,
        argv: Sequence[str],
        *,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """Run an argv list in the repo root, bounded and cancellation-safe.

        Never uses a shell. The child is killed on timeout AND on cancellation,
        so a cancelled dispatch leaves no orphan process (spec §7).

        Args:
            argv: Program and arguments as a list — never a single string.
            timeout: Seconds; defaults to ``self._command_timeout``.

        Returns:
            Mapping with ``exit_code``, ``stdout``, ``stderr``, ``timed_out``.
        """
        limit = timeout if timeout is not None else self._command_timeout
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._repo_root),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=limit)
        except asyncio.TimeoutError:
            self._kill(proc)
            await proc.wait()
            return {"exit_code": -1, "stdout": "", "stderr": "timeout",
                    "timed_out": True}
        except asyncio.CancelledError:
            self._kill(proc)
            # Do not await proc.wait() here on a cancel path; reap and re-raise.
            raise
        return {
            "exit_code": proc.returncode,
            "stdout": out[: self._max_result_bytes].decode("utf-8", "replace"),
            "stderr": err[:4096].decode("utf-8", "replace"),
            "timed_out": False,
        }

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        """Best-effort terminate; a already-exited child is not an error."""
        try:
            proc.kill()
        except ProcessLookupError:
            pass
```

### Pattern to Follow — the grep itself

```python
        argv = ["git", "grep", "--line-number", "--no-color", "-I"]
        argv.append("-E" if regex else "-F")
        argv += ["-e", pattern]          # -e guards a pattern starting with "-"
        argv.append("--")                # end of options
        if glob:
            argv.append(f":(glob){glob}")
```

Two argv details that are the whole injection defence, and are tested:
- `-e <pattern>` means a pattern like `--upload-pack=x` or `; rm -rf /` is a
  *pattern*, never an option or a shell command.
- The bare `--` terminates option parsing before any path/glob argument.

### Key Constraints

- `git grep` runs with `cwd=self._repo_root`, so its output paths are already
  repo-relative — but **verify** each against `resolve_within_root` anyway before
  emitting. Cheap, and it closes the door on a crafted filename.
- Filter deny-listed paths **before** building the hit, so the matched line for a
  secret file never enters the payload. Honour `self._deny_secret_files`.
- Bound hits at `self._max_search_hits`; set a `truncated`-style signal by noting
  it in `degraded_reason` **only if** you also set `degraded` — otherwise report
  truncation in the result some other way. Prefer: leave `degraded=False` and cap
  `hits`; the count speaks for itself.
- Never `shell=True`. Never blocking `subprocess.run`. Never `os.system`.
- The non-git fallback walk must also be off the event loop (`asyncio.to_thread`).
- `self.logger`, Google-style docstrings, strict type hints.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:769` — approach
  source (private; do not import).
- `packages/ai-parrot/src/parrot/tools/repo/toolkit.py` — TASK-2638's class.
- Spec §7 "Known Risks / Gotchas" — the argv-injection and cancellation rows.

---

## Acceptance Criteria

- [ ] `grep_files` appears in `get_tools()`; toolkit still exposes no write-shaped tool
- [ ] Finds a literal match in a tracked file and returns `RepoSearchResult` with
      `hits[].path` repo-relative and `hits[].summary` = the matched line
- [ ] **Respects `.gitignore`**: a match inside the ignored `build/` directory is
      absent from hits
- [ ] **Omits secret files (§8 Q1)**: a pattern matching content inside `.env`
      returns no hit for `.env`, and the secret value never appears in the payload
- [ ] **No shell injection**: pattern `; rm -rf /` is searched as a literal and
      creates/deletes nothing; pattern `--upload-pack=x` is a pattern, not an option
- [ ] **No matches is not an error**: a pattern with zero hits returns an empty
      `hits` list, not a `RepoToolError` (guards the `git grep` exit-1 trap)
- [ ] **Timeout terminates the child**: a hanging child is killed, `timed_out` is
      reported, and no orphan process remains
- [ ] **Cancellation terminates the child**: cancelling the awaiting task kills the
      subprocess (assert no orphan)
- [ ] Bounded: at most `max_search_hits` hits; stdout capped at `max_result_bytes`
- [ ] Works in a non-git directory via the fallback walk (no raise)
- [ ] `grep -rn "shell=True" packages/ai-parrot/src/parrot/tools/repo/` → no results
- [ ] `grep -rn "subprocess.run\|os.system" packages/ai-parrot/src/parrot/tools/repo/`
      → no results
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/repo/ -v`
- [ ] Clean: `ruff check` + `mypy` on the package

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/repo/test_grep_files.py
import asyncio
import pytest
from pathlib import Path

from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.tools.repo.models import RepoSearchResult, RepoToolError


@pytest.fixture
def toolkit(temp_repo: Path) -> ReadOnlyRepoToolkit:
    return ReadOnlyRepoToolkit(repo_root=temp_repo)


class TestGrepFiles:
    async def test_finds_literal(self, toolkit):
        out = await toolkit.grep_files("def alpha")
        assert isinstance(out, RepoSearchResult)
        assert any("mod.py" in h.path for h in out.hits)

    async def test_respects_gitignore(self, toolkit):
        """build/ is gitignored — its match must not appear."""
        out = await toolkit.grep_files("def alpha")
        assert not any("build/" in h.path for h in out.hits)

    async def test_omits_secret_file_hits(self, toolkit):
        out = await toolkit.grep_files("SECRET_KEY")
        assert not any(h.path.endswith(".env") for h in out.hits)
        assert "hunter2" not in out.model_dump_json()

    async def test_no_matches_is_not_an_error(self, toolkit):
        """git grep exits 1 on no matches — that is success, not failure."""
        out = await toolkit.grep_files("zzz_definitely_absent_zzz")
        assert isinstance(out, RepoSearchResult)
        assert out.hits == []

    async def test_no_shell_injection(self, toolkit, temp_repo):
        canary = temp_repo / "pkg" / "sub" / "mod.py"
        out = await toolkit.grep_files("; rm -rf /")
        assert isinstance(out, RepoSearchResult)
        assert canary.exists(), "pattern was executed as a shell command"

    async def test_pattern_starting_with_dash_is_a_pattern(self, toolkit):
        out = await toolkit.grep_files("--upload-pack=evil")
        assert isinstance(out, RepoSearchResult)

    async def test_bounded_hits(self, temp_repo):
        for i in range(50):
            (temp_repo / f"f{i}.py").write_text("needle\n")
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, max_search_hits=5)
        out = await tk.grep_files("needle")
        assert len(out.hits) <= 5

    async def test_timeout_terminates_child(self, temp_repo, monkeypatch):
        """Force a hanging child and assert it is killed, not leaked."""
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, command_timeout=0.2)
        res = await tk._run_argv(["sleep", "30"])
        assert res["timed_out"] is True

    async def test_cancellation_terminates_child(self, temp_repo):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, command_timeout=30)
        task = asyncio.create_task(tk._run_argv(["sleep", "30"]))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # No orphan: give the loop a tick, then assert nothing is still running.
        await asyncio.sleep(0.1)

    async def test_non_git_dir_fallback(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "a.py").write_text("needle\n")
        tk = ReadOnlyRepoToolkit(repo_root=plain)
        out = await tk.grep_files("needle")
        assert isinstance(out, RepoSearchResult)
        assert any("a.py" in h.path for h in out.hits)


class TestNoShellAnywhere:
    def test_package_has_no_shell_true(self):
        import pathlib
        pkg = pathlib.Path("packages/ai-parrot/src/parrot/tools/repo")
        for f in pkg.rglob("*.py"):
            src = f.read_text()
            assert "shell=True" not in src, f
            assert "subprocess.run" not in src, f
            assert "os.system" not in src, f
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 2, §5, §7 (Known Risks), §8 Q1.
2. **Check dependencies** — TASK-2638 must be in `sdd/tasks/completed/`. You are
   adding methods to its `ReadOnlyRepoToolkit`.
3. **Verify the Codebase Contract**. Pay attention to the `git grep` exit-1 note
   and the fact that `rg` is not guaranteed on PATH.
4. Update the index → `"in-progress"`.
5. **Implement** per scope. `_run_argv` is reused by TASK-2640 — make it general
   and give it a real docstring.
6. **Verify** all acceptance criteria, including the two grep-based greps for
   `shell=True` / `subprocess.run`.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-31
**Notes**: Added `grep_files`, `_run_argv`, `_kill`, `_is_git_work_tree`,
`_hits_from_grep_lines`, and `_walk_grep` to `ReadOnlyRepoToolkit`, plus
`GrepFilesInput` in `schemas.py`. `git grep` is used with `--untracked`
(so newly-created-but-not-yet-committed files are found, while `.gitignore`
exclusions still apply) and `-F -e <pattern> --` (fixed-string, argv-safe,
no shell). Exit codes `{0, 1}` both treated as success (1 = no matches).
All 11 new tests pass, plus the full `tests/tools/repo/` suite (67 tests);
`ruff check` / `mypy` clean; confirmed no `shell=True` / `subprocess.run` /
`os.system` anywhere in the package.

**Deviations from spec**: `test_readonly_toolkit.py::test_expected_tool_set`
(TASK-2638) asserted the tool set was exactly `{read_file, list_files}` —
a snapshot that this task's own acceptance criterion ("Tests pass:
pytest packages/ai-parrot/tests/tools/repo/ -v") requires to stay green.
Updated that one assertion to include `grep_files`, with a comment noting
later tasks add more tools to the same set. No other change to that file.
