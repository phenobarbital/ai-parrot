# TASK-3081: LocalGitToolkit — isolated-index staging (git_prepare_files), fast-forward pull and non-force push

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-3080
**Assigned-to**: unassigned

---

## Context

Spec §2 "Git Contract" items 6–12, §3 Module M2 (second half), AC3, AC4.
This task adds the three mutating operations to `LocalGitToolkit`. The
core idea for `git_prepare_files` is an **index transaction**: stage into
a private copy of the index (`GIT_INDEX_FILE`), run every check against
that copy, and publish it only if the real index is unchanged and the
normal `index.lock` can be taken. `git reset` is never executed. Rejection
or failure leaves the original index and working files byte-identical.

The user's original recipe was
`git reset HEAD && git add -- {filename} && git diff --cached --name-only && git diff --cached --check`
(spec §6 "User-Provided Code"). The accepted design replaces the global
reset with **refusal** when unrelated paths are already staged.

---

## Scope

- Extend `git.py` (`LocalGitToolkit`):
  - `arg_models` gains `git_prepare_files: GitPrepareFilesArgs`,
    `git_pull: GitPullArgs`, `git_push: GitPushArgs`.
  - `confirming_tools = frozenset({"git_prepare_files", "git_pull", "git_push"})`.
    Consequence (verified): `_create_tool_from_method` sets
    `routing_meta["requires_confirmation"]=True` (`toolkit.py:686-689`)
    and the MCP adapter injects a required `confirm: bool` argument and
    rejects calls without `confirm=true` (`adapter.py:38-49, :59-73`).
    The `confirm` key never reaches `_pre_execute` (popped at `:59`), so
    the argument models must NOT declare it. Document in the method
    docstrings that `confirm` is the host-side approval record, not a
    model-settable authorization (spec Git Contract 12).
  - All three mutations run inside
    `async with WorktreeLock(layout.lock_path, timeout=policy.command_timeout_seconds)`
    (Contract 11) AND still use Git's own locks + revision checks.
- `async git_prepare_files(self, paths: list[str]) -> OperationResult` (`@tool_schema(GitPrepareFilesArgs)`):
  1. Validate: non-empty, unique after normalisation, each path a
     literal relative POSIX path: reject absolute, `..`, empty segments,
     leading `:` (pathspec magic), any of `*?[]` and `\\`, trailing `/`.
     Resolve with `resolve_operand(policy, p, must_exist=False)` (contains
     + secret + symlink-component checks) → repo-relative string. Reject
     directories (`is_dir()`), submodules/gitlinks (`git ls-files -s -z --
     <p>` mode `160000`), and symlinks (`lstat`). A path that does not
     exist on disk is accepted only if tracked
     (`git ls-files --error-unmatch -z -- <p>` exit 0) → **tracked
     deletion**.
  2. Refuse if the index has unmerged entries (`git ls-files -u -z` non-empty) → `unmerged_index`.
  3. Read current staging: `git diff --cached --name-only -z` → `staged`;
     `git diff --name-only -z` → `unstaged_modified`. Refuse
     `unrelated_staged` if `staged - selected` is non-empty. Refuse
     `partially_staged` for any selected path present in BOTH `staged`
     and `unstaged_modified` (whole-file staging would replace the partial
     hunk). Already fully staged selected files are fine.
  4. Fingerprint the real index: `(size, mtime_ns, sha256(bytes))` of
     `layout.index_path` (missing index → fingerprint `None`, allowed on
     an unborn repo). Refuse `index_unsupported` if `git config --get
     core.splitIndex` is `true` or `git config --get index.sparse` is `true`.
  5. Copy the index bytes to a private file INSIDE `layout.git_dir`
     (`tempfile.NamedTemporaryFile(dir=git_dir, prefix="parrot-index-", delete=False)`),
     then run with `extra_env={"GIT_INDEX_FILE": <abs temp path>}`:
     `git add --end-of-options -- <paths...>` (with `GIT_LITERAL_PATHSPECS=1`
     already in `GIT_ENV`; `git add` on a tracked-but-deleted path stages the
     removal). Then verify in the SAME temp index:
     `git diff --cached --name-only -z` must equal the selected set
     exactly (`staged_mismatch` otherwise) and `git diff --cached --check`
     must exit 0 (`whitespace_errors`, include offending lines).
  6. Publish: re-fingerprint the real index → if changed → `index_changed`
     (abort, delete temp). Acquire Git's index lock by creating
     `layout.index_path.with_name("index.lock")` with
     `os.open(O_CREAT|O_EXCL|O_WRONLY, 0o644)` → `EEXIST` →
     `index_locked` (another git process; never delete it). Copy the temp
     index bytes into `index.lock`, `fsync`, `os.replace(index.lock, index)`
     (this is exactly how git commits an index). On any exception before
     the replace: unlink ONLY our `index.lock` (we created it) and the temp
     file. Always unlink the temp file in `finally`.
  7. Result `data = {"staged": [...], "deleted": [...], "whitespace_ok": True, "index_published": True}`;
     steps include every git call with `state_changed=True` only on the
     publish step.
