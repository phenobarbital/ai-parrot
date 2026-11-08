# TASK-5238: Cover the unrecovered-abort branch and `main()`'s exit-code mapping

**Feature**: FEAT-820 — Close the FEAT-806 §4 Test Gaps in `test_worktree_sync.py`
**Spec**: `sdd/specs/fixgroup-d188effba3ca.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5237
**Assigned-to**: unassigned

**Discovered-from**: `issue:87804bdfe153`

---

## Context

Spec §3 Module 4. Two gaps from `issue:87804bdfe153`, both re-verified against `dev` at
`0054bf8623`:

- **`test_abort_failure_is_not_reported_as_restored` is missing.** FEAT-806's acceptance
  criterion reads "Failed rollback is reported as an error, never a successful restoration".
  `test_rollback_status_error_is_reported_as_exit_6` (`test_worktree_sync.py:635`) covers
  `_rollback` **in isolation** when `_status` raises, but nothing drives `sync()` through
  `_integration_failure`'s third branch (`worktree_sync.py:388-396`) with a genuinely failing
  `--abort`, so the operator-facing `status == "error"` result and its recovery guidance are
  unproven — and so is the absence of a destructive reset on that path.
- **`main()`'s exit-code mapping is only half covered.** The two refusal paths are tested
  (`test_main_missing_git_is_clean_refusal` → `EXIT_TRANSPORT` JSON;
  `test_cli_refusal_goes_to_stderr` → `EXIT_TARGET` human). The success (0) and conflict (6)
  mappings, and the `--base` / `--dry-run` plumbing, are not.

This task is last in the chain because it is the only one that exercises `main()`, which calls
`resolve_target` and therefore needs `_as_primary` from TASK-5235.

---

## Scope

- Add `test_abort_failure_is_not_reported_as_restored`.
- Add `test_main_exit_code_mapping`.
- Append both at the end of the file under a FEAT-820 banner comment.

**NOT in scope**:
- Any change to `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` (spec §1 Non-Goals).
  If the abort test exposes a real defect, file a new ledger issue and mark the test
  `xfail(strict=True)` citing that id — do not weaken the assertion and do not patch the module.
- Editing `test_rollback_status_error_is_reported_as_exit_6`, `test_main_missing_git_is_clean_refusal`
  or `test_cli_refusal_goes_to_stderr` — all three stay as they are.
- argparse usage errors (exit 2 with no `--json` body) — out of scope for this feature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY | Append two tests at EOF |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# already present at tests/sdd_scripts/test_worktree_sync.py — do NOT re-import
import json          # line 5
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
def _git(wt: Path, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:  # line 77
def _rollback(wt: Path, before: str, command: str) -> tuple[bool, list[str], str]:  # line 328
def _integration_failure(wt, base, mode, before, commits, abort_command, git_error="") -> SyncResult:  # line 341
def sync(wt, base, *, cherry_picks=..., ff_only=..., dry_run=...) -> SyncResult:  # line 524
def main(argv: Sequence[str] | None = None) -> int:  # line 650
#   argparse: positional `target`; flags --base, --cherry-pick (append), --ff-only, --dry-run, --json

# tests/sdd_scripts/test_worktree_sync.py (existing helpers — reuse verbatim)
def _run(path: Path, *args: str) -> str:                          # line 20
def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:       # line 25 — feature branch is feat-FEAT-999-sync
def _as_primary(monkeypatch: pytest.MonkeyPatch, primary: Path) -> None:  # added by TASK-5235
```

Behaviour verified in the source and relied on by this task:

```python
# worktree_sync.py:378-396 — the three branches of _integration_failure
if _unchanged(wt, before):
    ...  # "refused"  — no abort attempted
restored, conflicts, detail = _rollback(wt, before, abort_command)
if restored:
    ...  # "conflict" — HEAD and tree verified restored
recovery = (
    "integration failed; automatic rollback was not verified. Inspect the worktree and run Git recovery manually."
)
if detail:
    recovery = f"{recovery} {detail}"
return _result(wt, base, mode, False, before, commits, "error", EXIT_CONFLICT, recovery, conflicts)
```

- `_rollback` runs `_git(wt, command, "--abort")` and returns
  `restored = aborted.returncode == 0 and _head(wt) == before and clean` (`worktree_sync.py:328-339`).
  Making the `("merge", "--abort")` invocation return a non-zero `CompletedProcess` is therefore
  sufficient to force the `error` branch.
- `_git` is a module-level function called as `_git(wt, *args)` throughout
  (`worktree_sync.py:77-93`), so `monkeypatch.setattr(worktree_sync, "_git", wrapper)` intercepts
  every Git call the module makes.
- `main()` prints `result.message` to **stdout** when `result.exit_code == EXIT_OK` and to
  **stderr** otherwise, then each commit on stdout and each conflict as `f"conflict: {c}"` on
  stderr; with `--json` it prints `result.model_dump_json()` only (`worktree_sync.py:665-673`).
