# TASK-3080: LocalGitToolkit — subprocess runner, repository discovery, git_recent, git_fetch, git_preflight

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3079
**Assigned-to**: unassigned

---

## Context

Spec §2 "Git Contract" items 1–5 and §3 Module M2 (first half). This task
creates `git.py` with the `LocalGitToolkit` class, its bounded subprocess
runner, repository/worktree discovery, and the three read-only or
fetch-only operations. TASK-3081 adds the mutating operations
(`git_prepare_files`, `git_pull`, `git_push`) to the same class.

The toolkit executes **no LLM calls** (AC2). All results are
`OperationResult` models (TASK-3079) carrying one `StepResult` per Git
command actually executed, so a caller can see exactly which step failed.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/git.py`:
  - `class LocalGitToolkit(OptimizationToolkitBase)` with
    `arg_models = {"git_recent": GitRecentArgs, "git_fetch": GitFetchArgs, "git_preflight": GitPreflightArgs}`
    (TASK-3081 extends this dict). `tool_prefix = None`. `confirming_tools`
    is set in TASK-3081.
  - `GIT_ENV: dict[str, str]` merged over `os.environ` for EVERY Git call:
    `GIT_TERMINAL_PROMPT=0`, `GIT_EDITOR=:`, `GIT_SEQUENCE_EDITOR=:`,
    `GIT_PAGER=cat`, `GIT_OPTIONAL_LOCKS=0`, `LC_ALL=C`, `LANG=C`,
    `GIT_LITERAL_PATHSPECS=1`, `GIT_CONFIG_NOSYSTEM` NOT set (user config
    must still apply for remotes/credentials). Never pass a caller string
    as an option; every argv places `--end-of-options` or `--` before
    caller-derived values.
  - `async _run_git(self, args: Sequence[str], *, timeout: float | None = None, cwd: Path | None = None, extra_env: dict[str, str] | None = None, stdin_bytes: bytes | None = None, max_capture: int = 1_048_576) -> StepResult`:
    `asyncio.create_subprocess_exec("git", *args, stdin=PIPE if stdin_bytes else DEVNULL, stdout=PIPE, stderr=PIPE, cwd=..., env=...)`;
    drain stdout/stderr concurrently with a capped buffer (`max_capture`)
    but KEEP READING until EOF after the cap so the child never blocks on
    a full pipe; `asyncio.wait_for` on the drain tasks + `proc.wait()`;
    on `TimeoutError` → `proc.kill()`, `await proc.wait()`,
    `StepResult(exit_code=None, timed_out=True)`; on
    `asyncio.CancelledError` → kill, then re-raise. Exit code decides
    success; `truncated=True` only when the cap was hit. `state_changed`
    is set by the caller (the runner cannot know).
    Decode as UTF-8 with `errors="replace"`. `-z` outputs are split on
    `\x00` by callers — pass `raw_stdout: bytes` back on the StepResult
    via a private attribute (`_raw_stdout`, excluded from the model) OR
    return `(StepResult, bytes)`; pick the tuple form:
    `async _run_git(...) -> tuple[StepResult, bytes]`.
  - `class RepoLayout(BaseModel)` (in `git.py`): `toplevel: Path`,
    `git_dir: Path` (per-worktree, absolute), `common_dir: Path`,
    `is_linked_worktree: bool`, `index_path: Path` (`git_dir / "index"`),
    `lock_path: Path` (`git_dir / "parrot-tool-optimizations.lock"`).
  - `async _discover(self) -> RepoLayout | OperationResult`: run
    `git rev-parse --is-bare-repository --show-toplevel --absolute-git-dir --git-common-dir`
    (one call; four output lines). Refuse `true` bare → error
    `bare_repository`. `--git-common-dir` may be relative → resolve
    against `git_dir`'s parent… no: resolve it with
    `(policy.repo_root / value).resolve()` when not absolute. Toplevel
    must equal `policy.repo_root` (resolved) → else `root_mismatch`.
    `is_linked_worktree = git_dir != common_dir`. Cache the layout per
    instance after first success (`self._layout`), but re-validate
    `index_path.parent.exists()` on every mutating call (TASK-3081).
  - `_validate_remote(remote: str, remotes: list[str])`: remote must be in
    `git remote` output, must match `^[A-Za-z0-9._-]+$`, no leading `-`.
  - `_validate_branch(branch: str) -> str`: regex
    `^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$`, no `..`, no `@{`, no trailing
    `/`, `.lock` suffix or `.`; THEN
    `git check-ref-format --branch <branch>` must exit 0 (use
    `--end-of-options`? `check-ref-format` has no such flag — the regex
    already forbids a leading `-`). Refspecs (`:`), `HEAD`, `~`, `^` are
    rejected by the regex.
  - `async _resolve_commit(self, ref: str) -> tuple[str | None, StepResult]`:
    `validate_ref(ref)` from `parrot.tools.repo.git_tools` first, then
    `git rev-parse --verify --end-of-options <ref>^{commit}`; returns the
    40-hex sha or `None` (error code `unknown_ref`).
  - `async git_recent(self, ref: str = "HEAD", limit: int = 3) -> OperationResult`
    (decorate with `@tool_schema(GitRecentArgs)`): validate
    `GitRecentArgs(ref=ref, limit=limit)`; resolve ref to a commit;
    `git log --max-count=<limit> --format=<LOG_FORMAT> --end-of-options <sha> --`;
    `data = {"ref": ref, "commit": sha, "commits": parse_log(stdout)}`.
  - `async git_fetch(self, remote: str = "origin", branch: str = "dev", recent: int = 3) -> OperationResult`
    (`@tool_schema(GitFetchArgs)`): validate remote + branch; run
    `git fetch --no-tags --no-recurse-submodules --end-of-options <remote> refs/heads/<branch>:refs/remotes/<remote>/<branch>`
    with `timeout=policy.network_timeout_seconds` (no `+` → never a
    forced update; a non-fast-forward remote-tracking update is reported
    as `fetch_rejected` with git's stderr). On failure STOP (no history
    lookup). On success: `fetched = git rev-parse --verify FETCH_HEAD`,
    `tracking = git rev-parse --verify refs/remotes/<remote>/<branch>^{commit}`;
    `fresh = fetched == tracking`; if not fresh → status `uncertain`,
    code `tracking_ref_stale` (still return `fetched_commit`). Then
    `git log` on `fetched` (recent commits) as in `git_recent`.
    `data = {"remote", "branch", "fetched_commit", "tracking_ref", "tracking_commit", "fresh", "commits"}`.
  - `async git_preflight(self) -> OperationResult` (`@tool_schema(GitPreflightArgs)`):
    run ALL of the following even if one fails, each as its own step, and
    report per-check results in `data["checks"]` (dict of name →
    `{"ok": bool, "exit_code": int|None, "detail": str}`):
    1. `git status --porcelain=v2 -z --branch --untracked-files=normal`
       → parse header lines `# branch.oid`, `# branch.head`,
       `# branch.upstream`, `# branch.ab` and entries (`1 `, `2 `, `u `,
       `? `, `! `). Report `branch`, `detached` (`branch.head` ==
       `(detached)`), `unborn` (`branch.oid` == `(initial)`),
       `upstream`, `ahead`, `behind`, counts of staged / unstaged /
       untracked / unmerged, and up to 50 paths per category.
    2. `git diff --check` (unstaged whitespace) — exit 2 means errors;
       collect offending `path:line` lines (bounded).
    3. `git diff --cached --check` (staged whitespace).
    4. `git diff --cached --name-only -z` → staged names list.
    Overall `status` = `ok` when every check passed, else `error` with
    code `preflight_failed` and `details["failed"] = [check names]`.
- Register nothing in MCP config here (TASK-3087) but DO run
  `python scripts/generate_tool_registry.py --check`; if it reports the
  new class, run it without flags and include the updated
  `packages/ai-parrot-tools/src/parrot_tools/__init__.py` in the commit.
- Tests: `packages/ai-parrot-tools/tests/tool_optimizations/test_git.py`
  (read/fetch/preflight halves; TASK-3081 appends mutation tests) with a
  `conftest.py` in the same directory providing fixtures:
  `git_repo(tmp_path)` (init, `user.name/email` set, `commit.gpgsign=false`,
  deterministic dates via `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE`),
  `bare_remote(git_repo)` (`git init --bare` + `git remote add origin`),
  `linked_worktree(git_repo)` (`git worktree add`).

**NOT in scope**: `git_prepare_files`, `git_pull`, `git_push`, the index
transaction, `confirming_tools` (TASK-3081); MCP YAML wiring (TASK-3087).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/git.py` | CREATE | `LocalGitToolkit` (read/fetch/preflight half) |
| `packages/ai-parrot-tools/tests/tool_optimizations/conftest.py` | CREATE | Temp repo / bare remote / linked worktree fixtures |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_git.py` | CREATE | Unit tests for this half |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY (only if the registry script demands it) | `TOOL_REGISTRY` entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.tool_optimizations.base import OptimizationToolkitBase          # TASK-3079
from parrot_tools.tool_optimizations.models import (                              # TASK-3079
    OperationResult, OperationError, StepResult, GitRecentArgs, GitFetchArgs, GitPreflightArgs,
)
from parrot_tools.tool_optimizations.policy import OptimizationPolicy, WorktreeLock
from parrot.tools.decorators import tool_schema                                    # packages/ai-parrot/src/parrot/tools/decorators.py:39
from parrot.tools.repo.git_tools import LOG_FORMAT, InvalidRefError, parse_log, validate_ref
# packages/ai-parrot/src/parrot/tools/repo/git_tools.py:24 (LOG_FORMAT), :28, :61, :32
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/repo/git_tools.py
_REF_OK = re.compile(r"^[A-Za-z0-9._/~^@{}-]{1,255}$")          # :20
LOG_FORMAT = "\x1f".join(["%H", "%an", "%aI", "%s"]) + "\x1e"    # :24
def validate_ref(ref: str) -> str                                 # :32  raises InvalidRefError on option-shaped / bad chars
def parse_log(stdout: str) -> list[dict[str, str]]                # :61  → [{sha, author, date, subject}]

# packages/ai-parrot/src/parrot/tools/repo/toolkit.py — the runner pattern to IMPROVE upon (do not import it)
async def _run_argv(self, argv: Sequence[str], *, timeout: float | None = None) -> dict[str, Any]   # :334
#   uses asyncio.create_subprocess_exec + wait_for(proc.communicate()) (:361-367); kills on timeout (:369-371)
#   and on CancelledError (:378-381). It does NOT bound memory while draining — this task must.
def _is_git_work_tree(self) -> bool: return shutil.which("git") is not None and (self._repo_root / ".git").exists()  # :398 — WRONG for linked worktrees (.git is a file); do not copy.

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1671
if not os.path.isdir(os.path.join(repo_path, ".git")):   # same mistake — never replicate
```

### Does NOT Exist
- ~~`git rev-parse --absolute-git-dir` on git < 2.13~~ — assume git ≥ 2.24 (also needed for `--end-of-options`); assert once in `_discover` via `git --version` and return `git_too_old` otherwise.
- ~~`LocalGitToolkit` in core `parrot.tools`~~ — it lives in `parrot_tools.tool_optimizations.git` only.
- ~~`ReadOnlyRepoToolkit.git_log` reuse~~ — different toolkit, different result shape; only the format/parser helpers are shared.
- ~~`git fetch` updating `refs/remotes/<r>/<b>` when a bare `git fetch <r> <b>` is used~~ — without the explicit destination refspec only `FETCH_HEAD` is guaranteed. Always pass the explicit refspec.
- ~~`GitToolkit`'s `_run_subprocess` / `_scrub`~~ — belongs to `parrot_tools.gittoolkit`; not reused here.
- ~~A `ToolResult` return from public methods~~ — return `OperationResult`; the base `_post_execute` wraps it.

---

## Implementation Notes

### Pattern to Follow
```python
# Bounded, deadlock-free drain (spec Git Contract 2)
async def _drain(stream: asyncio.StreamReader, cap: int) -> tuple[bytes, bool]:
    buf = bytearray(); truncated = False
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return bytes(buf), truncated
        if len(buf) < cap:
            buf += chunk[: cap - len(buf)]
        if len(buf) >= cap and len(chunk):
            truncated = True   # keep reading; discard beyond cap

async def _run_git(self, args, *, timeout=None, cwd=None, extra_env=None, stdin_bytes=None, max_capture=1_048_576):
    env = {**os.environ, **GIT_ENV, **(extra_env or {})}
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd or self.policy.repo_root), env=env,
        stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout or self.policy.command_timeout_seconds):
            if stdin_bytes is not None:
                proc.stdin.write(stdin_bytes); await proc.stdin.drain(); proc.stdin.close()
            (out, out_trunc), (err, err_trunc) = await asyncio.gather(_drain(proc.stdout, max_capture), _drain(proc.stderr, 65536))
            code = await proc.wait()
    except TimeoutError:
        proc.kill(); await proc.wait()
        return StepResult(name=" ".join(args[:2]), exit_code=None, timed_out=True, state_changed=False, stderr="timeout"), b""
    except asyncio.CancelledError:
        proc.kill(); raise
    return StepResult(name=" ".join(args[:2]), exit_code=code, timed_out=False, state_changed=False,
                      stdout=out.decode("utf-8", "replace"), stderr=err.decode("utf-8", "replace")[:4096],
                      truncated=out_trunc or err_trunc), out