- `async git_pull(self, remote: str = "origin", branch: str | None = None) -> OperationResult` (`@tool_schema(GitPullArgs)`):
  1. Discover; `git status --porcelain=v2 -z --branch` (reuse the parser
     from TASK-3080). Refuse: detached (`detached_head`), unborn
     (`unborn_head`), any staged entries (`staged_changes`), any unstaged
     tracked modification (`dirty_worktree`), unmerged (`unmerged_index`).
     Untracked files are allowed.
  2. Branch resolution: if `branch is None`, require `branch.upstream`
     from the status header (`missing_upstream` otherwise) and that its
     remote part equals `remote` (`upstream_remote_mismatch`); if
     `branch` is given, it must equal the current branch (`branch_mismatch`).
  3. Fetch exactly as `git_fetch` does (explicit refspec, no `+`, network
     timeout). On failure → stop.
  4. `git merge-base --is-ancestor <fetched_sha> HEAD` exit 0 → already up
     to date (`ok`, `updated=False`). Else
     `git merge-base --is-ancestor HEAD <fetched_sha>` must exit 0 →
     otherwise `diverged` (report both shas, ahead/behind via
     `git rev-list --left-right --count HEAD...<sha>`).
  5. `git -c merge.autoStash=false merge --ff-only --no-autostash --end-of-options <fetched_sha>`.
     Git itself refuses to overwrite untracked files
     (`untracked_conflict`, stderr passed through; nothing was changed).
     No stash, rebase or merge commit ever (Contract 9).
  6. `data = {"branch", "remote", "before", "after", "updated"}`.
- `async git_push(self, remote: str = "origin", branch: str | None = None) -> OperationResult` (`@tool_schema(GitPushArgs)`):
  1. Discover + status header; refuse detached/unborn; resolve `branch`
     like pull (explicit must equal current). Verify `remote` exists.
  2. `git push --porcelain --no-force-with-lease --end-of-options <remote> refs/heads/<b>:refs/heads/<b>`
     — no `--force`, no `--all`, no `--mirror`, no `+` refspec, never
     creates commits (Contract 10). `timeout=policy.network_timeout_seconds`.
  3. Parse `--porcelain` lines (`<flag>\t<from>:<to>\t<summary>`): flag
     `' '` ok, `'='` up-to-date, `'*'` new ref, `'!'` rejected
     (`push_rejected`, summary carries `[rejected]`/reason), `'-'`
     deleted / `'+'` forced → must never appear, treat as `error`.
  4. Timeout → status `uncertain`, code `push_timeout`; then ONE
     `git ls-remote --heads --end-of-options <remote> refs/heads/<b>`
     (own network timeout) to resolve: if the remote sha equals local HEAD
     → upgrade to `ok` with `resolved_after_timeout=True`; if it fails or
     differs → stay `uncertain` (do not retry the push).
  5. `data = {"branch", "remote", "local_commit", "remote_commit_before", "remote_commit_after", "summary"}`.