- The conflicting-merge fixture to reuse verbatim is `test_conflict_aborts_and_restores_head`
  (`test_worktree_sync.py:206-227`): commit a change to `shared.txt` in `feature`, commit a
  different change to `shared.txt` in `primary`, `_run(primary, "push")`.
- `main()` resolves its target through `resolve_target`, so the test must call `_as_primary`
  first and pass a target string that `_match` resolves — the branch name `feat-FEAT-999-sync`
  is an exact match.

### Does NOT Exist

- ~~`worktree_sync.main(argv, root=...)`~~ — `main` takes `argv` only.
- ~~`--force` / `--no-verify` / `--abort-command` CLI flags~~ — the parser defines exactly
  `target`, `--base`, `--cherry-pick`, `--ff-only`, `--dry-run`, `--json` (`worktree_sync.py:651-658`).
- ~~`SyncResult.recovery`~~ — the guidance text lives in `SyncResult.message`.
- ~~`worktree_sync._reset()`~~ — there is no reset helper anywhere in the module; the point of the
  test is to prove `reset` is never passed to `_git` on this path.
- ~~`status == "unrecovered"`~~ — the literal status value is `"error"`.
- ~~`pytest.raises` around this `sync()` call~~ — the `error` branch **returns** a `SyncResult`;
  it does not raise.

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
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#_integration_failure",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#_rollback",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#main"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

`test_conflict_aborts_and_restores_head` (`test_worktree_sync.py:206`) for the conflicting
fixture, and `test_main_missing_git_is_clean_refusal` (`:538`) for the `capsys` + `json.loads`
assertion shape.

### Key Constraints

- The `_git` wrapper in `test_abort_failure_is_not_reported_as_restored` is the **only**
  legitimate `_git` monkeypatch in FEAT-820 (spec §7). It must:
  1. record every call's args, so the test can assert `"reset"` never appears;
  2. intercept **only** `("merge", "--abort")`, returning
     `subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="abort refused")`;
  3. delegate every other call to the captured original function.
  Capture the original **before** `setattr`, or the wrapper recurses infinitely.
- After the test, the worktree is genuinely left mid-merge (the abort was faked as failing, so
  nothing cleaned up). That is correct and expected — assert on the returned `SyncResult`, not on
  a clean tree. Do not add cleanup that would mask the behaviour.
- `main()` needs `_as_primary` first; without it `resolve_target` scans the real repository.
- Assert `result.status` and `result.message` precisely: `"error"`, and the message must contain
  both `"automatic rollback was not verified"` and the stub's `"abort refused"` detail.
- 120-column lines, one-line Google-style docstring per test, `ruff check --fix` before committing.

### References in Codebase

- `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py:341` — `_integration_failure`
- `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py:650` — `main`
- `tests/sdd_scripts/test_worktree_sync.py:635` — `test_rollback_status_error_is_reported_as_exit_6`

---

## Implementation Blueprint

### Steps (in order)

1. Append the banner comment and the two blocks below at the **end of the file** — *why*: EOF is
   the anchor the whole FEAT-820 chain uses; TASK-5237 appended just before you.
2. Build the `_git` wrapper with the original captured in a local before `setattr` — *why*: a
   wrapper that looks the function up on the module at call time calls itself forever.
3. Complete every `# FILL IN:` marker.
4. Run the validation commands from the worktree with an absolute `PYTHONPATH`.

### `tests/sdd_scripts/test_worktree_sync.py` (MODIFY — append at EOF)

```python
# --- FEAT-820 / TASK-5238: unrecovered abort and CLI exit-code mapping ----------------------------


def test_abort_failure_is_not_reported_as_restored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing merge --abort yields status 'error' with recovery guidance, never 'conflict'."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    (feature / "shared.txt").write_text("feature\n", encoding="utf-8")
    _run(feature, "add", "shared.txt")
    _run(feature, "commit", "-m", "feature change")
    before = _run(feature, "rev-parse", "HEAD")
    (primary / "shared.txt").write_text("base change\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "base change")
    _run(primary, "push")

    original_git = worktree_sync._git
    calls: list[tuple[str, ...]] = []

    def recording_git(wt: Path, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ("merge", "--abort"):
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="abort refused")
        return original_git(wt, *args, timeout=timeout)

    monkeypatch.setattr(worktree_sync, "_git", recording_git)

    result = worktree_sync.sync(feature, "dev")

    assert result.status == "error"
    assert result.exit_code == worktree_sync.EXIT_CONFLICT
    # FILL IN: assert both "automatic rollback was not verified" and "abort refused" are in
    #          result.message — bounded by worktree_sync.py:388-396
    # FILL IN: assert no recorded call starts with "reset" — bounded by AC
    #          "the test proves no git reset was issued"
    assert result.before == before


def test_main_exit_code_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() maps synced to 0 and conflict to 6, in human and --json form, honouring --dry-run."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    _as_primary(monkeypatch, primary)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")

    dry = worktree_sync.main(["feat-FEAT-999-sync", "--base", "dev", "--dry-run", "--json"])
    body = json.loads(capsys.readouterr().out)
    # FILL IN: assert dry == EXIT_OK, body["dry_run"] is True, body["commits"] is non-empty and
    #          base.txt has NOT appeared in the worktree — bounded by AC "--dry-run changes nothing"

    code = worktree_sync.main(["feat-FEAT-999-sync", "--base", "dev"])
    captured = capsys.readouterr()
    # FILL IN: assert code == EXIT_OK, the message went to stdout, stderr is empty and base.txt
    #          now exists — bounded by worktree_sync.py:669-673

    # Now make the next run conflict.
    # FILL IN: commit a divergent change to shared.txt in `feature`, a different one in `primary`,
    #          push, then call main(["feat-FEAT-999-sync", "--base", "dev", "--json"]) and assert
    #          it returns EXIT_CONFLICT with parsed status "conflict", exit_code 6 and a non-empty
    #          "conflicts" list — bounded by worktree_sync.py:382-387
```

