---
type: feature
base_branch: dev
projects: [sdd]
tags: [testing, worktree, sdd-tooling, tech-debt]
docs:
  policy: none
---

# Feature Specification: Close the FEAT-806 §4 Test Gaps in `test_worktree_sync.py`

**Feature ID**: FEAT-820
**Date**: 2026-11-06
**Author**: /sdd-fix (agent:sdd-fix:b5e88ee1)
**Status**: approved
**Target version**: 2.1.2

**Discovered-from**: `issue:87804bdfe153`

---

## 1. Motivation & Business Requirements

### Problem Statement

`issue:87804bdfe153` (major, `tech_debt`, from the FEAT-806 code review) records that
`tests/sdd_scripts/test_worktree_sync.py` does not cover several rows of the FEAT-806
spec's §4 Test Specification. `worktree_sync.py` is the only tool that mutates a feature
worktree's history from inside a sandbox; its refusal codes (2/3/4/5/6) and its
"never pushes, never resets" guarantees are safety properties, and the ones listed below
are currently asserted by no test at all.

Each limb of the ledger issue was re-verified against `dev` at `0054bf8623` before this
spec was written (FEAT-814 / TASK-5220 and TASK-5229 have already landed follow-up tests
in the same file, so two limbs are stale):

| Ledger limb | State on `dev` @ `0054bf8623` | Action |
|---|---|---|
| `test_orphan_and_mismatched_git_root_refused` missing; `resolve_target` only tested with `_git` monkeypatched | **Confirmed** — the file never calls `worktree_sync.resolve_target` | M1 |
| `resolve_base_branch` index-header / brief-frontmatter paths untested | **Confirmed** — only the hotfix-slug refusal path is covered (`test_hotfix_slug_candidates_handle_hyphenated_keys`) | M1 |
| `test_never_pushes` for host modes missing | **Confirmed** — `_refs(origin)` is compared only inside the two `test_native_policy_*` tests, which skip without `PARROT_TEST_REAL_LLM=1` | M2 |
| live-process refusal (exit 4) and own-ancestry exclusion untested | **Confirmed** — `EXIT_LIVE` and `own_ancestry` appear nowhere in the file | M2 |
| `stale_base_summary` "up to date" case missing | **Confirmed** — the string `up to date` appears nowhere; only the "1 commit(s) ahead" and sandbox-skip branches are covered | M2 |
| push-protection "missing extension" / "extra push URLs" variants missing | **Confirmed** — only the all-missing case (`test_sandbox_push_protection_refuses_before_gh`); `push_protection_ok` is never called directly | M3 |
| direct sandbox gh-failure test missing | **Confirmed** — no stub `gh` that exits non-zero | M3 |
| `test_abort_failure_is_not_reported_as_restored` missing | **Partially stale** — `test_rollback_status_error_is_reported_as_exit_6` covers `_rollback` in isolation when `_status` raises, but no test drives `sync()` through `_integration_failure`'s `error` branch with a *failing abort command*, which is the behaviour the acceptance criterion names | M4 |
| `main()` / `--json` exit-code mapping untested | **Partially stale** — the two refusal paths are covered (`EXIT_TRANSPORT` JSON, `EXIT_TARGET` human/stderr); the success (exit 0) and conflict (exit 6) mappings, and `--dry-run`/`--base` plumbing, are not | M4 |
| `test_sandbox_push_protection_required_including_dry_run` ends with a vacuous `stub.stat().st_size > 0` | **Stale — already fixed on `dev`** | none (recorded in §8) |
| Native gates skipped without `PARROT_TEST_REAL_LLM=1`, so TASK-5212 is unvalidated | **Confirmed, but by design** — `_native_cli()` skips with an `UNVALIDATED REQUIRED GATE:` message, which is exactly what FEAT-806 §4 demands | Non-goal (§1) |

### Goals

- Cover every FEAT-806 §4 row that is genuinely untested, using the file's existing
  real-temp-git style (bare `origin`, real `primary`, real linked worktree) — no new
  mocking framework and no monkeypatching of `_git` to fake Git behaviour.
- Assert the two global safety invariants directly: **no mode ever pushes** and **no
  failure path leaves an unverified rollback reported as success**.
- Leave the file's existing tests untouched except for appended sections.