- Tests: append to `test_git.py` (mutation cases listed in spec §4
  `test_git.py`) — see Test Specification.

**NOT in scope**: MCP wiring, docs, benchmarks, cross-process tests
(TASK-3091 covers two-process contention).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/git.py` | MODIFY | Add `git_prepare_files`, `git_pull`, `git_push`, confirming_tools |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_git.py` | MODIFY | Mutation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.tool_optimizations.base import OptimizationToolkitBase
from parrot_tools.tool_optimizations.models import (
    OperationResult, OperationError, StepResult, GitPrepareFilesArgs, GitPullArgs, GitPushArgs,
)
from parrot_tools.tool_optimizations.policy import WorktreeLock, LockTimeoutError, resolve_operand, SymlinkRejectedError
from parrot.tools.repo.confinement import PathOutsideRootError, SecretFileError   # confinement.py:55, :59
from parrot.tools.decorators import tool_schema                                    # decorators.py:39
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
confirming_tools: frozenset = frozenset()        # :275 — method names; applied at :684-689 → tool.routing_meta["requires_confirmation"] = True

# packages/ai-parrot/src/parrot/mcp/adapter.py
def _requires_confirmation(self) -> bool         # :23  reads routing_meta
def to_mcp_tool_definition(self)                 # :27  injects required "confirm" boolean at :38-49
async def execute(self, arguments)               # :58  :59 confirm = arguments.pop("confirm", None); rejects unless True (:60-73)

# TASK-3080 (same file, git.py)
async def _run_git(self, args, *, timeout=None, cwd=None, extra_env=None, stdin_bytes=None, max_capture=1_048_576) -> tuple[StepResult, bytes]
async def _discover(self) -> RepoLayout | OperationResult     # RepoLayout.index_path / .lock_path / .git_dir / .is_linked_worktree
def _validate_remote(...); def _validate_branch(...); async def _resolve_commit(...)
# status --porcelain=v2 parser from git_preflight (factor it into `_parse_status_v2(raw: bytes) -> StatusV2`)
```

### Does NOT Exist
- ~~`git add -N` / `git update-index` based staging~~ — use `git add` inside the temp index only.
- ~~`git reset`~~ in any form — forbidden by spec (Contract 8); tests grep the module source for `"reset"` in argv literals.
- ~~`git stash`, `pull --rebase`, `--autostash`, `push --force*`, `push --all`, `+refs/...`~~ — forbidden.
- ~~`git apply --cached`~~ — not the mechanism here.
- ~~Deleting a foreign `index.lock`~~ — never; report `index_locked`.
- ~~`GIT_INDEX_FILE` relative paths~~ — always absolute (git resolves relative values against cwd, which differs in linked worktrees).
- ~~`shutil.copy` of the index into the real `index`~~ — publishing goes through `index.lock` + `os.replace`.
- ~~An "unstage unrelated files" option~~ — refusal is the only behaviour (spec §8 decision).

---

## Implementation Notes

### Pattern to Follow
```python
# Index transaction skeleton (Contract 6-8)
async def git_prepare_files(self, paths: list[str]) -> OperationResult:
    """Stage exactly the given files after whitespace checks, without touching unrelated staging. ..."""
    started = time.perf_counter(); steps: list[StepResult] = []
    args = GitPrepareFilesArgs(paths=paths)                      # direct-call validation
    layout = await self._discover()
    if isinstance(layout, OperationResult): return layout
    async with WorktreeLock(layout.lock_path, self.policy.command_timeout_seconds):
        selected = self._normalise_literal_paths(args.paths)      # may return an error OperationResult
        ...pre-checks (unmerged / unrelated_staged / partially_staged)...
        fp_before = _fingerprint(layout.index_path)
        tmp = tempfile.NamedTemporaryFile(dir=layout.git_dir, prefix="parrot-index-", delete=False); tmp.close()
        try:
            if layout.index_path.exists(): shutil.copyfile(layout.index_path, tmp.name)
            env = {"GIT_INDEX_FILE": tmp.name}
            step, _ = await self._run_git(["add", "--end-of-options", "--", *selected], extra_env=env); steps.append(step)
            ...verify names (-z) and --check in the temp index...
            if _fingerprint(layout.index_path) != fp_before: return self._error(..., "index_changed", ...)
            lock = layout.index_path.with_name("index.lock")
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                return self._error(..., "index_locked", "another git process holds the index lock")
            try:
                with os.fdopen(fd, "wb") as fh, open(tmp.name, "rb") as src:
                    shutil.copyfileobj(src, fh); fh.flush(); os.fsync(fh.fileno())
                os.replace(lock, layout.index_path)              # atomic publish
            except BaseException:
                with contextlib.suppress(FileNotFoundError): os.unlink(lock)
                raise
        finally:
            with contextlib.suppress(FileNotFoundError): os.unlink(tmp.name)