```

```python
# Discovery (spec Git Contract 1)
step, raw = await self._run_git(["rev-parse", "--is-bare-repository", "--show-toplevel", "--absolute-git-dir", "--git-common-dir"])
is_bare, toplevel, git_dir, common = step.stdout.splitlines()[:4]
```

```python
# status --porcelain=v2 -z parsing hints
# header lines start with "# "; entries: "1 XY sub mH mI mW hH hI path", "2 ... path\0orig", "u ... path", "? path", "! path"
# X = index status, Y = worktree status; "." means unchanged. Split the -z stream on b"\0"; the "2 " (rename) entry consumes TWO records.
```

### Key Constraints
- Every git argv is a list; never `shell=True`; never f-string a caller
  value into an option. Place `--end-of-options` before refs and `--`
  before paths.
- A fetch failure must not fall through to history lookup (Contract 4).
- Preflight must run every check regardless of earlier failures (Contract 5).
- Truncation of a step's stdout never changes its exit-code-derived
  success; report `truncated=True` (Contract 2).
- `StepResult.name` is the git subcommand (e.g. `"fetch"`), never the full
  argv with user data — full argv only at `self.logger.debug` level.
- Timeouts: `command_timeout_seconds` for local commands,
  `network_timeout_seconds` for `fetch`.
- Keep imports lazy for anything heavy; `git.py` must import without AWS
  or MCP dependencies (spec §7 Patterns).

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/repo/toolkit.py:334-396` — runner + kill pattern.
- `packages/ai-parrot/src/parrot/tools/repo/toolkit.py:527-574` — `git log` argv shape with `LOG_FORMAT` and `--`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:428-451` — how linked worktrees are handled (`.git` may be a file; hooks resolve to the common dir).

---

## Acceptance Criteria

- [ ] `LocalGitToolkit(repo_root=...).get_tools()` exposes exactly `git_recent`, `git_fetch`, `git_preflight` (until TASK-3081) and every one is an `AbstractTool`.
- [ ] `git_recent` limit 1–50 enforced (51 rejected via `_pre_execute` and via direct call); `ref="--upload-pack=x"` rejected as `invalid_ref` without spawning git.
- [ ] `git_fetch` against a local bare remote returns `fetched_commit == tracking_commit`, `fresh is True`; against an unknown remote name returns `error/unknown_remote` with no fetch step; a failing fetch (remote path deleted) returns `error/fetch_failed` and NO log step.
- [ ] Freshness test: pre-create a stale `refs/remotes/origin/dev` pointing elsewhere, force the remote to a non-descendant history, fetch → `fetch_rejected` (no `+` refspec).
- [ ] `git_preflight` on a repo with unstaged whitespace errors AND staged files reports both `checks["diff_check"].ok is False` and the staged list; every check has an entry even when the first fails.
- [ ] Linked worktree: `_discover` returns `is_linked_worktree=True`, `git_dir` under `.git/worktrees/`, `index_path` exists.
- [ ] Bare repository → `bare_repository`; `repo_root` not the toplevel → `root_mismatch`.
- [ ] A 5 MiB-stdout command (fixture: `git log` with many commits or a test double of `_run_git` on `yes | head -c`) completes with `truncated=True` and no deadlock.
- [ ] Timeout test (`command_timeout_seconds=0.2` with a `git` wrapper that sleeps, via `PATH` fixture) → `timed_out=True`, `exit_code None`, no orphan process.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_git.py -v`
- [ ] `ruff check` + `black --check` clean on the new files.
- [ ] Log saved to `artifacts/logs/TASK-3080-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/conftest.py
import os, subprocess
from pathlib import Path
import pytest

ENV = {**os.environ, "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
       "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

def git(cwd: Path, *args: str, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, capture_output=True, text=True, check=check)

@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"; repo.mkdir()
    git(repo, "init", "-q", "-b", "dev"); git(repo, "config", "commit.gpgsign", "false")
    (repo / "a.py").write_text("print('a')\n"); git(repo, "add", "a.py"); git(repo, "commit", "-q", "-m", "init")
    return repo

@pytest.fixture
def bare_remote(git_repo: Path, tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"; git(tmp_path, "init", "-q", "--bare", str(remote))
    git(git_repo, "remote", "add", "origin", str(remote)); git(git_repo, "push", "-q", "origin", "dev")
    return remote

@pytest.fixture
def linked_worktree(git_repo: Path, tmp_path: Path) -> Path:
    wt = tmp_path / "wt"; git(git_repo, "worktree", "add", "-q", "-b", "feat", str(wt))
    return wt
```

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_git.py (this task's half)
from parrot_tools.tool_optimizations.git import LocalGitToolkit

async def test_recent_limit_and_option_shaped_ref(git_repo):
    tk = LocalGitToolkit(repo_root=git_repo)
    res = await tk.git_recent(limit=1)
    assert res.status == "ok" and len(res.data["commits"]) == 1
    bad = await tk.git_recent(ref="--upload-pack=/bin/sh")
    assert bad.status == "error" and bad.error.code == "invalid_ref" and bad.steps == []

async def test_fetch_reports_fetched_and_fresh(git_repo, bare_remote):
    res = await LocalGitToolkit(repo_root=git_repo).git_fetch(remote="origin", branch="dev", recent=1)
    assert res.status == "ok" and res.data["fresh"] is True and res.data["fetched_commit"] == res.data["tracking_commit"]

async def test_fetch_failure_stops_history(git_repo, bare_remote):
    import shutil; shutil.rmtree(bare_remote)
    res = await LocalGitToolkit(repo_root=git_repo).git_fetch()
    assert res.status == "error" and res.error.code == "fetch_failed"
    assert [s.name for s in res.steps] == ["fetch"]

async def test_preflight_runs_every_check(git_repo):
    (git_repo / "a.py").write_text("print('a') \n")          # trailing whitespace → diff --check fails
    (git_repo / "b.py").write_text("x = 1\n"); git(git_repo, "add", "b.py")
    res = await LocalGitToolkit(repo_root=git_repo).git_preflight()
    assert set(res.data["checks"]) == {"status", "diff_check", "cached_check", "staged_names"}
    assert res.data["checks"]["diff_check"]["ok"] is False and res.data["staged"] == ["b.py"]
    assert res.status == "error" and res.error.code == "preflight_failed"

async def test_linked_worktree_discovery(linked_worktree):
    layout = await LocalGitToolkit(repo_root=linked_worktree)._discover()
    assert layout.is_linked_worktree and ".git/worktrees/" in layout.git_dir.as_posix()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3079 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3080-local-git-discovery-fetch-preflight.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5, session_01G9NM1TzdkFLd5foNDmh72K)
