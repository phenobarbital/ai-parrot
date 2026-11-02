# TASK-5109: `parrot sdd install` prepares the SDD base branch

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.11, amendment C31)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4080, TASK-4091, TASK-4299, TASK-5101 (all done)
**Assigned-to**: unassigned

---

## Context

Every SDD worktree branches from `origin/<base_branch>` (`parrot sdd worktree ensure`), but
`parrot sdd install` never looks at git. The 2026-11-03 simulation installed FEAT-633 into a fresh
project (`git init`, branch `main`, no commits, no remote): install reported success, `sdd/config.json`
was seeded with `base_branch: "dev"`, and the first `worktree ensure` / `/sdd-start` could only fail —
there was no `dev` and no `origin/dev`. The user had to make the first commit, `git branch dev`, add a
remote and push both branches by hand.

Spec rev 0.11 amendment C31 (§3 M6, "Rev 0.11 amendments C31–C33") is the normative text. In short:
create the local base branch when it is safe and cheap; only warn about everything else; push only on an
explicit flag; never touch a branch that exists.

---

## Scope

- Add a `base-branch` plan step to `plan_install()` (after `config-seed`) and run it in
  `install_sdd_integration()` after the config seed, so it sees the seeded/explicit `base_branch`.
- Implement `_base_branch_step(root, config, *, push: bool) -> list[str]` with this decision table
  (each row is one action line; warnings start with `warning:`, informational lines with `note:`):

  | Situation | Result |
  |---|---|
  | `git` not on PATH, or `root` is not a git work tree | `warning:` skip, nothing created |
  | `HEAD` unborn (no commit yet) | `warning:` "commit once, then re-run `parrot sdd install` (or `git branch <base>`)" |
  | `refs/heads/<base>` exists | `<base> — base branch present` (no change) |
  | missing, `refs/remotes/origin/<base>` exists | `git branch --track <base> origin/<base>` → `<base> — created, tracking origin/<base>` |
  | missing, no `origin/<base>` | `git branch <base> HEAD` → `<base> — created from <current branch or short sha>` |
  | no `origin` remote | `note:` "SDD worktrees branch from origin/<base>: `git remote add origin <url> && git push -u origin <base>`" |
  | `origin` exists, no local `refs/remotes/origin/<base>` | without `--push-base`: `warning:` with `git push -u origin <base>`; with it: run that push and report the result (a failed push is a `warning:`, never an exception) |
  | `staging_branch` / `hotfix_base` set and missing locally | `note:` naming the branch; never created |

- Add `base_branch: str | None = None` and `push_base: bool = False` keyword parameters to
  `install_sdd_integration()`. When `base_branch` is given:
  - validate it with `git check-ref-format --branch <name>` (invalid → `ValueError` before any write);
  - if `sdd/config.json` does not exist, the seed uses it (`default_sdd_config().model_copy(update=...)`);
  - if it exists and sets a different `base_branch`, raise `ValueError` before any write
    ("sdd/config.json already sets base_branch=<x>; edit it there").
- Add `--base-branch NAME` and `--push-base` to the `parrot sdd install` click command and pass them through.
- `--dry-run` prints `plan: base-branch <name> (<exists | create from HEAD | track origin/<name> | skip: <reason>>)`
  and runs no mutating git command (read-only `rev-parse` / `show-ref` probes are fine).
- Add `"base-branch"` to the `PlanAction` literal and its vocabulary comment.
- Record `receipt["base_branch_created"] = <name>` when this run created the branch (status only; uninstall
  does NOT delete it — say so in the uninstall action log if the key is present).
- Write `packages/ai-parrot/tests/sdd/test_installer_base_branch.py` (see Test Specification).
- Document the behaviour and both flags in `docs/getting-started.md` where `parrot sdd install` is described.

