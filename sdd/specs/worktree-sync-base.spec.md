---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd, worktree, sandbox, git, cli]
---

# Feature Specification: Worktree Sync Base

**Feature ID**: FEAT-806
**Date**: 2026-11-05
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.0.x

---

## 1. Motivation & Business Requirements

### Problem Statement

A feature worktree is cut once from `origin/<base_branch>` and never refreshed. When a fix lands on
`dev` after the cut (typical case: a ledger fix the running feature needs), there is no sanctioned
way to bring it into the worktree:

- From **inside** the sandboxed `sdd-worker`, `git fetch` fails (`Please make sure you have the correct
  access rights…`): the remote is `git@github.com:phenobarbital/ai-parrot.git` (SSH) and the native
  sandbox carries no raw SSH, and by the operator decision recorded in brief
  `sdd/briefs/sdd-worker-gh-only-sandbox.brief.md` (merged PRs #1946/#1947) the worker reaches GitHub
  **only through `gh`**, never raw `git` against `github.com`.
- From the **host**, the operator improvises `git -C <wt> fetch && merge`, with no guard against a live
  worker editing the same tree, against a dirty tree, or against rebasing.

### Goals
- One encapsulated command, `parrot sdd worktree sync-base <target>`, that brings `origin/<base_branch>`
  (or selected commits of it) into an SDD worktree.
- Works **from outside the worktree** (primary checkout, host): worktrees share the common `.git`, so the
  fetch updates `origin/<base>` for all of them and the integration targets the worktree via `git -C`.
- Works **from inside the sandbox** using only `gh` (patch transport), honouring the gh-only decision.
- Safe by construction: clean tree required, refuse a live worker, merge never rebase, abort on conflict,
  never push.

### Non-Goals (explicitly out of scope)
- Opening `github.com` (HTTPS or SSH) to the sandbox — rejected: contradicts the gh-only decision.
- Rebasing the feature branch onto the base.
- Pushing anything, from any context.
- Syncing several worktrees in one call (one target per invocation).
- Any override of the live-process guard (`--force-live` or similar), even for `--ff-only`: a fast-forward
  still rewrites tracked files under a running worker, so it is refused exactly like `remove` (Q2, closed).
- Auto-syncing on start: `/sdd-start` and `parrot sdd launch worker` only *warn* about a stale base
  (M5); integration always needs an explicit `sync-base` call by the operator.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:a32e381ccddd9f23d7e152dc47ad1c93de21f1127aececd62bdbecf74c573f27 evaluation_digest=sha256:1f3002e23a5fc567da387eb7c39bd4cd247cb2484f3b6972ebbb8be048baa1bf rules_version=1 status=pass -->

No eligible decisions govern subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools

## 2. Architectural Design

### Overview

```
parrot sdd worktree sync-base <FEAT-ID|KEY|name|path> [--cherry-pick SHA ...] [--ff-only] [--dry-run]
```

1. **Resolve** the target with `remove_worktree.discover()` + `_match()` (same semantics as
   `parrot sdd worktree remove`). Zero or >1 matches → exit 2 with the candidates. The primary checkout is
   refused. `FEAT-<NNN>` targets match the `feat-FEAT-<NNN>-` name prefix.
   Discovery also returns orphan directories: require `registered=True`, a non-primary linked
   worktree, and a successful `git -C <wt> rev-parse --show-toplevel` whose canonical path equals
   the target. Otherwise exit 2 before any fetch, config write or integration. Never let Git's
   parent-directory discovery turn an orphan target into an operation on the primary checkout.
2. **Base branch**: from the worktree's per-spec index header (`worktree_status._read_worktree_index`);
   for brief worktrees (`hotfix-*` / `fix-*`) from the brief frontmatter `base_branch`; `--base` overrides.
3. **Guards** (before touching anything):
   - working tree clean (`git status --porcelain` empty) — else exit 3, list files;
   - no live process inside the worktree other than the caller's own process ancestry — else exit 4,
     listing pid + cmdline. **No override flag in v1** (same stance as `remove`).
4. **Transport** — chosen automatically:
   - **host** (`PARROT_SDD_SANDBOX_BACKEND` unset): `git -C <wt> fetch origin <base>` (SSH works on the
     host). For `--cherry-pick`, the SHAs must be reachable from the fetched `origin/<base>`.
   - **sandbox** (`PARROT_SDD_SANDBOX_BACKEND` set): no `git fetch`. Only `--cherry-pick` is supported;
     download every requested SHA as a patch with
     `gh api repos/<owner>/<repo>/commits/<sha> -H "Accept: application/vnd.github.patch"`.
     Before changing HEAD or the index, complete all downloads and validate that each requested commit
     is a non-merge commit with a usable patch. Store patches in temporary storage outside the target
     working tree, preserving request order. A failed download or validation exits 5 without applying
     any patch. The patch transport rewrites SHAs (so does `cherry-pick` on the host; the rewrite is a
     property of cherry-picking, not of the transport — Q1, accepted). To leave the same trace as
     `cherry-pick -x`, rewrite each downloaded patch before applying it: insert a blank line plus
     `(cherry picked from commit <sha>)` immediately before the first body line that starts with `---`
     (the same separator heuristic `git mailinfo` uses, so `git am` keeps the trailer in the message).
     Apply the entire ordered batch in one `git am -3 <patch1> <patch2> ...` invocation;
     separate per-SHA `git am` sessions are forbidden because abort cannot roll back earlier sessions.
     A full-base merge requested in the sandbox fails with exit 5 and the message
     `full base sync needs git objects — run 'parrot sdd worktree sync-base <target>' from the host`.
     `gh` failures (no token, domain not allowed) exit 5 with the same host hint.
5. **Integrate**:
   - default (host): `git -C <wt> merge --no-edit origin/<base>`; `--ff-only` → `merge --ff-only`.
   - `--cherry-pick` (host): `git -C <wt> cherry-pick -x <sha>...`.
   - Never `rebase`.
6. **Conflict**: `merge --abort` / `cherry-pick --abort` / `am --abort`, the tree is left exactly at the
   pre-sync HEAD, exit 6 with the conflicting paths. Capture conflicts before aborting, check that
   abort succeeds, and verify HEAD, index and working tree restoration before reporting a clean abort.
   The sandbox batch is one transaction, including when a later patch conflicts after earlier patches
   applied successfully. Never claim restoration if abort or verification fails; report an error
   with the actual state and recovery guidance. Do not use a destructive reset as a fallback.
7. **`--dry-run`**: performs the fetch (host) and prints the commits that would enter
   (`git log --oneline HEAD..origin/<base>`, or the SHAs + subjects for cherry-pick); changes nothing in
   the worktree. Because nothing in the worktree changes, dry-run skips the dirty/live guards of step 3
   (the sandbox prerequisite check of step 8 still applies), which is what lets M5 run it as an advisory
   before a worker starts.
8. **Never push.** Push protection is a trusted-host prerequisite for sandbox sync, not a sandbox
   write. Before launching the sandbox, the operator enables `extensions.worktreeConfig=true` in
   the common Git config and sets `git -C <wt> config --worktree remote.origin.pushurl no_push`.
   Document this host setup in M4, including Git's required migration of any common `core.worktree`
   or `core.bare` settings before enabling worktree-specific configuration. Preserve sibling
   worktrees' effective configuration; never set the common `remote.origin.pushurl`.
   Inside the sandbox, verify that the extension is enabled and the effective push URL list is
   exactly `no_push` before downloading or integrating patches (also for `--dry-run`). Missing or
   inconsistent protection exits 5 with host setup instructions and no changes. Never write either
   common Git config or `config.worktree` from the sandbox, and keep native policy deny rules intact.
9. Output: human summary by default, `--json` emits a `SyncResult`.

Exit codes: `0` synced or already up to date · `2` target unresolved/ambiguous/primary/orphan/invalid · `3` dirty ·
`4` live process · `5` transport or sandbox prerequisite unavailable · `6` integration failed
(status `conflict` only after verified restoration; otherwise status `error` with recovery guidance).

### Component Diagram
```
parrot sdd worktree sync-base ──→ worktree_sync.main
        │
        ├─ resolve ──→ remove_worktree.discover/_match
        ├─ base    ──→ worktree_status._read_worktree_index | brief frontmatter
        ├─ guards  ──→ git status --porcelain · remove_worktree.live_processes_in(exclude ancestry)
        ├─ transport: HostGit (git fetch) | SandboxGh (gh api … patch)
        └─ integrate: merge | merge --ff-only | cherry-pick -x | git am -3  (abort on conflict)

/sdd-start (step 3) · parrot sdd launch worker ──→ worktree_sync.stale_base_summary (dry-run, advisory, host only)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.sdd.cli.VERBS["worktree"]` | extends | new verb `sync-base` → module `worktree_sync` |
| `remove_worktree.discover` / `_match` | uses | target resolution, identical semantics to `remove` |
| `remove_worktree.live_processes_in` | modifies | new keyword `exclude_pids` so an in-sandbox call does not flag its own ancestry |
| `worktree_status._read_worktree_index` | uses | base branch from the per-spec index |
| `native_claude_sandbox.BACKEND_ENV` | uses | sandbox detection |
| `sdd-worker` agent instructions (+ twins) | modifies | "need a base fix? `sync-base --cherry-pick`; never `git fetch`" |
| `worktree-management` rule (+ twins) | modifies | §4 documents `sync-base` |
| `feature_launcher.launch` (`parrot sdd launch worker`) | modifies | after `prepare_upstream`, prints the stale-base advisory (M5); never blocks the launch |
| `/sdd-start` command (+ twins) | modifies | step 3, after `cd "$WT"`: run `sync-base --dry-run` and show the result as a warning (M5) |

### Data Models
```python
class SyncResult(BaseModel):
    worktree: str
    branch: str | None
    base_branch: str
    transport: Literal["host-git", "sandbox-gh"]
    mode: Literal["merge", "ff-only", "cherry-pick"]
    dry_run: bool
    before: str            # HEAD sha before
    after: str             # HEAD sha after (== before on dry-run / abort)
    commits: list[str]     # "<sha> <subject>" that entered (or would enter)
    status: Literal["synced", "up-to-date", "refused", "conflict", "error"]
    exit_code: int
    message: str
    conflicts: list[str] = []
```

### New Public Interfaces
CLI only: `parrot sdd worktree sync-base`. Module API in §3.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: worktree_sync core | yes | §2 steps 1–9, exit codes, `SyncResult` | — |
| M2: live-process ancestry exclusion | yes | `exclude_pids` kwarg, default empty → behaviour unchanged | — |
| M3: CLI verb | yes | one `VERBS` entry | — |
| M4: docs / agent instructions + twins | yes | text in §2; twins per `sdd-worker-prompt-two-suites` | — |
| M5: stale-base advisory | yes | `stale_base_summary()` contract below; one `print` in the launcher; one paragraph in `/sdd-start` + twins | — |

### Module 1: worktree_sync core
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` (new)
- **Responsibility**: resolve, guard, transport, integrate, report (§2).
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py  (new)
  from parrot.sdd.scripts.remove_worktree import discover, _match, live_processes_in  # verified: remove_worktree.py:191,269,163
  from parrot.sdd.scripts.worktree_status import _read_worktree_index  # verified: worktree_status.py:135

  EXIT_OK, EXIT_TARGET, EXIT_DIRTY, EXIT_LIVE, EXIT_TRANSPORT, EXIT_CONFLICT = 0, 2, 3, 4, 5, 6

  class SyncResult(BaseModel): ...  # §2 Data Models

  def in_sandbox() -> bool:
      """True when PARROT_SDD_SANDBOX_BACKEND is set (native_claude_sandbox.BACKEND_ENV)."""

  def own_ancestry() -> set[int]:
      """PIDs of this process and all its ancestors (walk /proc/<pid>/stat ppid)."""

  def resolve_target(target: str) -> Path:
      """Require one registered non-primary linked worktree with matching Git top-level; otherwise EXIT_TARGET."""

  def resolve_base_branch(wt: Path, override: str | None) -> str:
      """override > per-spec index header > brief frontmatter > 'dev'."""

  def check_guards(wt: Path) -> None:
      """Raise SyncError(EXIT_DIRTY | EXIT_LIVE) when the tree is dirty or a foreign live process is inside."""

  def owner_repo(wt: Path) -> str:
      """'<owner>/<repo>' parsed from `git remote get-url origin` (SSH or HTTPS form)."""

  def sync(wt: Path, base: str, *, cherry_picks: Sequence[str] = (), ff_only: bool = False,
           dry_run: bool = False) -> SyncResult:
      """Run transport + integration; report conflict only after verified rollback, otherwise error."""

  def stale_base_summary(wt: Path, base: str | None = None) -> str:
      """Advisory one-liner for M5: run a host dry-run and return
      'base <base>: N commit(s) ahead of this worktree — run `parrot sdd worktree sync-base <name>` from the host'
      or 'base <base>: up to date'. Never raises: any SyncError (sandbox, transport, unresolved target) becomes
      'stale-base check skipped: <reason>'."""

  def main(argv: Sequence[str] | None = None) -> int:
      """argparse entry: target, --base, --cherry-pick (repeatable), --ff-only, --dry-run, --json."""
  ```

### Module 2: live-process ancestry exclusion
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` (modify)
- **Responsibility**: let callers exclude PIDs. Today the docstring claims parents are skipped but the code
  skips only `os.getpid()` (`remove_worktree.py:178-180`), so an in-worktree call flags its own shell/claude.
- **Interface Skeleton**:
  ```python
  def live_processes_in(path: Path, exclude_pids: Collection[int] = ()) -> list[tuple[int, str]]:  # verified: remove_worktree.py:163
      """… PIDs in ``exclude_pids`` (and own PID) are skipped. Default keeps current behaviour."""
  ```

### Module 3: CLI verb
- **Path**: `packages/ai-parrot/src/parrot/sdd/cli.py` (modify)
- **Interface Skeleton**:
  ```python
  # inside VERBS["worktree"]  # verified: cli.py:238
  "sync-base": ("worktree_sync", (), "Bring origin/<base_branch> (or chosen commits) into a worktree; never pushes."),
  ```

### Module 4: docs and agent instructions
- **Paths**: `.claude/rules/worktree-management.md` §4 + twin `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md`
  and `.agent/skills/worktree-management/SKILL.md`; `.claude/agents/sdd-worker.md` + `_assets/claude/agents/sdd-worker.md`
  (+ `.codex/agents/sdd-worker.toml` and its `_assets` twin) — one paragraph: to pull a base fix use
  `parrot sdd worktree sync-base <FEAT> --cherry-pick <sha>`; never `git fetch`/`pull`; a full base sync is the operator's job on the host.
  New `docs/sdd/worktree-sync-base.md` with usage, exit codes, trusted-host push-protection setup,
  and sandbox prerequisite refusal/recovery instructions. Worker instructions must send missing
  prerequisites to the host operator, never advise changing protected Git config inside the sandbox.

---

### Module 5: stale-base advisory
- **Paths**: `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` (modify);
  `.claude/commands/sdd-start.md` + twins `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md`
  and `.agent/workflows/sdd-start.md` (modify).
- **Responsibility**: both entry points run on the host *before* any sandbox exists, so a full-base dry-run
  (host `git fetch`) is possible there and only there. They print the advisory and continue; they never
  integrate. Inside the sandbox the worker makes no stale-base check (a full-base dry-run would exit 5).
- **Depends on**: M1 (`stale_base_summary`).
- **Interface Skeleton**:
  ```python
  # feature_launcher.py — right after the existing `print(prepare_upstream(worktree), file=sys.stderr)`  # verified: feature_launcher.py:507
      if not no_upstream:
          print(prepare_upstream(worktree), file=sys.stderr)
          print(stale_base_summary(worktree), file=sys.stderr)   # advisory; cannot raise
  ```
  ```bash
  # sdd-start.md step 3, right after `cd "$WT"` (+ twins)
  parrot sdd worktree sync-base "$WT" --dry-run || true   # advisory only: a stale base is a warning, never a stop
  ```
  The `/sdd-start` paragraph tells the agent to surface the dry-run output to the user verbatim and carry on;
  if the base is behind, suggest `parrot sdd worktree sync-base <FEAT-ID>` from the host **before** the
  worker starts (once a worker is live the guard of step 3 refuses the sync).

## 4. Test Specification

### Unit Tests (`tests/sdd_scripts/test_worktree_sync.py`, real temp git repos, bare repo as `origin`)
| Test | Module | Description |
|---|---|---|
| `test_resolve_target_feat_id_and_ambiguity` | M1 | `FEAT-<NNN>` resolves; two matches → exit 2; primary refused |
| `test_orphan_and_mismatched_git_root_refused` | M1 | orphan inside primary and target with mismatched Git top-level → exit 2 before mutation; primary HEAD, index, files, refs and config unchanged |
| `test_base_branch_from_index_and_brief` | M1 | index header, brief frontmatter, `--base` override |
| `test_dirty_tree_refused` | M1 | exit 3, nothing changed |
| `test_live_process_refused` | M1/M2 | a `sleep` with cwd in the worktree → exit 4 |
| `test_own_ancestry_not_flagged` | M2 | caller running inside the worktree is not reported |
| `test_host_merge_from_outside` | M1 | run with cwd = primary checkout; new base commit lands in the worktree via merge |
| `test_host_ff_only_and_up_to_date` | M1 | ff-only success; second run → `up-to-date`, exit 0 |
| `test_conflict_aborts_and_restores_head` | M1 | exit 6, HEAD == before, tree clean, conflicts listed |
| `test_cherry_pick_host` | M1 | `-x` trailer present |
| `test_dry_run_changes_nothing` | M1 | commits listed, HEAD unchanged |
| `test_sandbox_full_sync_refused` | M1 | env set, no `--cherry-pick` → exit 5 with host hint, no git fetch invoked |
| `test_sandbox_cherry_pick_via_gh_patch` | M1 | host preconfigures push protection; stubbed `gh` patches apply in one `git am -3` batch; config remains unchanged; each applied commit message ends with `(cherry picked from commit <original sha>)` |
| `test_patch_trailer_insertion` | M1 | trailer goes before the first `---` body line; a body containing `---` inside a code block is cut exactly where `git mailinfo` cuts it |
| `test_stale_base_summary` | M1/M5 | behind → "N commit(s) ahead" line with the host hint; up to date → "up to date"; sandbox env / unresolved target → "skipped: …" and no exception |
| `test_sandbox_push_protection_required` | M1 | missing extension, missing push URL or additional effective push URLs → exit 5 before download/integration, including dry-run; no config writes |
| `test_sandbox_second_patch_conflict_restores_batch` | M1 | first patch applies, second conflicts; one `am --abort` restores pre-sync HEAD, index and tree with no am state remaining |
| `test_sandbox_late_download_or_validation_failure` | M1 | second patch download or validation fails → exit 5; no patch applied and HEAD, index and tree unchanged |
| `test_abort_failure_is_not_reported_as_restored` | M1 | abort/verification failure → status error, actual state and recovery guidance; no destructive reset |
| `test_sandbox_gh_failure` | M1 | stub `gh` exits 1 → exit 5 |
| `test_never_pushes` | M1 | the bare origin's refs are unchanged after every mode |
| `test_owner_repo_parsing` | M1 | SSH and HTTPS remote forms |

### Integration Tests
| Test | Description |
|---|---|
| `tests/sdd_scripts/test_sdd_cli.py` (extended) | `parrot sdd worktree sync-base --help` dispatches to `worktree_sync.main` |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (extended) | `launch()` prints the stale-base advisory after `prepare_upstream`; a "skipped" result still launches; `--no-upstream` skips it |
| `tests/sdd_scripts/test_worktree_sync.py` (native sandbox integration) | launch under actual native filesystem policy with host-provisioned protection and stubbed gh; sync succeeds without config writes; common config and own config.worktree remain protected; missing protection refuses unchanged. An unavailable native backend must be reported as an unvalidated gate, not a passing substitute using only the environment variable. |

### Validation Contract

tests:
- tests/sdd_scripts/test_worktree_sync.py
- tests/sdd_scripts/test_sdd_cli.py
- packages/ai-parrot/tests/sdd/test_sdd_launch.py
markers: none

---

## 5. Acceptance Criteria

- [ ] `parrot sdd worktree sync-base <FEAT-ID>` run from the primary checkout merges new `origin/<base>` commits into the feature worktree.
- [ ] Orphan, unregistered and Git top-level-mismatched targets exit 2 before mutation; the primary checkout remains unchanged.
- [ ] Dirty worktree → exit 3; foreign live process inside → exit 4; neither path modifies the worktree.
- [ ] An in-worktree caller never flags its own process ancestry.
- [ ] Conflicts abort cleanly: exit 6, HEAD and tree identical to before.
- [ ] Sandbox multi-patch sync is atomic: a later conflict rolls back the whole batch; a late download/validation failure applies nothing. Failed rollback is reported as an error, never a successful restoration.
- [ ] Inside the sandbox the command never invokes `git fetch`/`git pull`/`git push`; it reaches GitHub only through `gh`.
- [ ] Inside the sandbox, a full-base sync is refused with exit 5 and the host hint; `--cherry-pick` works via `gh api … patch` + `git am -3`, and every applied commit carries the `(cherry picked from commit <sha>)` trailer.
- [ ] No live-process override exists in any mode (`--force-live` is not a flag).
- [ ] `parrot sdd launch worker` and `/sdd-start` (+ twins) print the stale-base advisory on the host and continue; neither integrates anything, and the worker never runs a stale-base check inside the sandbox.
- [ ] No mode ever pushes; the host provisions worktree-local push protection and the sandbox verifies it without config writes. Missing protection exits 5 unchanged, including dry-run.
- [ ] The native sandbox integration gate proves successful sync with protected config files; existing deny rules remain intact.
- [ ] Never uses `rebase`.
- [ ] `live_processes_in` default behaviour is unchanged for `parrot sdd worktree list/remove`.
- [ ] Worker instructions, worktree-management rule and their twins document the command; `docs/sdd/worktree-sync-base.md` exists.
- [ ] Validation Contract tests pass; `ruff check` clean on touched files.

---

## 6. Codebase Contract

Verified against: `b9c9259a68`

### Verified Imports
```python
from parrot.sdd.scripts.remove_worktree import discover, _match, live_processes_in  # remove_worktree.py:191,269,163
from parrot.sdd.scripts.worktree_status import _read_worktree_index  # worktree_status.py:135
from parrot.sdd.scripts.native_claude_sandbox import BACKEND_ENV  # native_claude_sandbox.py:31 (== "PARROT_SDD_SANDBOX_BACKEND")
from parrot.sdd.scripts.sdd_meta import WORKTREE_ROOT  # re-export of knowledge/wiki/ledger/sdd_meta.py:379 (".claude/worktrees")
from parrot.flows.dev_loop.feature_launcher import launch, prepare_upstream  # feature_launcher.py:253 (prepare_upstream), launch() calls it at :507
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
def live_processes_in(path: Path) -> list[tuple[int, str]]:            # line 163 — skips only os.getpid()
def discover() -> list[Worktree]:                                     # line 191 — hardcodes _root()/".claude"/"worktrees" for orphans
def _match(worktrees: list[Worktree], target: str) -> list[Worktree]: # line 269 — exact name/branch, path, then substring
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py
def _read_worktree_index(wt_path: Path, slug: str) -> tuple[list[WorktreeTaskStatus], str]:  # line 135 — base defaults "dev"
# packages/ai-parrot/src/parrot/sdd/cli.py
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]]  # line 237; worktree group line 238; dispatch imports f"{_HELPER_PACKAGE}.{module}".main (line 322)
```

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot sdd worktree sync` / `sync-base`~~ — no such verb today.
- ~~any `gh`-based git object transport~~ — none; `gh repo sync` syncs forks server-side, not local refs.
- ~~parent-PID skipping in `live_processes_in`~~ — the docstring claims it; the code does not do it.
- ~~github.com in the sandbox allowlist~~ — deliberately absent (gh-only decision).