**Why this shape**: `original_git` is captured into a local *before* `monkeypatch.setattr`, which is
the only thing standing between this test and infinite recursion. The `calls` list exists solely to
satisfy the AC "proves no `git reset` was issued" — that assertion is the reason this test is worth
more than the existing isolated `_rollback` test. In `test_main_exit_code_mapping` the dry-run leg
runs first, while the worktree is still behind, so the same base commit serves both the dry-run and
the real sync; `capsys.readouterr()` must be called after each `main()` because it drains the buffer.

### FILL IN checklist

- [ ] `test_abort_failure_is_not_reported_as_restored` — message assertions; bounded by `worktree_sync.py:388-396`
- [ ] `test_abort_failure_is_not_reported_as_restored` — no-`reset` assertion over `calls`; bounded by AC "no destructive reset"
- [ ] `test_main_exit_code_mapping` — dry-run JSON assertions; bounded by AC "--dry-run changes nothing"
- [ ] `test_main_exit_code_mapping` — success stdout/stderr assertions; bounded by `worktree_sync.py:669-673`
- [ ] `test_main_exit_code_mapping` — conflict fixture and exit-6 JSON assertions; bounded by `worktree_sync.py:382-387`

---

## Acceptance Criteria

- [ ] `test_abort_failure_is_not_reported_as_restored` and `test_main_exit_code_mapping` exist and pass.
- [ ] The abort test asserts `status == "error"` (never `"conflict"`), that the message carries both
      the recovery guidance and the abort's stderr detail, and that no `git reset` was ever issued.
- [ ] Its `_git` wrapper delegates every call other than `("merge", "--abort")` to the original.
- [ ] `main()` is asserted for exit 0 (human: message on stdout, stderr empty) and exit 6
      (`--json`: `status == "conflict"`, `exit_code == 6`, non-empty `conflicts`), plus `--dry-run`
      reporting `dry_run: true` with the worktree unchanged.
- [ ] `test_rollback_status_error_is_reported_as_exit_6`, `test_main_missing_git_is_clean_refusal`
      and `test_cli_refusal_goes_to_stderr` are unchanged.
- [ ] `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` is unchanged
      (`git diff origin/dev...HEAD -- packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` empty).
- [ ] `ruff check tests/sdd_scripts/test_worktree_sync.py` is clean.
- [ ] The whole file contains no test ending on a vacuous assertion (spec §5).

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py::test_abort_failure_is_not_reported_as_restored -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py::test_main_exit_code_mapping -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

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
2. **Read the spec** at `sdd/specs/fixgroup-d188effba3ca.spec.md` (§3 Module 4, §4, §6)
3. **Check dependencies** — `TASK-5237` must be `"done"` in
   `sdd/tasks/index/fixgroup-d188effba3ca.json`; `_as_primary` comes from `TASK-5235`
4. **Verify the Codebase Contract** — re-check every line number above before writing code
5. **Update status** in `sdd/tasks/index/fixgroup-d188effba3ca.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only `tests/sdd_scripts/test_worktree_sync.py`
9. **Close the task** with `parrot sdd task close TASK-5238 fixgroup-d188effba3ca verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: ai-parrot-85 (agent:sdd-fix:b5e88ee1)
**Date**: 2026-11-06
**Notes**: Added `_conflicting_base` plus the two tests. The `_git` wrapper captures the original
into a local before `monkeypatch.setattr` (otherwise it recurses), intercepts only
`("merge", "--abort")`, and records every call so the test can assert no `reset` was ever issued —
the assertion that makes this worth more than the existing isolated `_rollback` test. No cleanup is
added after the faked-failing abort: the worktree is genuinely left mid-merge, which is the
behaviour under test. `worktree_sync.py` untouched (`git diff origin/dev...HEAD` lists only the
test file and SDD state). Full validation contract: 146 passed, 2 skipped (native gates);
`ruff check` clean.

**Deviations from spec**: none.