**NOT in scope**:
- Any network call (`ls-remote`, `fetch`). `doctor --sdd`'s `_check_sdd_git` stays the remote truth.
- Checking out / switching to the base branch, moving or resetting an existing branch, deleting it on uninstall.
- Creating `origin` or any remote, or creating `staging_branch` / `hotfix_base`.
- The dangerous-actions guard (TASK-5110) and the `.gitignore` block (PR #1932, amendment C33).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `base-branch` plan step, `_base_branch_step`, new `install_sdd_integration` kwargs, receipt key |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `--base-branch`, `--push-base` on `install` |
| `packages/ai-parrot/tests/sdd/test_installer_base_branch.py` | CREATE | Decision-table tests on real temp git repos |
| `docs/getting-started.md` | MODIFY | Base-branch behaviour + flags |

---

## Codebase Contract (Anti-Hallucination)

Verified on `origin/feat-FEAT-633-parrot-installer` at `b521bda1e4` (2026-11-03; includes PR #1932 / C33).

### Verified Imports
```python
from parrot.sdd.config import CONFIG_PATH, default_sdd_config, load_sdd_config  # parrot/sdd/config.py:11,88,106 (lazy, as today)
from parrot.sdd.installer import install_sdd_integration, plan_install, uninstall_sdd_integration  # tests
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/installer.py
PlanAction = Literal[...]                                   # line 74 — add "base-branch"
class PlannedAction(BaseModel): action; target: str; note   # line 102
def _empty_receipt() -> dict[str, Any]                       # line 195 — keys: schema_version, version, files, blocks, ledger_hooks
def load_receipt(root: Path) -> dict[str, Any]               # line 199
def plan_install(root: Path, hosts: Sequence[str], *, force: bool = False, hook: str = GUARD_HOOK_LINE) -> list[PlannedAction]  # line 310
    # last step today (line 345): plan.append(PlannedAction(action="config-seed", target="sdd/config.json"))
def _seed_config(root: Path) -> str                           # line 471 — writes default_sdd_config() iff absent
def install_sdd_integration(root, hosts=("claude",), *, force=False, dry_run=False, portable=False) -> list[str]  # line 627
    # config = load_sdd_config(root) runs BEFORE planning (C21: a malformed config raises before any write)
    # dispatch loop: `elif step.action == "config-seed": actions.append(_seed_config(root))`  # line 680
def uninstall_sdd_integration(root, hosts=("claude",), *, dry_run=False) -> list[str]  # line 709

# packages/ai-parrot/src/parrot/sdd/config.py
class SddConfig(BaseModel):                                   # line 19
    base_branch: str = "dev"                                  # line 24
    staging_branch: str | None = None                         # line 25
    hotfix_base: str = "main"                                 # line 26
def default_sdd_config() -> SddConfig                         # line 88
def load_sdd_config(root: Path | None = None) -> SddConfig    # line 106

# packages/ai-parrot/src/parrot/sdd/cli.py
_path_option / _host_option / _dry_run_option                 # lines 16-33
def install(path_, hosts, force, portable, dry_run) -> None   # line 74 — wraps ValueError/RuntimeError in ClickException

# packages/ai-parrot/src/parrot/self_/doctor.py — pattern for a bounded, prompt-free git call (copy, do not import)
def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]   # line 160 (timeout + GIT_TERMINAL_PROMPT=0)
def _check_sdd_git(root: Path, branch: str) -> list[DoctorCheck]       # line 206 — remote check via ls-remote
```

### Does NOT Exist
- ~~`parrot sdd install --base-branch` / `--push-base`~~ — added by this task
- ~~a git helper in `parrot.sdd.installer`~~ — there is none; add a private `_git_run(root, *args)` modelled on `doctor._git`
- ~~`receipt["base_branch_created"]`~~ — new key; `load_receipt` must tolerate its absence (older receipts)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/installer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer_base_branch.py", "action": "CREATE"},
    {"path": "docs/getting-started.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#plan_install",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_seed_config",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#uninstall_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#SddConfig",
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#default_sdd_config",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#install"
  ]
}
```

---

## Implementation Notes

- Probes: `git rev-parse --is-inside-work-tree`, `git rev-parse --verify -q HEAD` (unborn → non-zero),
  `git show-ref --verify -q refs/heads/<b>`, `git show-ref --verify -q refs/remotes/origin/<b>`,
  `git remote get-url origin`, `git symbolic-ref -q --short HEAD` (for the "created from" label).
- Every git call: `-C root`, `capture_output=True`, `timeout=20`, `env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}`,
  `OSError`/`TimeoutExpired` → a `warning:` line, never an exception out of `install`.
- The step runs for every host (git state is host-independent), once per install.
- Re-running install is idempotent: the second run reports "present" and creates nothing.
- Keep it stdlib + existing imports; no new dependency.

---

## Acceptance Criteria

- [ ] Fresh repo with one commit on `main` and no `dev`: install creates `dev` at `main`'s commit, leaves `HEAD` on `main`.
- [ ] Repo with `origin/dev` but no local `dev`: install creates `dev` tracking `origin/dev`.
- [ ] Unborn `HEAD` / not a git repo: install succeeds, prints the `warning:`, creates nothing.
- [ ] Existing local `dev` at another commit: untouched (same sha before/after).
- [ ] No `origin`: `note:` line with the exact command; `origin` without `origin/dev`: `warning:` with `git push -u origin dev`.
- [ ] `--push-base` against a local bare remote pushes `dev` and sets upstream; a failing push is a `warning:`.
- [ ] `--base-branch main` on a fresh repo seeds `"base_branch": "main"` and creates nothing new; against a config that says `dev` it fails before writing anything (repo byte-identical).
- [ ] `--dry-run` shows `plan: base-branch …` and creates no ref.
- [ ] Uninstall never deletes the base branch.
- [ ] `ruff check` clean on the touched Python files; existing `test_installer.py` / `test_sdd_cli.py` still pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer_base_branch.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_installer_base_branch.py
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.installer import install_sdd_integration, uninstall_sdd_integration


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Fresh repo on `main` with one commit and no `dev`, no remote."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    return tmp_path


def test_creates_local_base_branch_from_head(repo: Path) -> None: ...
def test_tracks_origin_base_when_present(repo: Path, tmp_path_factory) -> None: ...   # bare remote fixture
def test_unborn_head_warns_and_creates_nothing(tmp_path: Path) -> None: ...
def test_existing_branch_is_never_moved(repo: Path) -> None: ...
def test_missing_origin_is_a_note(repo: Path) -> None: ...
def test_push_base_pushes_to_bare_remote(repo: Path, tmp_path_factory) -> None: ...
def test_base_branch_flag_seeds_config(repo: Path) -> None: ...
def test_base_branch_flag_conflicting_config_refuses_before_writing(repo: Path) -> None: ...
def test_dry_run_creates_no_ref(repo: Path) -> None: ...
def test_uninstall_keeps_base_branch(repo: Path) -> None: ...
```

---

## Agent Instructions

When you pick up this task:
1. **Work in the feature worktree** — branch `feat-FEAT-633-parrot-installer` (never on `dev`)
2. **Read the spec** amendment C31 (§3 M6, "Rev 0.11 amendments C31–C33")
3. **Verify the Codebase Contract** — re-check every anchor before editing
4. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"` and commit only that file
5. **Implement**, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
6. **Commit the code** — stage only the files listed above
7. **Close the task** with `parrot sdd task close TASK-5109 parrot-installer verified`
8. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note
*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
