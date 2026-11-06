# TASK-5236: Cover live-process guards, the never-pushes invariant and the up-to-date advisory

**Feature**: FEAT-820 — Close the FEAT-806 §4 Test Gaps in `test_worktree_sync.py`
**Spec**: `sdd/specs/fixgroup-d188effba3ca.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5235
**Assigned-to**: unassigned

**Discovered-from**: `issue:87804bdfe153`

---

## Context

Spec §3 Module 2. Three gaps recorded by `issue:87804bdfe153` and re-verified against
`dev` at `0054bf8623`:

- `EXIT_LIVE` and `own_ancestry` appear **nowhere** in `tests/sdd_scripts/test_worktree_sync.py`,
  so `check_guards`' exit-4 refusal (`worktree_sync.py:239-242`) and its own-ancestry exclusion
  are untested. FEAT-806 made the absence of a live-process override a hard acceptance criterion;
  nothing currently proves the guard fires at all.
- The bare origin's refs are compared only inside `test_native_policy_sync_with_protected_config`
  and `test_native_policy_missing_protection_refuses`, both of which **skip** without
  `PARROT_TEST_REAL_LLM=1`. So in a normal CI run nothing asserts the FEAT-806 invariant
  "no mode ever pushes".
- `stale_base_summary`'s up-to-date branch (`worktree_sync.py:628`) is uncovered — the string
  `up to date` does not occur in the test file. Only the "N commit(s) ahead" and sandbox-skip
  branches are tested, by `test_stale_base_summary`.

---

## Scope

- Add `test_live_process_refused`.
- Add `test_own_ancestry_not_flagged`.
- Add `test_never_pushes`.
- Add `test_stale_base_summary_up_to_date`.
- Append all four at the end of the file under a FEAT-820 banner comment.

**NOT in scope**:
- Any change to `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` (spec §1 Non-Goals).
- Editing the existing `test_stale_base_summary` — the new test is additive; the ahead and
  sandbox-skip branches stay where they are.
- Sandbox push-protection variants and `gh` failure (TASK-5237).
- `main()` exit-code mapping (TASK-5238).
- `tests/sdd_scripts/test_sync_process_exclusions.py` — a different module, untouched.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY | Append four tests at EOF |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# already present at tests/sdd_scripts/test_worktree_sync.py — do NOT re-import
import json          # line 5
import os            # line 6
import subprocess    # line 8
from pathlib import Path   # line 10
import pytest              # line 12
from parrot.sdd.scripts import native_claude_sandbox, worktree_sync  # line 14
from parrot.sdd.scripts import remove_worktree  # added by TASK-5235
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py
EXIT_OK, EXIT_TARGET, EXIT_DIRTY, EXIT_LIVE, EXIT_TRANSPORT, EXIT_CONFLICT = 0, 2, 3, 4, 5, 6  # line 24
BACKEND_ENV: str                                     # imported line 17 from native_claude_sandbox
class SyncError(Exception):                          # line 51 — attribute: exit_code: int
class SyncResult(BaseModel):                         # line 59 — status, exit_code, before, after, commits, conflicts, message, base_branch, mode, transport, dry_run
def own_ancestry() -> set[int]:                      # line 135 — walks /proc/<pid>/stat, Linux-only
def check_guards(wt: Path) -> None:                  # line 218
def sync(wt, base, *, cherry_picks=..., ff_only=..., dry_run=...) -> SyncResult:  # line 524
def stale_base_summary(wt: Path, base: str | None = None) -> str:  # line 616

# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
def live_processes_in(path: Path, exclude_pids: Collection[int] = ()) -> list[tuple[int, str]]:  # line 164

# tests/sdd_scripts/test_worktree_sync.py (existing helpers — reuse verbatim)
def _run(path: Path, *args: str) -> str:                          # line 20
def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:       # line 25 — (origin, primary, feature)
def _configure_sandbox(feature: Path) -> None:                    # line 43
def _install_gh_stub(tmp_path, monkeypatch, responses, compare=None) -> None:  # line 50
def _patch_response(primary: Path, sha: str) -> tuple[dict[str, object], str]:  # line 88
def _refs(path: Path) -> str:                                     # line 184
def _as_primary(monkeypatch: pytest.MonkeyPatch, primary: Path) -> None:  # added by TASK-5235
```