```

```python
# push --porcelain parsing
for line in stdout.splitlines():
    if not line or line.startswith("To ") or line.startswith("Done"): continue
    flag, refs, _, summary = line[0], *line[1:].split("\t", 2)   # "<flag>\t<from>:<to>\t<summary>"
```

### Key Constraints
- Order of pre-checks: validate → unmerged → unrelated/partial → fingerprint
  → temp index → verify → re-fingerprint → lock → publish. Nothing is
  written to the real index before the last two steps.
- On ANY failure the real index bytes must be identical to the
  pre-operation fingerprint; tests compare `index` bytes before/after.
- Paths with spaces and non-ASCII names must round-trip through `-z`
  parsing (never `splitlines()` on path output).
- `state_changed=True` only on: index publish, `merge --ff-only` success,
  push (when `summary` is not up-to-date).
- The three methods must keep a Google-style docstring whose first
  sentence says exactly what mutates — it is the LLM-facing description.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/adapter.py:8-73` — confirm guard behaviour to document.
- `packages/ai-parrot/tests/mcp/test_adapter_confirm.py` — existing tests for the confirm flag (pattern for the MCP-side assertion).
- `.claude/hooks/dangerous-actions-blocker.sh` — the repo's own host-side guard for destructive shell commands; note it is unrelated to these tools but shows what hosts already block.

---

## Acceptance Criteria

- [ ] `git_prepare_files(["a.py"])` with `b.py` already staged → `unrelated_staged`; index bytes unchanged.
- [ ] Partially staged `a.py` (stage, then modify again) → `partially_staged`; index unchanged.
- [ ] Whitespace error in a selected file → `whitespace_errors`; index unchanged (the temp index is discarded).
- [ ] Tracked deletion (`rm b.py` then prepare `["b.py"]`) stages the removal; `git diff --cached --name-only` == `b.py`.
- [ ] Non-ASCII + space filename (`"año nuevo.py"`) staged correctly, single entry.
- [ ] Directory, glob (`*.py`), `:(top)` magic, symlink, submodule, `../x`, `.env` → rejected before any git write step.
- [ ] Pre-existing foreign `index.lock` → `index_locked`, file not deleted.
- [ ] Linked worktree prepare publishes to `.git/worktrees/<n>/index`, not the main index.
- [ ] `git_pull` refusals: detached, unborn, dirty, staged, missing upstream, explicit branch mismatch, diverged; untracked file that the merge would overwrite → `untracked_conflict` and the untracked file content preserved.
- [ ] `git_pull` fast-forward succeeds and `updated=True`; second call `updated=False`.
- [ ] `git_push` succeeds to bare remote; a remote that moved ahead → `push_rejected` with `[rejected]` in summary; module source contains no `"--force"`, `"reset"`, `"stash"` git argv.
- [ ] Push timeout (fake `git` on PATH that sleeps) → `uncertain`/`push_timeout`; with `ls-remote` resolvable → `ok` + `resolved_after_timeout`.
- [ ] `tools/list` over `StdioMCPServer` shows `confirm` as required for the three mutations and absent for `git_recent`.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_git.py -v`; lint clean; log in `artifacts/logs/TASK-3081-pytest.log`.

---

## Test Specification

```python
# appended to packages/ai-parrot-tools/tests/tool_optimizations/test_git.py
import hashlib
from parrot_tools.tool_optimizations.git import LocalGitToolkit

