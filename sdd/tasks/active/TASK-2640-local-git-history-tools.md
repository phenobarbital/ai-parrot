# TASK-2640: Local git history tools — git_log, git_show, git_blame

**Feature**: FEAT-484 — ReadOnlyRepoToolkit — Safe Repo Grounding for Any Client
**Spec**: `sdd/specs/readonly-repo-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2639
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 3** — the historical grounding axis.

A research partner investigating a codebase needs to ask *why* code looks the way
it does, not just *what* it says. `git_log` / `git_show` / `git_blame` are that
axis. They also carry a specific weight in this feature's design: spec §2 accepts
that the wiki plane inside a worktree is at roughly **last-commit state**, and
notes that "`git_*` and `read_file` cover uncommitted edits". These tools are the
freshness escape hatch for a deliberately stale index.

Nothing in the codebase does this today. Spec §6 is explicit that
`parrot_tools/gittoolkit.py` is a **GitHub API** toolkit — `RepositoryCredential`,
`CreatePullRequestInput`, `SearchRepoCodeInput` — with no `log`/`show`/`blame` over
a local checkout. Do not try to reuse it.

The security surface here is **argv injection via a ref**, which spec §7 calls out
by name: a ref like `--upload-pack=/bin/sh` handed to a git command that does not
terminate its options is remote code execution. Ref validation and `--` separators
are this task's real work.

---

## Scope

- Create `parrot/tools/repo/git_tools.py` holding the ref-validation helpers and
  argv builders (module-level, so they are unit-testable without a toolkit).
- Add three tools to `ReadOnlyRepoToolkit`:
  - `async def git_log(path="", limit=20) -> dict[str, Any] | RepoToolError`
  - `async def git_show(ref) -> dict[str, Any] | RepoToolError`
  - `async def git_blame(path, start=1, end=0) -> dict[str, Any] | RepoToolError`
- Implement `validate_ref(ref: str) -> str` — reject anything option-shaped or
  otherwise unsafe; raise `InvalidRefError`.
- Reuse TASK-2639's `_run_argv` for every invocation. Do not write a second
  subprocess helper.
- Confine every `path` argument through TASK-2637's `resolve_within_root`.
- Degrade cleanly outside a git repo: structured `RepoToolError`, never a raise.
- Write unit tests in `test_git_tools.py`.

### Behavior detail

`git_log`:
- `git log --max-count=<limit> --date=iso --format=<parseable> [-- <path>]`
- Parse into a list of `{sha, author, date, subject}` dicts. Use a delimiter that
  cannot appear in a commit subject (e.g. `%x1f` unit separator, `%x1e` record
  separator) rather than trying to split on whitespace.
- `limit` clamped to a sane maximum (e.g. 200).

`git_show`:
- `git show --stat --format=<...> <validated-ref> --`
- Bound the diff output at `max_result_bytes` with an explicit truncation marker.
- **Do not** let a ref reach argv unvalidated.

`git_blame`:
- `git blame --line-porcelain -L <start>,<end> -- <confined path>`
  (or plain `--porcelain`; pick one and parse it consistently).
- `end=0` means to EOF — omit the `-L` bound entirely in that case, or use
  `-L <start>,`.
- Deny-listed paths are refused (`error="secret_file"`), since blame output
  contains the file's content lines.

**NOT in scope**:
- Any mutating git operation — no `commit`, `checkout`, `fetch`, `push`, `apply`.
  Spec §1: absent, not disabled.
- Network-touching git operations (`fetch`, `ls-remote`) — local checkout only.
- `git grep` — that is TASK-2639's `grep_files`.
- The wiki plane / `resolve_plane_root` → TASK-2641 (which also shells out to
  `git rev-parse`; it owns that call, not you).
- `web_search` → TASK-2643.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repo/git_tools.py` | CREATE | `validate_ref`, `InvalidRefError`, argv builders, output parsers |
| `packages/ai-parrot/src/parrot/tools/repo/toolkit.py` | MODIFY | Add `git_log`, `git_show`, `git_blame` |
| `packages/ai-parrot/src/parrot/tools/repo/schemas.py` | MODIFY | Add `GitLogInput`, `GitShowInput`, `GitBlameInput` |
| `packages/ai-parrot/tests/tools/repo/test_git_tools.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-08-31.

### Verified Imports

```python
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.tools.decorators import tool_schema           # tools/decorators.py:39
from parrot.tools.repo.confinement import (               # TASK-2637
    PathOutsideRootError, SecretFileError, resolve_readable_path,
    resolve_within_root,
)
from parrot.tools.repo.models import RepoToolError        # TASK-2637
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/repo/toolkit.py  (TASK-2638/2639, this feature)
class ReadOnlyRepoToolkit(AbstractToolkit):
    self._repo_root: Path
    self._max_result_bytes: int
    self._command_timeout: float
    self._deny_secret_files: bool
    self.logger: logging.Logger
    def _error(self, exc: Exception, path: str = "") -> RepoToolError
    async def _run_argv(                      # ← TASK-2639. REUSE THIS.
        self, argv: Sequence[str], *, timeout: Optional[float] = None,
    ) -> dict[str, Any]
    # returns {"exit_code": int, "stdout": str, "stderr": str, "timed_out": bool}