### Non-Goals (explicitly out of scope)

- Changing `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py`. This feature adds
  tests only. If a new test proves a real defect, it is recorded as a new ledger issue and
  the test is marked `xfail` with that issue id — never "fixed" by weakening the assertion.
- Making the native-sandbox gates (`test_native_policy_*`, TASK-5212) run without
  `PARROT_TEST_REAL_LLM=1`. FEAT-806 §4 explicitly requires that an unavailable native
  backend be reported as an unvalidated gate, never substituted. The existing skip
  messages already say `UNVALIDATED REQUIRED GATE: …`; they stay as they are.
- Touching `tests/sdd_scripts/test_sync_process_exclusions.py` or any other test module.

---

## 2. Architectural Design

### Overview

One file grows by four appended sections, one per module, each introduced by a banner
comment in the file's existing style (`# --- FEAT-820 / TASK-<NNN>: <topic> ---`). All
four reuse the module-level helpers that already exist (`_repository`, `_run`,
`_configure_sandbox`, `_install_gh_stub`, `_patch_response`, `_refs`, `_refs_except`), and
add at most the two new helpers named in §2 "New Public Interfaces".

Because `resolve_target` and `check_guards` reach the real process table and the real
`git worktree list` of whatever repository the *current working directory* belongs to,
M1 and M2 must retarget `remove_worktree`'s cached root. That is the one mechanism this
feature introduces and it is specified exactly below so no task has to invent it.

### Component Diagram

```
tests/sdd_scripts/test_worktree_sync.py
  ├── M1 target & base resolution ──→ worktree_sync.resolve_target / resolve_base_branch
  ├── M2 guards, pushes, advisory ──→ worktree_sync.check_guards / sync / stale_base_summary
  ├── M3 sandbox transport        ──→ worktree_sync.push_protection_ok / sync (sandbox)
  └── M4 failure classification   ──→ worktree_sync._integration_failure / main
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `worktree_sync` | calls | system under test; imported already at `test_worktree_sync.py:14` |
| `remove_worktree._ROOT` | monkeypatched | module-global cache behind `discover()`; must be reset per test |
| `_repository(tmp_path)` | reuses | returns `(origin, primary, feature)` with branch `feat-FEAT-999-sync` |
| `_install_gh_stub(...)` | reuses/extends | M3 needs a failing variant (see §2 New Public Interfaces) |

### Data Models

No new models. The tests assert against the existing `worktree_sync.SyncResult` fields
(`status`, `exit_code`, `before`, `after`, `commits`, `conflicts`, `message`,
`base_branch`, `mode`, `transport`, `dry_run`) and the `worktree_sync.SyncError`
(`exit_code`, message).

### New Public Interfaces

Two module-private test helpers, appended next to the existing helper block:

```python
# tests/sdd_scripts/test_worktree_sync.py
def _as_primary(monkeypatch: pytest.MonkeyPatch, primary: Path) -> None:
    """Point remove_worktree's cached repo root and the process cwd at a disposable clone.

    ``discover()`` runs ``git worktree list`` with ``cwd=_root()`` and reads
    ``_root()/.claude/worktrees`` for orphans; ``_root()`` memoises into the module global
    ``remove_worktree._ROOT``. Both are redirected so ``resolve_target`` sees only the
    disposable repository's worktrees.
    """