def _index_bytes(repo): return (repo / ".git" / "index").read_bytes()

async def test_prepare_refuses_unrelated_staging_and_preserves_index(git_repo):
    (git_repo / "b.py").write_text("b = 1\n"); git(git_repo, "add", "b.py")
    (git_repo / "a.py").write_text("print('A')\n")
    before = _index_bytes(git_repo)
    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py"])
    assert res.status == "error" and res.error.code == "unrelated_staged"
    assert _index_bytes(git_repo) == before

async def test_prepare_whitespace_failure_keeps_original_staging(git_repo):
    (git_repo / "a.py").write_text("print('A') \n")
    before = _index_bytes(git_repo)
    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py"])
    assert res.error.code == "whitespace_errors" and _index_bytes(git_repo) == before

async def test_prepare_stages_exact_names_including_deletion_and_unicode(git_repo):
    (git_repo / "año nuevo.py").write_text("x = 1\n"); git(git_repo, "add", "año nuevo.py"); git(git_repo, "commit", "-q", "-m", "u")
    (git_repo / "a.py").unlink(); (git_repo / "año nuevo.py").write_text("x = 2\n")
    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py", "año nuevo.py"])
    assert res.status == "ok" and sorted(res.data["staged"]) == ["a.py", "año nuevo.py"] and res.data["deleted"] == ["a.py"]
    assert git(git_repo, "diff", "--cached", "--name-only", "-z").stdout.split("\0")[:-1] == sorted(["a.py", "año nuevo.py"])

async def test_prepare_respects_foreign_index_lock(git_repo):
    lock = git_repo / ".git" / "index.lock"; lock.write_bytes(b"")
    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py"])
    assert res.error.code == "index_locked" and lock.exists()

async def test_pull_ff_only_and_diverged(git_repo, bare_remote, tmp_path):
    other = tmp_path / "other"; git(tmp_path, "clone", "-q", str(bare_remote), str(other))
    (other / "c.py").write_text("c\n"); git(other, "add", "c.py"); git(other, "commit", "-q", "-m", "c"); git(other, "push", "-q")
    tk = LocalGitToolkit(repo_root=git_repo)
    ok = await tk.git_pull(); assert ok.status == "ok" and ok.data["updated"] is True
    (git_repo / "d.py").write_text("d\n"); git(git_repo, "add", "d.py"); git(git_repo, "commit", "-q", "-m", "d")
    (other / "e.py").write_text("e\n"); git(other, "add", "e.py"); git(other, "commit", "-q", "-m", "e"); git(other, "push", "-q")
    div = await tk.git_pull(); assert div.error.code == "diverged"

async def test_push_rejected_without_force(git_repo, bare_remote, tmp_path):
    other = tmp_path / "other"; git(tmp_path, "clone", "-q", str(bare_remote), str(other))
    (other / "c.py").write_text("c\n"); git(other, "add", "c.py"); git(other, "commit", "-q", "-m", "c"); git(other, "push", "-q")
    (git_repo / "d.py").write_text("d\n"); git(git_repo, "add", "d.py"); git(git_repo, "commit", "-q", "-m", "d")
    res = await LocalGitToolkit(repo_root=git_repo).git_push()
    assert res.status == "error" and res.error.code == "push_rejected"

def test_no_forbidden_git_verbs_in_source():
    import inspect, parrot_tools.tool_optimizations.git as m
    src = inspect.getsource(m)
    for bad in ('"reset"', '"stash"', '"--force"', '"--force-with-lease"', '"--all"', '"--mirror"', '"rebase"'):
        assert bad not in src
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3080 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3081-local-git-prepare-pull-push.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5, session_01G9NM1TzdkFLd5foNDmh72K)
**Date**: 2026-09-10
**Notes**:

Added `git_prepare_files`, `git_pull` and `git_push` to `LocalGitToolkit`
plus `confirming_tools`. 91 tests pass across the feature suite; the file
was run 10x consecutively to prove stability (see the race note below).