```

### Does NOT Exist

- ~~a local-git toolkit anywhere in the codebase~~ — VERIFIED.
  `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` is a **GitHub API**
  toolkit (`RepositoryCredential:48`, `CreatePullRequestInput:267`,
  `SearchRepoCodeInput:438`). It offers **no** `git log` / `show` / `blame` over a
  local checkout. Do not import it, do not subclass it, do not extend it.
- ~~`GitPython` / `pygit2` / `dulwich` being available~~ — none is a dependency,
  and spec §7 says "**No new required dependency**". Shell out to the `git` binary
  via `_run_argv`.
- ~~`parrot.tools.repo.git_tools`~~ — new in this task.
- ~~`validate_ref`~~ / ~~`InvalidRefError`~~ — new in this task.
- ~~a second subprocess helper being acceptable~~ — reuse `_run_argv` from
  TASK-2639. Spec §2's "a second implementation is a second chance to get it wrong"
  applies to subprocess handling as much as to path confinement.
- ~~`git` being guaranteed present~~ — spec §7 External Dependencies: "`git`
  system … degrades if absent". Handle a missing binary as a structured error.
- ~~`git log` exiting 0 in an empty repo~~ — it exits **128** with
  "does not have any commits yet". Handle it as a structured error, not a crash.

---

## Implementation Notes

### Pattern to Follow — ref validation is the security control

```python
class InvalidRefError(ValueError):
    """Raised when a caller-supplied git ref is not safe to pass to argv."""


# Deliberately conservative: shas, branch/tag names, HEAD~3, a..b, a...b, ^ref.
_REF_OK = re.compile(r"^[A-Za-z0-9._/~^@{}-]{1,255}$")


def validate_ref(ref: str) -> str:
    """Validate a git ref before it reaches an argv list.

    Rejects option-shaped refs — a ref such as ``--upload-pack=/bin/sh`` handed
    to a git command that does not terminate its options is remote code
    execution (spec §7).

    Args:
        ref: Caller-supplied ref: a sha, branch, tag, or range.

    Returns:
        The ref, unchanged, when it is safe.

    Raises:
        InvalidRefError: The ref is empty, option-shaped, or contains a
            character outside the conservative allow-list.
    """
    candidate = ref.strip()
    if not candidate:
        raise InvalidRefError("ref must not be empty")
    if candidate.startswith("-"):
        raise InvalidRefError(f"option-shaped ref rejected: {ref!r}")
    if not _REF_OK.match(candidate):
        raise InvalidRefError(f"ref contains unsupported characters: {ref!r}")
    if ".." in candidate and candidate.count(".") > 3:
        raise InvalidRefError(f"malformed ref range: {ref!r}")
    return candidate
```

Belt **and** braces — validate the ref *and* terminate options:

```python
        argv = ["git", "show", "--stat", f"--format={_SHOW_FORMAT}",
                validate_ref(ref), "--"]
```

The `--` matters even with validation: it is what makes a ref that happens to
look like a path unambiguous, and it costs nothing.

### Pattern to Follow — parseable log output

Do not split on whitespace; commit subjects contain everything.

```python
_US = "\x1f"   # unit separator — cannot appear in a commit message
_RS = "\x1e"   # record separator
_LOG_FORMAT = _US.join(["%H", "%an", "%aI", "%s"]) + _RS


def parse_log(stdout: str) -> list[dict[str, str]]:
    """Parse `git log --format=<_LOG_FORMAT>` output into records."""
    out: list[dict[str, str]] = []
    for record in stdout.split(_RS):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(_US)
        if len(parts) != 4:
            continue
        sha, author, date, subject = parts
        out.append({"sha": sha, "author": author, "date": date,
                    "subject": subject})
    return out