### Edit Sites (Blueprint Anchors)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | MODIFY | `def live_processes_in(path: Path) -> list[tuple[int, str]]:` | `remove_worktree.py:163` | 1 |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `"remove": (` (inside `"worktree": {`) | `cli.py:249` | 1 |
| `tests/sdd_scripts/test_worktree_sync.py` | CREATE | — | — | — |
| `tests/sdd_scripts/test_sdd_cli.py` | MODIFY | (unverified — check before use) | — | — |
| `.claude/rules/worktree-management.md` + twins | MODIFY | `## 4. Work inside` | — | 1 |
| `.claude/agents/sdd-worker.md` + twins | MODIFY | (unverified — locate the push/sync paragraph) | — | — |
| `docs/sdd/worktree-sync-base.md` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | `print(prepare_upstream(worktree), file=sys.stderr)` | `feature_launcher.py:507` | 1 |
| `.claude/commands/sdd-start.md` + twins (`_assets/claude/commands/`, `.agent/workflows/`) | MODIFY | `cd "$WT"` | step 3 of each twin | 1 per file |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | `monkeypatch.setattr(launcher, "prepare_upstream", lambda path: "launch-worker: ready")` | `test_sdd_launch.py:172,230` | 2 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `remove_worktree.py`: `subprocess` git calls with explicit `cwd`/`-C`, argparse `main(argv)`.
- Pass the worktree path explicitly everywhere (memory: heredoc/cwd escapes the worktree).
- Pydantic v2 for `SyncResult`; `logging`, no `print` except the CLI summary writer (match `remove_worktree`).