**Date**: 2026-09-10
**Notes**:

Created `git.py` with `LocalGitToolkit` (read/fetch/preflight half),
`RepoLayout`, `GIT_ENV`, the bounded `_run_git` runner and module-level
output parsers. `get_tools()` exposes exactly `git_recent`, `git_fetch`,
`git_preflight`. No LLM call anywhere in this module (AC2).

Codebase Contract verified: `validate_ref`/`parse_log`/`LOG_FORMAT`/
`InvalidRefError` are all present at the cited lines in
`parrot/tools/repo/git_tools.py`; `tool_schema` sets `_args_schema` as
documented. Local git is 2.43.0, above the 2.24 floor `--end-of-options`
and `--absolute-git-dir` need.

Empirically-established behaviors that shaped the implementation (probed
against real git before coding, not assumed):

- **A bare repo makes the combined `rev-parse` exit 128**, because
  `--show-toplevel` needs a work tree — but it still prints `true` for
  `--is-bare-repository` on stdout first. So `_discover` checks the bare
  marker BEFORE the exit code; checking exit code first would misreport a
  bare repo as `not_a_repository`.
- **`--git-common-dir` is relative (`.git`) in a normal checkout but
  absolute in a linked worktree.** Both are handled; `is_linked_worktree`
  is derived from `git_dir != common_dir`, never from probing whether
  `.git` is a directory (the mistake called out in the contract at
  `repo/toolkit.py:398` and `gittoolkit.py:1671`).