```

### Pattern to Follow — degrade, never raise

```python
    @tool_schema(GitLogInput)
    async def git_log(
        self, path: str = "", limit: int = 20,
    ) -> dict[str, Any] | RepoToolError:
        """List recent commits, optionally only those touching one path.

        Use this to understand why code looks the way it does, or to find when
        a behaviour changed. Paths are relative to the repository root.

        Args:
            path: Repository-relative path to filter by. Empty = whole repo.
            limit: Maximum commits to return (clamped to 200).

        Returns:
            Mapping with a ``commits`` list of {sha, author, date, subject},
            or RepoToolError when the path is refused or git is unavailable.
        """
        argv = ["git", "log", f"--max-count={min(max(limit, 1), 200)}",
                f"--format={_LOG_FORMAT}"]
        if path:
            try:
                target = resolve_within_root(self._repo_root, path)
            except PathOutsideRootError as exc:
                return self._error(exc, path)
            argv += ["--", str(target.relative_to(self._repo_root))]

        try:
            res = await self._run_argv(argv)
        except FileNotFoundError as exc:          # `git` not on PATH
            return RepoToolError(error="git_unavailable", detail=str(exc))
        if res["timed_out"]:
            return RepoToolError(error="timeout", detail="git log timed out")
        if res["exit_code"] != 0:
            return RepoToolError(error="git_error",
                                 detail=res["stderr"][:500], path=path)
        return {"commits": parse_log(res["stdout"])}
```

### Key Constraints

- **No mutating git subcommand may appear anywhere in the package.** A test greps
  for them. Read-only by construction extends to the argv you build.
- Reuse `_run_argv`; do not call `asyncio.create_subprocess_exec` directly here.
- Every `path` argument confined; `git_blame` additionally deny-listed (its output
  is file content).
- Bound `git_show` diff output at `max_result_bytes` with a visible marker.
- Put `validate_ref`, the argv builders, and the parsers at **module level** in
  `git_tools.py` — not as public async methods on the toolkit, or
  `_generate_tools()` (`toolkit.py:537`) would expose them as tools.
- `self.logger`, Google-style docstrings, strict type hints.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/repo/toolkit.py` — `_run_argv` (TASK-2639).
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` — what this is **not**
  (GitHub API; read the header to confirm, then leave it alone).
- Spec §7 "Known Risks / Gotchas" — the argv-injection row.

---

## Acceptance Criteria

- [ ] `git_log`, `git_show`, `git_blame` appear in `get_tools()`; the toolkit still
      exposes no write-shaped tool
- [ ] `git_log` returns parsed commits from `temp_repo` (which has two commits)
- [ ] `git_log` honours `limit` and clamps an absurd value
- [ ] `git_log` with a `path` filters to commits touching it, and refuses a path
      outside the root with a structured error
- [ ] `git_log` parses correctly when a commit subject contains spaces, a pipe,
      and a tab
- [ ] `git_show` returns the commit for a valid sha and for `HEAD`
- [ ] **`git_show` rejects an argv-injection ref**: `--upload-pack=/bin/sh`,
      `-x`, and `--output=/tmp/x` each return a structured error and spawn nothing
- [ ] `validate_ref` accepts `HEAD`, `HEAD~3`, a 40-char sha, `main`,
      `origin/main`, `v1.2.3`; rejects `""`, `--foo`, `-x`, and a ref with `;`
- [ ] `git_blame` returns per-line attribution for a tracked file and respects
      `start`/`end`
- [ ] `git_blame` refuses a deny-listed path with `error="secret_file"`
- [ ] **Degrades outside a git repo**: all three return a structured `RepoToolError`
      in a plain (non-git) directory — no exception escapes
- [ ] `git_show` bounds output at `max_result_bytes` with a visible marker
- [ ] No mutating git subcommand in the package:
      `grep -rnE '"(commit|checkout|push|fetch|reset|rebase|merge|apply|clean|rm|add)"' packages/ai-parrot/src/parrot/tools/repo/`
      returns nothing
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/repo/ -v`
- [ ] Clean: `ruff check` + `mypy` on the package

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/repo/test_git_tools.py
import subprocess
import pytest
from pathlib import Path

from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.tools.repo.git_tools import InvalidRefError, parse_log, validate_ref
from parrot.tools.repo.models import RepoToolError


@pytest.fixture
def toolkit(temp_repo: Path) -> ReadOnlyRepoToolkit:
    return ReadOnlyRepoToolkit(repo_root=temp_repo)