Behaviour verified in the source and relied on by this task:

- `check_guards` calls `live_processes_in(wt, exclude_pids=own_ancestry())` and raises
  `SyncError(EXIT_LIVE, "live process(es) inside target worktree:\n…")` when the list is
  non-empty (`worktree_sync.py:239-242`).
- `live_processes_in` resolves each `/proc/<pid>/cwd` and counts a process as inside when its
  cwd is the worktree or a descendant (`remove_worktree.py:164-189`). It also always skips
  `os.getpid()` itself; ancestors are skipped only because `check_guards` passes
  `own_ancestry()`.
- `stale_base_summary` returns `f"base {result.base_branch}: up to date"` when the dry-run
  result lists no commits (`worktree_sync.py:628`), and
  `f"base {…}: {len(...)} commit(s) ahead of this worktree — run \`parrot sdd worktree sync-base <name>\` from the host"`
  otherwise (`worktree_sync.py:623-627`).
- `_install_gh_stub` narrows `PATH` to `f"{tmp_path}:/usr/bin"` (`test_worktree_sync.py:86`), so
  it must be the **last** PATH-affecting call in a test. The module captures the untouched host
  PATH as `_HOST_PATH` at line 17 for anything that needs it afterwards.
- The existing sandbox cherry-pick recipe is `test_sandbox_cherry_pick_via_gh_patch`
  (`test_worktree_sync.py:248-265`): `_configure_sandbox(feature)`, commit in `primary`,
  `_install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)})`,
  `monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")`, then
  `worktree_sync.sync(feature, "dev", cherry_picks=[sha])`.

### Does NOT Exist

- ~~`worktree_sync.FORCE_LIVE`~~ / ~~`--force-live`~~ / ~~`sync(..., force=...)`~~ — FEAT-806
  forbids any live-process override. `sync()` takes `cherry_picks`, `ff_only`, `dry_run` only.
- ~~`worktree_sync.live_processes_in`~~ — it is imported into the module namespace from
  `remove_worktree` (`worktree_sync.py:18`); reference it as
  `remove_worktree.live_processes_in` or `worktree_sync.live_processes_in`, both resolve, but
  do not claim it is *defined* in `worktree_sync`.
- ~~`stale_base_summary(wt)` raising~~ — it never raises; it returns a `"stale-base check skipped: …"`
  string on any `SyncError`/`OSError`/`SubprocessError` (`worktree_sync.py:620-621`).
- ~~a `psutil` dependency~~ — ancestry and cwd detection read `/proc` directly.
- ~~`pytest.mark.skipif(sys.platform …)` anywhere in this file~~ — the suite is already
  Linux-only; do not add one, it would silently drop this coverage in CI.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "tests/sdd_scripts/test_worktree_sync.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#check_guards",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#own_ancestry",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#stale_base_summary",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#live_processes_in"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

`test_host_merge_from_outside` (`test_worktree_sync.py:189`) for the host-mode setup, and
`test_sandbox_cherry_pick_via_gh_patch` (`:248`) for the sandbox leg of `test_never_pushes`.

### Key Constraints

- **Process hygiene**: every spawned helper must be terminated in a `finally`, even when an
  assertion fails, or the pytest process leaves orphans behind and later tests in the same temp
  tree see a phantom live process.
- **Timing**: `live_processes_in` reads `/proc/<pid>/cwd`. A freshly spawned child may not have
  its cwd visible yet. Poll with a bounded deadline until `Path(f"/proc/{pid}/cwd").resolve()`
  equals the worktree before asserting; fail the test on timeout rather than sleeping blindly.