- `_drain` keeps reading past the cap and discards the excess, so a
  ~5.5 MiB `git show` is capped at exactly 1 MiB with `truncated=True` and
  no pipe deadlock (`test_runner_bounds_large_output_without_deadlock`).

Contract compliance worth noting: the fetch uses an explicit
`refs/heads/<b>:refs/remotes/<r>/<b>` refspec with **no** leading `+`, so a
non-fast-forward tracking update surfaces as `fetch_rejected` (covered by a
real unrelated-history test, not a mock). A failed fetch returns only the
`fetch` step and never performs the history lookup. `git_preflight` runs all
four checks unconditionally and reports each one, and both `git_fetch` and
`git_preflight` attach `data` to the *error* result too, so a failed
preflight still returns the staged list and parsed status.

**Testing**: 30 tests in `test_git.py`, 57 across the feature suite; ruff and
black clean. Log at `artifacts/logs/TASK-3080-pytest.log`.

**Deviations from spec**: none, with two recorded judgement calls:

1. **`scripts/generate_tool_registry.py` was NOT run in bulk.** Running it
   wholesale also added an unrelated `contracts:` entry, dropped the
   `google_lyria` alias and reordered several blocks — unrelated churn that
   Cardinal Rule 5 forbids. The registry file was reverted and the single
   `"local_git"` entry added by hand. The pre-existing registry staleness on
   `dev` is left untouched for its own owner.
2. The task's own test spec asserts `[s.name for s in res.steps] == ["fetch"]`
   on a failed fetch, so the failure path deliberately reports only the fetch
   step (the preceding `remote` listing step is dropped). Implemented to the
   task's assertion.