### Known Risks / Gotchas
- **FEAT-802 hard-cuts `.claude/worktrees` → `.parrot/worktrees`.** Use `WORKTREE_ROOT` / `discover()`,
  never a literal path, so whichever lands second needs no change here.
- **Patch transport rewrites SHAs**: `git am` creates new commits, exactly as host `cherry-pick` does. The
  `(cherry picked from commit <sha>)` trailer (Q1) keeps the provenance; when the feature later merges into
  `dev` git recognises identical patches in most cases, with a residual risk of a trivial conflict.
- **Stale-base advisory must never block**: `stale_base_summary` swallows every `SyncError`; a broken `gh`,
  an unreachable origin or an in-sandbox call degrade to a "skipped" line, never a launch failure.
- **`gh api …/commits/<sha>` patch omits merge commits** — cherry-picking a merge SHA in the sandbox must be
  refused (exit 5, "merge commits need the host transport").
- **Race with a live worker** is why there is no override; the guard is checked immediately before integrating.
- **Sandbox needs `GH_TOKEN` + `api.github.com`** — provided by the gh-only brief (PRs #1946/#1947); without
  them the command exits 5 with the host hint.
- Native sandbox policy denies common `config`, `config.lock` and the worktree's `config.worktree`
  (`native_claude_sandbox._denied_write_paths`). Host setup must complete before launch; sync only reads
  protection settings. Enabling `extensions.worktreeConfig` requires preserving existing Git configuration semantics.

### External Dependencies
None (git, `gh` CLI already required).

---

## Decisions

```yaml
schema_version: 1
document_id: worktree-sync-base
entries:
  - id: sandbox-sync-gh-only
    statement: In-sandbox worktree sync reaches GitHub only through the gh CLI (patch transport); it never runs git fetch, pull or push.
    relation: constrains
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/sdd/cli.py]
    contradicts: []
    supersedes: []
    rationale: Honours the operator decision of brief sdd-worker-gh-only-sandbox.
    rejected_alternatives: ["allow github.com HTTPS in the sandbox and fetch with gh auth git-credential"]
  - id: sync-never-rebases-never-pushes
    statement: worktree sync integrates with merge, cherry-pick or git am only, and never pushes.
    relation: forbids
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/sdd/cli.py]
    contradicts: []
    supersedes: []
    rationale: Avoid-rebase-on-dev policy; pushing stays a host /sdd-done act.
    rejected_alternatives: []
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:a32e381ccddd9f23d7e152dc47ad1c93de21f1127aececd62bdbecf74c573f27 evaluation_digest=sha256:1f3002e23a5fc567da387eb7c39bd4cd247cb2484f3b6972ebbb8be048baa1bf rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `possible-supersession` [advisory]; waived_by: not recorded; participants: adr:spec:worktree-sync-base#sandbox-sync-gh-only@1, adr:spec:worktree-sync-base#sync-never-rebases-never-pushes@1; scope: file:packages/ai-parrot/src/parrot/sdd/cli.py; message: adr:spec:worktree-sync-base#sandbox-sync-gh-only and adr:spec:worktree-sync-base#sync-never-rebases-never-pushes share targets and about without an explicit link
- `potential-conflict` [advisory]; waived_by: not recorded; participants: adr:spec:worktree-sync-base#sandbox-sync-gh-only@1, adr:spec:worktree-sync-base#sync-never-rebases-never-pushes@1; scope: file:packages/ai-parrot/src/parrot/sdd/cli.py; message: adr:spec:worktree-sync-base#sandbox-sync-gh-only (constrains) and adr:spec:worktree-sync-base#sync-never-rebases-never-pushes (forbids) govern overlapping scope

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: cli, git, sandbox, worktree
- Targets resolved: 1/1
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 1,
    "targets_total": 1,
    "unmapped_tags": [
      "cli",
      "git",
      "sandbox",
      "worktree"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:1f3002e23a5fc567da387eb7c39bd4cd247cb2484f3b6972ebbb8be048baa1bf",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:1f4bf2e12b869ce66ca4fa0d8cf9f0eca2f436b26b303c2629187999cd8c8a11",
      "kind": "possible-supersession",
      "message": "adr:spec:worktree-sync-base#sandbox-sync-gh-only and adr:spec:worktree-sync-base#sync-never-rebases-never-pushes share targets and about without an explicit link",
      "participants": [
        {
          "decision_id": "adr:spec:worktree-sync-base#sandbox-sync-gh-only",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:worktree-sync-base#sync-never-rebases-never-pushes",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/sdd/cli.py"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:477c95bee5ec48ff7d56247370f95cd852feb66c56173dade994d55f18c2b12f",
      "kind": "potential-conflict",
      "message": "adr:spec:worktree-sync-base#sandbox-sync-gh-only (constrains) and adr:spec:worktree-sync-base#sync-never-rebases-never-pushes (forbids) govern overlapping scope",
      "participants": [
        {
          "decision_id": "adr:spec:worktree-sync-base#sandbox-sync-gh-only",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:worktree-sync-base#sync-never-rebases-never-pushes",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/sdd/cli.py"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:a32e381ccddd9f23d7e152dc47ad1c93de21f1127aececd62bdbecf74c573f27",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:4a74694320eb2977955f758d6eb0a4d1f9ea3a6e2fbdd22f566204ba6055a485",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Q1: Is the SHA rewrite of the sandbox patch transport acceptable, or should the sandbox path stay host-only too (exit 5 always)? — *Owner: Jesus* — **Resolved 2026-11-05: accepted.** The rewrite is inherent to cherry-picking (host `cherry-pick` rewrites too); the sandbox transport inserts the `(cherry picked from commit <sha>)` trailer into each patch before `git am` so both transports leave the same trace (§2 step 4, §7).
- [x] Q2: Should a future `--force-live` allow a fast-forward-only sync while a worker is live? v1 says no. — *Owner: Jesus* — **Resolved 2026-11-05: no, closed as a non-goal.** A fast-forward still rewrites tracked files under a live worker; same stance as `remove`, no override flag now or planned (§1 Non-Goals).
- [x] Q3: Should `/sdd-start` / `sdd-worker` call `sync-base --dry-run` at start to warn about a stale base? — *Owner: Jesus* — **Resolved 2026-11-05: yes, host-only and advisory.** `/sdd-start` (step 3) and `parrot sdd launch worker` run the dry-run on the host and print a warning, never integrate; the worker makes no check inside the sandbox because a full-base dry-run cannot fetch there (new M5).

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec seeded from inline notes)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- Isolation: one feature worktree `feat-FEAT-806-worktree-sync-base`; the sdd-coder engine gives each task a sub-worktree.
- Module graph: M1 → M2 (`live_processes_in(exclude_pids=…)`); M3 → M1 (module name); M5 → M1 (`stale_base_summary`); M4 independent.
- Shared files: none between modules (M5 touches `sdd-start.md` twins; M4 touches `worktree-management` / `sdd-worker` twins — disjoint files).
- Exclusive resources: none.
- Cross-feature: FEAT-802 (worktree root move) — no ordering required if `WORKTREE_ROOT`/`discover()` are used.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-05 | Jesus Lara / Claude | Initial draft from inline notes; sandbox transport changed to gh patch per gh-only decision |
| 0.2 | 2026-11-05 | Codex | Resolve review issues fbd638a5a750, 1f5e830f5221 and 95434c288bdb: validate linked targets, provision push protection on host, and require atomic patch batches with native-policy and rollback regression coverage |
| 0.3 | 2026-11-05 | Jesus Lara / Claude | Resolve Q1–Q3: sandbox patches carry the `(cherry picked from commit)` trailer; `--force-live` closed as non-goal; new M5 host-only stale-base advisory in `/sdd-start` and `parrot sdd launch worker` |