- **`own_ancestry` is the pytest process' own chain.** `test_own_ancestry_not_flagged` must not
  spawn anything — it sets the *test process'* cwd to the worktree with `monkeypatch.chdir` and
  asserts the guard stays silent.
- `test_never_pushes` must snapshot `_refs(origin)` **once** before the first mode and compare
  after **each** mode; do not re-snapshot between modes or the test proves nothing.
- Order matters inside `test_never_pushes`: run every host mode before installing the gh stub,
  because `_install_gh_stub` narrows `PATH`.
- 120-column lines, one-line Google-style docstring per test, `ruff check --fix` before committing.

### References in Codebase

- `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py:218` — `check_guards`
- `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:164` — `live_processes_in`
- `tests/sdd_scripts/test_worktree_sync.py:229` — existing `test_stale_base_summary`
- `tests/sdd_scripts/test_sync_process_exclusions.py` — prior art for exercising process exclusion

---

## Implementation Blueprint

### Steps (in order)

1. Append the banner comment and the four blocks below at the **end of the file** — *why*:
   TASK-5235 appended before you and TASK-5237 will append after; EOF is the only anchor that
   does not move under the chain.
2. Write the bounded `/proc` cwd poll helper inline in `test_live_process_refused` — *why*: it is
   needed exactly once, and a module-level helper would invite later tests to sleep instead of poll.
3. Complete every `# FILL IN:` marker.
4. Run the validation commands from the worktree with an absolute `PYTHONPATH`.

### `tests/sdd_scripts/test_worktree_sync.py` (MODIFY — append at EOF)

```python
# --- FEAT-820 / TASK-5236: live-process guards, never-pushes, up-to-date advisory ------------------


def test_live_process_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A foreign process whose cwd is inside the worktree refuses the sync with exit 4."""
    _origin, primary, feature = _repository(tmp_path)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    before = _run(feature, "rev-parse", "HEAD")

    child = subprocess.Popen(["sleep", "30"], cwd=feature)
    try:
        # FILL IN: poll Path(f"/proc/{child.pid}/cwd").resolve() == feature.resolve() with a
        #          bounded deadline (a few seconds); pytest.fail on timeout — bounded by
        #          "never sleep blindly" in Key Constraints
        with pytest.raises(worktree_sync.SyncError) as raised:
            worktree_sync.sync(feature, "dev")
        # FILL IN: assert raised.value.exit_code == worktree_sync.EXIT_LIVE and that the message
        #          names the child pid — bounded by worktree_sync.py:239-242
    finally:
        child.terminate()
        child.wait(timeout=10)

    assert _run(feature, "rev-parse", "HEAD") == before
    assert _run(feature, "status", "--porcelain") == ""
    assert not (feature / "base.txt").exists()


def test_own_ancestry_not_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller running inside the worktree is excluded from the live-process guard and syncs."""
    _origin, primary, feature = _repository(tmp_path)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    monkeypatch.chdir(feature)

    assert os.getpid() in worktree_sync.own_ancestry()
    worktree_sync.check_guards(feature)

    result = worktree_sync.sync(feature, "dev")

    # FILL IN: assert result.status == "synced", result.exit_code == EXIT_OK and base.txt landed
    #          — bounded by AC "an in-worktree caller never flags its own process ancestry"


def test_never_pushes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bare origin's refs are byte-identical after every host mode and after a sandbox patch."""
    _origin, primary, feature = _repository(tmp_path)
    origin, _p, _f = _origin, primary, feature
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    remote_before = _refs(origin)

    # FILL IN: for each host mode in order — merge, ff_only=True, cherry_picks=[<sha>],
    #          dry_run=True — create whatever base commit that mode needs in `primary`, push it
    #          to origin via `_run(primary, "push")`, run worktree_sync.sync(...), then assert
    #          _refs(origin) == remote_before. Re-snapshot remote_before ONLY after a deliberate
    #          `_run(primary, "push")`, never after a sync — bounded by AC "no mode ever pushes"

    # Sandbox leg LAST: _install_gh_stub narrows PATH for the rest of the test.
    _configure_sandbox(feature)
    # FILL IN: commit a patch in `primary`, capture its sha, _install_gh_stub(...),
    #          monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native"),
    #          worktree_sync.sync(feature, "dev", cherry_picks=[sha]), then assert
    #          _refs(origin) == <the snapshot taken after the last deliberate push>


def test_stale_base_summary_up_to_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no new base commits the advisory reads 'up to date' and changes nothing."""
    _origin, _primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    before = _run(feature, "rev-parse", "HEAD")

    summary = worktree_sync.stale_base_summary(feature, "dev")

    assert summary == "base dev: up to date"
    assert _run(feature, "rev-parse", "HEAD") == before
    assert _run(feature, "status", "--porcelain") == ""
```