Codebase Contract verified: `confirming_tools` is applied at
`toolkit.py:684-689`, and `MCPToolAdapter` injects the required `confirm`
boolean (`adapter.py:38-49`) and pops it before `_execute` (`:59`) — so the
argument models correctly do NOT declare `confirm`. Asserted end-to-end in
`test_mcp_tools_list_marks_confirm_required` /
`test_mcp_call_rejected_without_confirm`.

**Two real bugs found and fixed during implementation:**

1. **`git add --end-of-options -- <paths>` is broken.** Once
   `--end-of-options` has ended option parsing, git reads the following
   `--` as a *literal pathspec* and dies with
   `fatal: pathspec '--' did not match any files`. The two must never be
   combined. `git add -- <paths>` is used instead; the `--` separator alone
   already protects an option-shaped path, and `GIT_LITERAL_PATHSPECS=1`
   neutralizes pathspec magic. (`git log --end-of-options <sha> --` is
   unaffected and still works — the difference is that `log` has already
   consumed a revision.)

2. **Copying the index with `shutil.copyfile` silently loses edits.**
   Git decides an index entry is "racily clean" by comparing the entry's
   mtime against the *index file's own* mtime, re-hashing the file when it
   is. A copy made with `copyfile` gets a fresh mtime, which converts those
   racy entries into trusted-clean ones — so a same-size edit written
   within the same (coarse, ~ms) filesystem clock tick as the last
   `git add` was **not staged**, and the operation refused with
   `staged_mismatch`. Measured: 4/120 same-size edits before the fix, 0/240
   after switching to `shutil.copy2`, which preserves the mtime and makes
   the private copy behave exactly like the real index. Plain `git diff`
   missed the same change 0/200 times, which is what proved this was our
   bug and not a git limitation. Covered by
   `test_prepare_stages_same_size_edit_made_in_the_same_clock_tick`.
   This surfaced first as an intermittent (~1-in-4-runs) test failure; it
   was traced rather than retried, because the failure mode in production
   is a false refusal, not a crash.

Design notes:

- The transaction order is validate -> submodule/tracked-deletion ->
  unmerged -> unrelated/partial -> split/sparse -> fingerprint -> temp
  index -> verify names -> verify whitespace -> re-fingerprint -> `index.lock`
  -> `os.replace`. Nothing touches the real index before the last two steps,
  and every refusal test asserts the index bytes are byte-identical
  afterwards.
- Publication uses git's own mechanism: create `index.lock` with `O_EXCL`,
  write, `fsync`, `os.replace` onto `index`. A pre-existing lock is reported
  as `index_locked` and never removed; only a lock this process created is
  ever unlinked.
- `git reset` is never invoked in any form — enforced by
  `test_no_forbidden_git_verbs_in_source`, which also bars `"stash"`,
  `"--force"`, `"--force-with-lease"`, `"--all"`, `"--mirror"` and
  `"rebase"` as argv literals.
- A push timeout is `uncertain` and is resolved by exactly one read-only
  `ls-remote`; the push is never retried. On success the reported
  `remote_commit_after` is the full local sha, not git's abbreviated
  porcelain range.

**Testing**: 91 tests, 10 consecutive clean runs; ruff and black clean.
Log at `artifacts/logs/TASK-3081-pytest.log`.

**Deviations from spec**: none, with two recorded test-level judgement calls:

1. The task's test sketch clones the bare remote and commits directly. That
   silently pushes `master`, because `git init --bare` leaves HEAD at
   `refs/heads/master` while the fixture only ever pushes `dev` — the clone
   lands on an unborn branch. Tests use a `_clone_on_dev` helper that checks
   out `dev` explicitly. The `bare_remote` fixture itself was left untouched,
   since `conftest.py` belongs to TASK-3080's file scope.
2. `../outside.py` is rejected as `invalid_path` (the `..` shape check) rather
   than `path_outside_root`; the shape check runs first and is the stricter
   of the two. `path_outside_root` remains covered by `test_policy.py`.