def _install_failing_gh_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    """Put a gh on PATH that writes ``message`` to stderr and exits 1 for every invocation."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: target & base resolution | yes | helper `_as_primary` specified verbatim; test names and assertions fixed in §4 | — |
| M2: guards, never-pushes, advisory | yes | `subprocess.Popen` sleep fixture and `_refs` snapshot comparison fixed in §4 | — |
| M3: sandbox transport variants | yes | `_install_failing_gh_stub` specified; `push_protection_ok` truth table fixed in §4 | — |
| M4: failure classification & CLI | yes | monkeypatch target (`worktree_sync._git`) and `capsys` JSON assertions fixed in §4 | — |

### Module 1: Target and base-branch resolution coverage
- **Path**: `tests/sdd_scripts/test_worktree_sync.py` (append)
- **Responsibility**: Cover `resolve_target` (single/ambiguous/primary/orphan/mismatched
  Git top-level) and `resolve_base_branch` (per-spec index header, brief frontmatter,
  `--base` override precedence) against a real disposable repository, and prove the
  primary checkout is untouched by a refused resolution.
- **Depends on**: existing `_repository`, new `_as_primary`.
- **Interface Skeleton**:
  ```python
  # tests/sdd_scripts/test_worktree_sync.py  (appends after line 833)
  def _as_primary(monkeypatch: pytest.MonkeyPatch, primary: Path) -> None:
      """Redirect remove_worktree._ROOT and the cwd at a disposable primary clone."""

  def test_resolve_target_feat_id_and_ambiguity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
      """A unique FEAT id resolves; two substring matches and the primary are refused with exit 2."""

  def test_orphan_and_mismatched_git_root_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
      """Unregistered orphan and Git-top-level mismatch exit 2 with the primary unchanged."""

  def test_base_branch_from_index_and_brief(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
      """Index header, brief frontmatter and the --base override resolve in that precedence."""
  ```

### Module 2: Guards, never-pushes and the stale-base advisory
- **Path**: `tests/sdd_scripts/test_worktree_sync.py` (append)
- **Responsibility**: Cover `check_guards`' live-process refusal (exit 4) and its
  own-ancestry exclusion, the dirty-tree refusal reached through `sync()` on the host, the
  `stale_base_summary` "up to date" branch, and the global "no mode ever pushes"
  invariant across host merge, host `--ff-only`, host cherry-pick, dry-run and sandbox
  cherry-pick.
- **Depends on**: existing `_repository`, `_refs`, `_configure_sandbox`, `_install_gh_stub`,
  `_patch_response`; M1's `_as_primary` for the ancestry test.
- **Interface Skeleton**:
  ```python
  # tests/sdd_scripts/test_worktree_sync.py
  def test_live_process_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
      """A foreign process whose cwd is inside the worktree refuses with exit 4, tree unchanged."""

  def test_own_ancestry_not_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
      """A caller whose own cwd is the worktree is excluded from live_processes_in and syncs."""

  def test_never_pushes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
      """The bare origin's refs are byte-identical after every host and sandbox mode."""

  def test_stale_base_summary_up_to_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
      """With no new base commits the advisory reads 'base dev: up to date' and lists nothing."""
  ```

### Module 3: Sandbox push-protection variants and gh failure
- **Path**: `tests/sdd_scripts/test_worktree_sync.py` (append)
- **Responsibility**: Exercise `push_protection_ok`'s truth table directly (extension off /
  absent, no push URL, exactly `no_push`, `no_push` plus an extra effective push URL) and
  prove each refusing variant exits 5 before any `gh` call, in both normal and `--dry-run`
  mode, with no configuration written. Cover a `gh` that exits non-zero.
- **Depends on**: existing `_repository`, `_configure_sandbox`, `_install_gh_stub`,
  `_patch_response`, `_git_control_paths`; new `_install_failing_gh_stub`.
- **Interface Skeleton**:
  ```python
  # tests/sdd_scripts/test_worktree_sync.py
  def _install_failing_gh_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str) -> None:
      """Install a PATH-local gh that exits 1 with ``message`` on stderr."""

  @pytest.mark.parametrize("variant", ["missing-extension", "missing-pushurl", "extra-pushurl"])
  @pytest.mark.parametrize("dry_run", [False, True])
  def test_sandbox_push_protection_required(
      tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str, dry_run: bool
  ) -> None:
      """Each incomplete protection variant exits 5 before gh, including dry-run, writing no config."""

  def test_push_protection_ok_truth_table(tmp_path: Path) -> None:
      """push_protection_ok is True only for extension=true and exactly one no_push effective URL."""

  def test_sandbox_gh_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
      """A gh stub exiting 1 yields exit 5 with the host hint and an unchanged worktree."""
  ```

### Module 4: Failure classification and CLI exit-code mapping
- **Path**: `tests/sdd_scripts/test_worktree_sync.py` (append)
- **Responsibility**: Drive `sync()` through `_integration_failure`'s third branch — an
  integration that really started and whose `--abort` fails — and assert `status == "error"`
  with recovery guidance, not `"conflict"`; prove no destructive reset was issued. Cover
  `main()`'s exit-code mapping for success and conflict in both human and `--json` form,
  and the `--base` / `--dry-run` plumbing.
- **Depends on**: existing `_repository`, `_run`; M1's `_as_primary` (`main()` calls
  `resolve_target`).
- **Interface Skeleton**:
  ```python
  # tests/sdd_scripts/test_worktree_sync.py
  def test_abort_failure_is_not_reported_as_restored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
      """A failing merge --abort yields status 'error' with guidance, never 'conflict'."""

  def test_main_exit_code_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
      """main() maps synced→0 and conflict→6, in human and --json form, honouring --base/--dry-run."""
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_resolve_target_feat_id_and_ambiguity` | M1 | In a disposable primary with two worktrees whose branches both contain `sync`, the exact branch name resolves to one path; the ambiguous substring raises `SyncError(EXIT_TARGET)` whose message lists both paths; the primary checkout's own name raises `SyncError(EXIT_TARGET)` with "registered non-primary linked worktree" |
| `test_orphan_and_mismatched_git_root_refused` | M1 | (a) a bare directory created under `<primary>/.claude/worktrees/orphan-dir` resolves to an unregistered `Worktree` and raises `EXIT_TARGET`; (b) a registered worktree whose path is replaced by a *different* independent git repo (same basename) raises `EXIT_TARGET` with "Git top-level does not match". Both assert the primary's `HEAD`, `git status --porcelain`, `_refs(primary)` and `config --list` are byte-identical before and after |
| `test_base_branch_from_index_and_brief` | M1 | In the `feat-FEAT-999-sync` worktree, committing `sdd/tasks/index/sync.json` with `{"base_branch": "staging", …}` makes `resolve_base_branch(feature, None) == "staging"`; for a `fix-ABC-1-widget` worktree a committed `sdd/briefs/widget.brief.md` with `base_branch: main` resolves to `main`; `resolve_base_branch(feature, "dev") == "dev"` proves the override wins over the index |
| `test_live_process_refused` | M1/M2 | `subprocess.Popen(["sleep", "30"], cwd=feature)` from a *non-ancestor* process → `sync()` raises `SyncError` with `exit_code == EXIT_LIVE`; HEAD and `status --porcelain` unchanged; the child is terminated in a `finally` |
| `test_own_ancestry_not_flagged` | M2 | With the test process' own cwd set to the worktree (`monkeypatch.chdir(feature)`), `check_guards(feature)` returns without raising and `worktree_sync.own_ancestry()` contains `os.getpid()`; a full host `sync()` from that cwd still reports `synced` |
| `test_never_pushes` | M2 | Snapshot `_refs(origin)` once, then run, in order: host merge, host `--ff-only`, host cherry-pick, host `--dry-run`, and a sandbox `--cherry-pick` via the gh stub. After each, assert `_refs(origin)` equals the snapshot exactly |
| `test_stale_base_summary_up_to_date` | M2 | With `origin/dev` at the worktree's own tip, `stale_base_summary(feature, "dev") == "base dev: up to date"`; HEAD and porcelain unchanged |
| `test_push_protection_ok_truth_table` | M3 | `push_protection_ok` is `False` with no config at all, `False` with `extensions.worktreeConfig` unset but `--worktree remote.origin.pushurl=no_push` written to common config, `False` with the extension true and no push URL, `False` with the extension true and `["no_push", "git@github.com:example/sync.git"]`, and `True` only for extension true + exactly `["no_push"]` |
| `test_sandbox_push_protection_required` | M3 | Parametrized over `{missing-extension, missing-pushurl, extra-pushurl} × {dry_run False, True}`: each raises `SyncError(EXIT_TRANSPORT)` containing "host-provisioned"; the gh on PATH is `_install_failing_gh_stub`, so reaching it would fail differently — the refusal message proves it was not reached; `_git_control_paths(feature)` mtimes and contents are unchanged |
| `test_sandbox_gh_failure` | M3 | Host protection configured, `_install_failing_gh_stub(…, "gh: HTTP 403")` on PATH → `SyncError(EXIT_TRANSPORT)` whose message contains both `403` and "run 'parrot sdd worktree sync-base <target>' from the host"; HEAD, porcelain and `_refs(feature)` unchanged |
| `test_abort_failure_is_not_reported_as_restored` | M4 | Build the conflicting-merge fixture of `test_conflict_aborts_and_restores_head`, then wrap `worktree_sync._git` so that `("merge", "--abort")` returns `CompletedProcess(returncode=1, stderr="abort refused")` while every other call passes through. `sync()` returns `status == "error"`, `exit_code == EXIT_CONFLICT`, message contains "automatic rollback was not verified" and "abort refused"; assert no `reset` was ever passed to `_git` (record every invocation) |
| `test_main_exit_code_mapping` | M4 | Through `_as_primary`, call `main([<branch name>])` after pushing a new base commit → returns `EXIT_OK`, message on stdout, stderr empty; `main([<branch>, "--json"])` on the conflicting fixture → returns `EXIT_CONFLICT` and the parsed JSON has `status == "conflict"`, `exit_code == 6`, non-empty `conflicts`; `main([<branch>, "--dry-run", "--base", "dev", "--json"])` reports `dry_run is True` with HEAD unchanged |

### Integration Tests

None. This feature adds no production code and no new integration surface. The existing
`packages/ai-parrot/tests/sdd/test_sdd_cli.py` and `test_sdd_launch.py` gates stay in the
Validation Contract because they import the same module and must not regress.

### Validation Contract

tests:
- tests/sdd_scripts/test_worktree_sync.py
- tests/sdd_scripts/test_sync_process_exclusions.py
- packages/ai-parrot/tests/sdd/test_sdd_cli.py
- packages/ai-parrot/tests/sdd/test_sdd_launch.py
markers: none

### Test Data / Fixtures

Reuses the module's existing `_repository(tmp_path)` factory verbatim (bare `origin.git`,
`primary` clone on branch `dev`, linked `feature` worktree on `feat-FEAT-999-sync`). No
`conftest.py` changes and no new pytest fixtures.

---

## 5. Acceptance Criteria

- [ ] Every test named in §4 exists in `tests/sdd_scripts/test_worktree_sync.py` and passes.
- [ ] `resolve_target` is exercised against a real `git worktree list` — no test in this
      feature monkeypatches `worktree_sync._git` to fake target resolution.
- [ ] A refused `resolve_target` leaves the disposable primary's HEAD, index, working tree,
      refs and config unchanged, asserted explicitly.
- [ ] `test_never_pushes` compares the bare origin's full ref snapshot after host merge,
      host `--ff-only`, host cherry-pick, host dry-run and a sandbox cherry-pick.
- [ ] The live-process refusal (exit 4) and the own-ancestry exclusion are both asserted,
      and every spawned helper process is terminated even when the test fails.
- [ ] `push_protection_ok` is asserted for all five configuration shapes in §4, and each
      refusing shape is shown to exit 5 before `gh`, in normal and dry-run mode, with no
      configuration written.
- [ ] A failing abort is reported as `status == "error"` with recovery guidance — never as
      `"conflict"` — and the test proves no `git reset` was issued.
- [ ] `main()` success (0) and conflict (6) mappings are asserted in human and `--json` form.
- [ ] `tests/sdd_scripts/test_worktree_sync.py` contains no test that passes only because an
      assertion is vacuous (no bare truthiness on a file size, length or existence as the
      final assertion of a test).
- [ ] `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` is unchanged by this feature
      (`git diff origin/dev...HEAD -- packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py`
      is empty).
- [ ] The existing `test_native_policy_*` gates still skip with their `UNVALIDATED REQUIRED GATE:`
      message when `PARROT_TEST_REAL_LLM` is unset — this feature does not weaken them.
- [ ] Validation Contract tests pass; `ruff check` clean on the touched file.

---

## 6. Codebase Contract

> Verified against `dev` at `0054bf8623` (2026-11-06).

### Verified Imports

```python
from parrot.sdd.scripts import native_claude_sandbox, worktree_sync  # verified: tests/sdd_scripts/test_worktree_sync.py:14
from parrot.sdd.scripts import remove_worktree                        # verified: packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:1
from parrot.sdd.scripts.remove_worktree import _match, discover, live_processes_in  # verified: worktree_sync.py:18
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py
EXIT_OK, EXIT_TARGET, EXIT_DIRTY, EXIT_LIVE, EXIT_TRANSPORT, EXIT_CONFLICT = 0, 2, 3, 4, 5, 6  # line 24
BACKEND_ENV: str                                     # imported line 17 from native_claude_sandbox
class SyncError(Exception):                          # line 51 — attribute: exit_code: int
class SyncResult(BaseModel):                         # line 59
def _git(wt: Path, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:  # line 77
def own_ancestry() -> set[int]:                      # line 135
def resolve_target(target: str) -> Path:             # line 151
def resolve_base_branch(wt: Path, override: str | None) -> str:  # line 189
def check_guards(wt: Path) -> None:                  # line 218
def owner_repo(wt: Path) -> str:                     # line 245
def _rollback(wt: Path, before: str, command: str) -> tuple[bool, list[str], str]:  # line 328
def _integration_failure(wt, base, mode, before, commits, abort_command, git_error="") -> SyncResult:  # line 341
def push_protection_ok(wt: Path) -> bool:            # line 402
def sync(...) -> SyncResult:                         # line 524
def stale_base_summary(wt: Path, base: str | None = None) -> str:  # line 616
def main(argv: Sequence[str] | None = None) -> int:  # line 650

# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
_ROOT: Path | None                                   # module global, memoised by _root()
def repo_root() -> Path:                             # line 53
def _root() -> Path:                                 # line 63
def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:  # line 71 — cwd defaults to _root()
@dataclass class Worktree:                           # line 77 — path, branch, registered, primary, live_processes
def live_processes_in(path: Path, exclude_pids: Collection[int] = ()) -> list[tuple[int, str]]:  # line 164
def discover() -> list[Worktree]:                    # line 191 — scans _root()/".claude"/"worktrees" for orphans
def _match(worktrees: list[Worktree], target: str) -> list[Worktree]:  # line 269

# tests/sdd_scripts/test_worktree_sync.py (existing helpers, reuse verbatim)
def _run(path: Path, *args: str) -> str:                              # line 20
def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:           # line 25 — (origin, primary, feature)
def _configure_sandbox(feature: Path) -> None:                        # line 43
def _install_gh_stub(tmp_path, monkeypatch, responses, compare=None) -> None:  # line 50
def _patch_response(primary: Path, sha: str) -> tuple[dict[str, object], str]:  # line 88
def _refs_except(path: Path, excluded: str) -> str:                   # line 172
def _git_control_paths(feature: Path) -> tuple[Path, Path]:           # line 177
def _refs(path: Path) -> str:                                         # line 184
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_as_primary` | `remove_worktree._ROOT` | `monkeypatch.setattr(remove_worktree, "_ROOT", primary)` + `monkeypatch.chdir(primary)` | `remove_worktree.py:63-68` |
| `test_resolve_target_*` | `worktree_sync.resolve_target` | direct call | `worktree_sync.py:151` |
| `test_live_process_refused` | `worktree_sync.check_guards` via `sync()` | `live_processes_in(wt, exclude_pids=own_ancestry())` | `worktree_sync.py:239` |
| `test_sandbox_push_protection_required` | `worktree_sync._check_sandbox_push_protection` | reached from `sync()` under `BACKEND_ENV` | `worktree_sync.py:410` |
| `test_abort_failure_*` | `worktree_sync._integration_failure` error branch | wrapped `worktree_sync._git` | `worktree_sync.py:391-396` |

### Does NOT Exist (Anti-Hallucination)

- ~~`worktree_sync.push_protection_enable()`~~ — provisioning lives in the CLI, not this module.
- ~~`worktree_sync.FORCE_LIVE`~~ / ~~`--force-live`~~ — FEAT-806 forbids a live-process override.
- ~~`remove_worktree.set_root()`~~ — there is no setter; `_ROOT` is set by `main()` or memoised by `_root()`.
- ~~`tests/sdd_scripts/conftest.py`~~ — this directory has no conftest; do not create one.
- ~~`worktree_sync.sync(..., force=...)`~~ — `sync()` takes `cherry_picks`, `ff_only`, `dry_run` only.
- ~~a `pytest.ini` marker named `sandbox`~~ — the file uses no custom markers.

### Edit Sites (Blueprint Anchors)

> Verified against: `0054bf8623`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY (append at EOF) | last three lines of the file (the one-line form occurs twice — anchor on this block): <br>`    assert raised.value.exit_code == worktree_sync.EXIT_DIRTY`<br>`    assert not (feature / "base.txt").exists()`<br>`<EOF>` | `test_worktree_sync.py:832-833` | 1 (as a block; the single line alone: 2) |
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY (helper block) | `def _refs(path: Path) -> str:` | `test_worktree_sync.py:184` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Real temp Git repositories, never a mocked `git`. The only legitimate monkeypatching in
  this feature is: `BACKEND_ENV` (sandbox toggle), `PATH` (gh stub), `remove_worktree._ROOT`
  / `chdir` (target discovery), and the single deliberate `_git` wrapper in
  `test_abort_failure_is_not_reported_as_restored` — which must pass every other call
  through to the real function.
- Every test ends on a behavioural assertion. A final assertion that only checks a file
  exists, is non-empty, or has `st_size > 0` is the exact defect this feature closes —
  do not write one.
- Google-style one-line docstring on every test, 120-column lines, `ruff check --fix`
  on the touched file before committing.
- Banner comments in the file's established style, e.g.
  `# --- FEAT-820 / TASK-<NNN>: target and base-branch resolution ---`.

### Known Risks / Gotchas

- **`remove_worktree._ROOT` leaks between tests.** It is a module global; `monkeypatch.setattr`
  restores it, but a test that calls `discover()` *without* `_as_primary` will memoise the
  real repository root and poison later tests in the same process. Every test that touches
  `resolve_target` or `main()` must call `_as_primary` first.
- **`_install_gh_stub` narrows `PATH` to `<tmp>:/usr/bin`.** Anything the test needs after
  that call (including `git`, if it is not in `/usr/bin`) must already be resolved. The
  module captures `_HOST_PATH` at import (line 17) for exactly this reason — reuse it
  rather than reconstructing a PATH.
- **Live-process tests are timing-sensitive.** `live_processes_in` reads `/proc/<pid>/cwd`;
  spawn with `subprocess.Popen(cwd=feature)` and poll until the child's `/proc/<pid>/cwd`
  resolves to the worktree before asserting, with a bounded wait. Always `terminate()` and
  `wait()` in a `finally`.
- **`own_ancestry` is Linux-only** (walks `/proc/<pid>/stat`). The existing suite is already
  Linux-only for the same reason; do not add a skipif that would silently drop coverage in CI.
- **The ledger issue is partly stale.** Two limbs are already fixed on `dev` (see the §1
  table). Do not "re-fix" them and do not delete the FEAT-814 tests that fixed them.
- **Worktree validation needs an absolute `PYTHONPATH`.** Run the tests from the worktree as
  `PYTHONPATH=<worktree>/packages/ai-parrot/src pytest tests/sdd_scripts/test_worktree_sync.py`
  — a bare `pytest` imports the main checkout's `parrot`.

### External Dependencies

None. `pytest` and `pytest-asyncio` are already declared.

---

## 8. Open Questions

- [x] Is the "vacuous `stub.stat().st_size > 0`" limb still real? — **No.** Verified absent from
      `tests/sdd_scripts/test_worktree_sync.py` at `0054bf8623`; FEAT-814 replaced that test with
      `test_sandbox_push_protection_refuses_before_gh`. Recorded, no work.
- [x] Should this feature make the native gates run unattended? — **No.** FEAT-806 §4 requires an
      unavailable native backend to be reported as an unvalidated gate; TASK-5212 stays
      unvalidated until someone runs with `PARROT_TEST_REAL_LLM=1`. Out of scope (§1 Non-Goals).
- [ ] If a new test uncovers a real `worktree_sync` defect, it is filed as a new ledger issue and
      marked `xfail(strict=True)` citing that id, rather than fixed here — *Owner: implementer*.

---

## 9. Design Research Cross-Check

> Status: skipped (test-only tech-debt closure against an already-approved spec's §4 table;
> the design is FEAT-806's, not new).

---

## 10. Documentation

- **Policy**: `none` — test-only feature, no public surface change.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-06 | /sdd-fix | Initial draft from `issue:87804bdfe153`, every limb re-verified against `dev` @ `0054bf8623` |