class TestValidateRef:
    @pytest.mark.parametrize("ref", [
        "HEAD", "HEAD~3", "main", "origin/main", "v1.2.3",
        "a" * 40, "HEAD^", "refs/heads/dev",
    ])
    def test_accepts(self, ref):
        assert validate_ref(ref) == ref

    @pytest.mark.parametrize("ref", [
        "", "   ", "--upload-pack=/bin/sh", "-x", "--output=/tmp/x",
        "HEAD; rm -rf /", "a b", "$(whoami)", "`id`",
    ])
    def test_rejects(self, ref):
        with pytest.raises(InvalidRefError):
            validate_ref(ref)


class TestParseLog:
    def test_handles_awkward_subjects(self):
        us, rs = "\x1f", "\x1e"
        raw = us.join(["sha1", "A U Thor", "2026-01-01T00:00:00+00:00",
                       "fix: a | b\twith tab"]) + rs
        [rec] = parse_log(raw)
        assert rec["subject"] == "fix: a | b\twith tab"


class TestGitLog:
    async def test_returns_commits(self, toolkit):
        out = await toolkit.git_log()
        assert len(out["commits"]) == 2
        assert out["commits"][0]["subject"] == "second"

    async def test_limit(self, toolkit):
        out = await toolkit.git_log(limit=1)
        assert len(out["commits"]) == 1

    async def test_path_filter(self, toolkit):
        out = await toolkit.git_log(path="pkg/sub/mod.py")
        assert len(out["commits"]) >= 1

    async def test_path_outside_root(self, toolkit):
        out = await toolkit.git_log(path="../../etc")
        assert isinstance(out, RepoToolError)
        assert out.error == "path_outside_root"


class TestGitShow:
    async def test_shows_head(self, toolkit):
        out = await toolkit.git_show("HEAD")
        assert not isinstance(out, RepoToolError)

    @pytest.mark.parametrize("bad", [
        "--upload-pack=/bin/sh", "-x", "--output=/tmp/pwned", "",
    ])
    async def test_rejects_argv_injection(self, toolkit, bad):
        out = await toolkit.git_show(bad)
        assert isinstance(out, RepoToolError)

    async def test_bounded(self, temp_repo):
        big = temp_repo / "huge.txt"
        big.write_text("y" * 300_000)
        subprocess.run(["git", "add", "-A"], cwd=temp_repo, check=True)
        subprocess.run(["git", "commit", "-qm", "huge"], cwd=temp_repo, check=True)
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, max_result_bytes=2000)
        out = await tk.git_show("HEAD")
        assert len(str(out)) < 100_000


class TestGitBlame:
    async def test_blames(self, toolkit):
        out = await toolkit.git_blame("pkg/sub/mod.py")
        assert not isinstance(out, RepoToolError)

    async def test_refuses_secret(self, toolkit):
        out = await toolkit.git_blame(".env")
        assert isinstance(out, RepoToolError) and out.error == "secret_file"


class TestDegradesOutsideGit:
    @pytest.fixture
    def plain(self, tmp_path: Path) -> Path:
        d = tmp_path / "plain"
        d.mkdir()
        (d / "a.py").write_text("x = 1\n")
        return d

    async def test_all_three_degrade(self, plain):
        tk = ReadOnlyRepoToolkit(repo_root=plain)
        assert isinstance(await tk.git_log(), RepoToolError)
        assert isinstance(await tk.git_show("HEAD"), RepoToolError)
        assert isinstance(await tk.git_blame("a.py"), RepoToolError)


class TestNoMutatingGit:
    def test_package_has_no_mutating_subcommand(self):
        import pathlib, re
        banned = re.compile(
            r'"(commit|checkout|push|fetch|reset|rebase|merge|apply|clean|rm|add)"'
        )
        pkg = pathlib.Path("packages/ai-parrot/src/parrot/tools/repo")
        for f in pkg.rglob("*.py"):
            assert not banned.search(f.read_text()), f
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 3, §5, §6 (the "Does NOT Exist" entry about
   `gittoolkit.py`), §7 (Known Risks).
2. **Check dependencies** — TASK-2639 must be in `sdd/tasks/completed/`. You reuse
   its `_run_argv`.
3. **Verify the Codebase Contract**. Confirm for yourself that
   `parrot_tools/gittoolkit.py` is GitHub-API-only before writing anything.
4. Update the index → `"in-progress"`.
5. **Implement** per scope. Ref validation is the security control — write it first
   and test it hardest.
6. **Verify** all acceptance criteria, including the mutating-subcommand grep.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