**Why this shape**: the `finally` in `test_live_process_refused` is the whole point of spawning a
real process — a leaked `sleep` would make unrelated later tests fail with exit 4. The snapshot
discipline in `test_never_pushes` is what makes it a real invariant check: one snapshot, compared
after every mode, with the sandbox leg last because `_install_gh_stub` narrows `PATH`.
`test_stale_base_summary_up_to_date` asserts the exact string rather than a substring because the
advisory text is itself the contract operators read.

### FILL IN checklist

- [ ] `test_live_process_refused` — bounded `/proc/<pid>/cwd` poll; bounded by Key Constraints "never sleep blindly"
- [ ] `test_live_process_refused` — exit-4 and pid-in-message assertions; bounded by `worktree_sync.py:239-242`
- [ ] `test_own_ancestry_not_flagged` — synced-result assertions; bounded by AC "in-worktree caller never flags itself"
- [ ] `test_never_pushes` — the four host-mode legs and their per-mode ref comparison; bounded by AC "no mode ever pushes"
- [ ] `test_never_pushes` — the sandbox cherry-pick leg; bounded by `test_sandbox_cherry_pick_via_gh_patch`'s recipe

---

## Acceptance Criteria

- [ ] `test_live_process_refused`, `test_own_ancestry_not_flagged`, `test_never_pushes` and
      `test_stale_base_summary_up_to_date` exist and pass.
- [ ] The live-process test terminates its child in a `finally` and leaves no orphan process.
- [ ] `test_never_pushes` compares the bare origin's full ref snapshot after host merge, host
      `--ff-only`, host cherry-pick, host dry-run and a sandbox cherry-pick.
- [ ] `test_stale_base_summary_up_to_date` asserts the exact string `"base dev: up to date"`.
- [ ] No `skipif` marker is added to this file.
- [ ] `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` is unchanged.
- [ ] Every pre-existing test in the file still passes and none was edited.
- [ ] `ruff check tests/sdd_scripts/test_worktree_sync.py` is clean.
- [ ] No test ends on a vacuous assertion.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py::test_live_process_refused -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py::test_never_pushes -q`
- `pytest tests/sdd_scripts/test_sync_process_exclusions.py -q`

---

## Test Specification

This task *is* the test specification — see the Implementation Blueprint. Run from inside the
feature worktree with an absolute `PYTHONPATH`:

```bash
PYTHONPATH=$PWD/packages/ai-parrot/src pytest tests/sdd_scripts/test_worktree_sync.py -q
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug fixgroup-d188effba3ca --feature-id FEAT-820`)
2. **Read the spec** at `sdd/specs/fixgroup-d188effba3ca.spec.md` (§3 Module 2, §4, §6)
3. **Check dependencies** — `TASK-5235` must be `"done"` in
   `sdd/tasks/index/fixgroup-d188effba3ca.json` (it defines `_as_primary` and adds the
   `remove_worktree` import)
4. **Verify the Codebase Contract** — re-check every line number above before writing code
5. **Update status** in `sdd/tasks/index/fixgroup-d188effba3ca.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only `tests/sdd_scripts/test_worktree_sync.py`
9. **Close the task** with `parrot sdd task close TASK-5236 fixgroup-d188effba3ca verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
