# TASK-5237: Cover the push-protection truth table and a failing `gh`

**Feature**: FEAT-820 — Close the FEAT-806 §4 Test Gaps in `test_worktree_sync.py`
**Spec**: `sdd/specs/fixgroup-d188effba3ca.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5236
**Assigned-to**: unassigned

**Discovered-from**: `issue:87804bdfe153`

---

## Context

Spec §3 Module 3. `issue:87804bdfe153` records two gaps, both re-verified against `dev`
at `0054bf8623`:

- `push_protection_ok` (`worktree_sync.py:402-408`) is never called directly by any test, and
  the only refusal covered is the all-missing case
  (`test_sandbox_push_protection_refuses_before_gh`, `test_worktree_sync.py:405`). The
  spec's "missing extension" and "extra effective push URLs" variants — the two shapes that
  look protected but are not — have no coverage, in either normal or dry-run mode.
- No test installs a `gh` that exits non-zero, so the `_gh` failure path
  (`worktree_sync.py:432-434`) and its host hint are unproven.

FEAT-806 made "the sandbox verifies host-provisioned protection without config writes" an
acceptance criterion; a protection check whose negative cases are untested is the exact kind
of safety gap this ledger issue was filed for.

---

## Scope

- Add the module-level helper `_install_failing_gh_stub(tmp_path, monkeypatch, message)`.
- Add `test_push_protection_ok_truth_table`.
- Add `test_sandbox_push_protection_required`, parametrized over the three incomplete
  protection variants × `{dry_run False, True}`.
- Add `test_sandbox_gh_failure`.
- Append all four at the end of the file under a FEAT-820 banner comment.

**NOT in scope**:
- Any change to `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` (spec §1 Non-Goals).
- Editing or deleting `test_sandbox_push_protection_refuses_before_gh` — it covers the
  all-missing case and stays as it is.
- The native-sandbox gates `test_native_policy_*` — they stay skipped without
  `PARROT_TEST_REAL_LLM=1` by design (spec §1 Non-Goals).
- `main()` exit-code mapping (TASK-5238).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY | Append one helper and three tests at EOF |

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
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py
EXIT_TRANSPORT = 5                                   # line 24
BACKEND_ENV: str                                     # imported line 17 from native_claude_sandbox
class SyncError(Exception):                          # line 51 — attribute: exit_code: int
def push_protection_ok(wt: Path) -> bool:            # line 402
def _check_sandbox_push_protection(wt: Path) -> None:  # line 410
def _gh(wt: Path, endpoint: str, *, patch: bool = False) -> str:  # line 422
def _sandbox_hint(detail: str) -> str:               # line 397
def sync(wt, base, *, cherry_picks=..., ff_only=..., dry_run=...) -> SyncResult:  # line 524

# tests/sdd_scripts/test_worktree_sync.py (existing helpers — reuse verbatim)
def _run(path: Path, *args: str) -> str:                          # line 20
def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:       # line 25
def _configure_sandbox(feature: Path) -> None:                    # line 43
def _install_gh_stub(tmp_path, monkeypatch, responses, compare=None) -> None:  # line 50
def _patch_response(primary: Path, sha: str) -> tuple[dict[str, object], str]:  # line 88
def _git_control_paths(feature: Path) -> tuple[Path, Path]:       # line 177 — (common config, config.worktree)
def _refs(path: Path) -> str:                                     # line 184
```

Behaviour verified in the source and relied on by this task:

```python
# worktree_sync.py:402-408 — the exact truth table under test
def push_protection_ok(wt: Path) -> bool:
    extension = _git(wt, "config", "--bool", "extensions.worktreeConfig")
    push_urls = _git(wt, "config", "--get-all", "remote.origin.pushurl")
    urls = [line for line in push_urls.stdout.splitlines() if line]
    return extension.returncode == 0 and extension.stdout.strip().lower() == "true" and urls == ["no_push"]
```

- `_check_sandbox_push_protection` raises `SyncError(EXIT_TRANSPORT, _sandbox_hint("sandbox patch
  sync requires host-provisioned extensions.worktreeConfig=true and exactly one effective
  remote.origin.pushurl=no_push (host: parrot sdd worktree push-protection enable <target>)"))`
  when `push_protection_ok` is false (`worktree_sync.py:410-420`). The message therefore contains
  the literal substring `host-provisioned`.
- `_sandbox_hint(detail)` returns
  `f"{detail} — run 'parrot sdd worktree sync-base <target>' from the host"` (`worktree_sync.py:397-399`).
- `_gh` raises `SyncError(EXIT_TRANSPORT, _sandbox_hint(proc.stderr.strip() or "gh patch download
  failed"))` when the subprocess returns non-zero (`worktree_sync.py:432-434`). The stub's stderr
  text therefore appears in the message.
- `_configure_sandbox(feature)` (`test_worktree_sync.py:43-48`) performs exactly three writes:
  `remote set-url origin git@github.com:example/sync.git`,
  `config extensions.worktreeConfig true`,
  `config --worktree remote.origin.pushurl no_push`. Build each incomplete variant by omitting or
  adding to these three, **not** by editing `_configure_sandbox`.
- `_install_gh_stub` narrows `PATH` to `f"{tmp_path}:/usr/bin"` (`test_worktree_sync.py:86`); the
  new failing stub must do the same so a refusal cannot be mistaken for "gh not found".

### Does NOT Exist

- ~~`worktree_sync.push_protection_enable()`~~ — provisioning lives in the CLI
  (`parrot sdd worktree push-protection enable`), not in this module. Configure the disposable
  repo with `_run(feature, "config", …)` instead.
- ~~`worktree_sync.PUSH_PROTECTION_URL`~~ / ~~`NO_PUSH`~~ — the sentinel is the bare literal
  string `"no_push"` inline at `worktree_sync.py:407`.
- ~~`_install_gh_stub(..., fail=True)`~~ — the existing stub has no failure mode; this task adds a
  separate helper.
- ~~`sync(..., skip_protection=...)`~~ — there is no bypass; `sync()` takes `cherry_picks`,
  `ff_only`, `dry_run` only.
- ~~a `stub.stat().st_size > 0` style assertion~~ — that vacuous pattern is what this feature
  exists to eliminate; never write one (spec §5).

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
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#push_protection_ok",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#_check_sandbox_push_protection",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#_gh"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

`_install_gh_stub` (`test_worktree_sync.py:50-86`) for writing a PATH-local executable stub, and
`test_sandbox_push_protection_refuses_before_gh` (`:405`) for the refusal shape.

### Key Constraints

- **Prove the refusal came before `gh`, not from a missing `gh`.** Install
  `_install_failing_gh_stub` in the protection-variant test: if the code ever reached `gh`, the
  message would carry the stub's stderr instead of `host-provisioned`. Asserting the
  `host-provisioned` text is therefore the proof, and it is not vacuous.
- **No config writes.** Snapshot both paths from `_git_control_paths(feature)` — read their bytes
  (treat a missing file as `None`) before the call and compare after. Compare *contents*, not
  mtimes alone.
- The `extra-pushurl` variant needs a second effective push URL: add
  `remote.origin.pushurl` a second time so `--get-all` returns two lines. Note
  `_configure_sandbox` writes the first one with `--worktree`; add the second the same way so
  both are effective for this worktree.
- The `missing-extension` variant must still have the `no_push` URL present — that is what makes
  it look protected. Write it to the **common** config (plain `git config`) since
  `--worktree` without `extensions.worktreeConfig=true` is not honoured.
- Parametrize with `@pytest.mark.parametrize` stacked exactly as the blueprint shows; do not
  collapse the two axes into one list.
- 120-column lines, one-line Google-style docstring per test, `ruff check --fix` before committing.

### References in Codebase

- `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py:402` — `push_protection_ok`
- `tests/sdd_scripts/test_worktree_sync.py:50` — `_install_gh_stub`, the stub-writing pattern
- `tests/sdd_scripts/test_worktree_sync.py:405` — the existing all-missing refusal test

---

## Implementation Blueprint

### Steps (in order)

1. Append the banner comment and the four blocks below at the **end of the file** — *why*: EOF is
   the only anchor that survives TASK-5235/5236 appending before you and TASK-5238 after.
2. Write `_install_failing_gh_stub` first — *why*: both of the other tests depend on it, and
   getting the `PATH` narrowing identical to `_install_gh_stub` is what makes the
   "refused before gh" assertion meaningful.
3. Complete every `# FILL IN:` marker.
4. Run the validation commands from the worktree with an absolute `PYTHONPATH`.

### `tests/sdd_scripts/test_worktree_sync.py` (MODIFY — append at EOF)

```python
# --- FEAT-820 / TASK-5237: push-protection truth table and gh failure -----------------------------


def _install_failing_gh_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    """Put a gh on PATH that writes ``message`` to stderr and exits 1 for every invocation."""
    executable = tmp_path / "gh"
    executable.write_text(f'#!/bin/sh\necho {message!r} >&2\nexit 1\n', encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{Path('/usr/bin')}")


def test_push_protection_ok_truth_table(tmp_path: Path) -> None:
    """Protection holds only for extensions.worktreeConfig=true plus exactly one no_push URL."""
    _origin, _primary, feature = _repository(tmp_path)

    assert worktree_sync.push_protection_ok(feature) is False

    # Looks protected, but the worktree-config extension is off.
    _run(feature, "config", "remote.origin.pushurl", "no_push")
    assert worktree_sync.push_protection_ok(feature) is False

    _run(feature, "config", "--unset-all", "remote.origin.pushurl")
    _run(feature, "config", "extensions.worktreeConfig", "true")
    # FILL IN: assert False — extension on, no push URL at all; bounded by worktree_sync.py:407

    _run(feature, "config", "--worktree", "remote.origin.pushurl", "no_push")
    # FILL IN: assert True — the only protected shape; bounded by worktree_sync.py:407

    _run(feature, "config", "--worktree", "--add", "remote.origin.pushurl", "git@github.com:example/sync.git")
    # FILL IN: assert False — a second effective push URL defeats protection;
    #          bounded by `urls == ["no_push"]` at worktree_sync.py:407


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("variant", ["missing-extension", "missing-pushurl", "extra-pushurl"])
def test_sandbox_push_protection_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str, dry_run: bool
) -> None:
    """Every incomplete protection shape exits 5 before gh, dry-run included, writing no config."""
    _origin, _primary, feature = _repository(tmp_path)
    _run(feature, "remote", "set-url", "origin", "git@github.com:example/sync.git")
    # FILL IN: apply `variant` using only `_run(feature, "config", ...)`:
    #   missing-extension -> plain `config remote.origin.pushurl no_push`, extension left unset
    #   missing-pushurl   -> `config extensions.worktreeConfig true`, no push URL
    #   extra-pushurl     -> extension true, `config --worktree remote.origin.pushurl no_push`
    #                        plus a second `--worktree --add` push URL
    #   — bounded by the truth table at worktree_sync.py:402-408

    common, worktree_config = _git_control_paths(feature)
    before = tuple(path.read_bytes() if path.is_file() else None for path in (common, worktree_config))
    _install_failing_gh_stub(tmp_path, monkeypatch, "gh must not be reached")
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=["a" * 40], dry_run=dry_run)

    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert "host-provisioned" in str(raised.value)
    assert "gh must not be reached" not in str(raised.value)
    assert tuple(path.read_bytes() if path.is_file() else None for path in (common, worktree_config)) == before


def test_sandbox_gh_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gh stub exiting 1 becomes a transport refusal carrying its stderr and the host hint."""
    _origin, primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    (primary / "patch.txt").write_text("from gh\n", encoding="utf-8")
    _run(primary, "add", "patch.txt")
    _run(primary, "commit", "-m", "gh patch")
    sha = _run(primary, "rev-parse", "HEAD")
    before = (_run(feature, "rev-parse", "HEAD"), _run(feature, "status", "--porcelain"), _refs(feature))
    _install_failing_gh_stub(tmp_path, monkeypatch, "gh: HTTP 403")
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=[sha])

    # FILL IN: assert exit_code == EXIT_TRANSPORT, "403" in the message and the host hint
    #          "run 'parrot sdd worktree sync-base <target>' from the host" is present
    #          — bounded by worktree_sync.py:397-399 and :432-434
    assert (_run(feature, "rev-parse", "HEAD"), _run(feature, "status", "--porcelain"), _refs(feature)) == before
    assert not (feature / "patch.txt").exists()
```

**Why this shape**: installing a *failing* `gh` in the protection test is what turns
`assert "host-provisioned" in …` into real evidence that the refusal happened before any remote
call — had the code reached `gh`, the message would read `gh must not be reached` instead, which
the next assertion rules out. The config-bytes comparison is the AC "verifies protection without
config writes"; compare contents, not mtimes. Keep `cherry_picks=["a" * 40]` — a well-formed
40-hex sha, so the refusal cannot be the short-sha validation at `worktree_sync.py:124-128`.

### FILL IN checklist

- [ ] `test_push_protection_ok_truth_table` — three remaining truth-table assertions; bounded by `worktree_sync.py:407`
- [ ] `test_sandbox_push_protection_required` — the three variant configurations; bounded by `worktree_sync.py:402-408`
- [ ] `test_sandbox_gh_failure` — exit code, stderr text and host-hint assertions; bounded by `worktree_sync.py:397-399`, `:432-434`

---

## Acceptance Criteria

- [ ] `_install_failing_gh_stub`, `test_push_protection_ok_truth_table`,
      `test_sandbox_push_protection_required` and `test_sandbox_gh_failure` exist and pass.
- [ ] `push_protection_ok` is asserted for all five configuration shapes named in spec §4.
- [ ] Each incomplete protection variant is proven to refuse with exit 5 **before** `gh`, in both
      `dry_run=False` and `dry_run=True`, with both git config files byte-identical afterwards.
- [ ] `test_sandbox_gh_failure` asserts both the stub's stderr text and the host hint appear in the
      refusal message.
- [ ] `test_sandbox_push_protection_refuses_before_gh` and the `test_native_policy_*` gates are
      unchanged.
- [ ] `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` is unchanged.
- [ ] `ruff check tests/sdd_scripts/test_worktree_sync.py` is clean.
- [ ] No test ends on a vacuous assertion — in particular no `st_size > 0` on the stub.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py::test_push_protection_ok_truth_table -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py::test_sandbox_push_protection_required -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py::test_sandbox_gh_failure -q`

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
2. **Read the spec** at `sdd/specs/fixgroup-d188effba3ca.spec.md` (§3 Module 3, §4, §6)
3. **Check dependencies** — `TASK-5236` must be `"done"` in
   `sdd/tasks/index/fixgroup-d188effba3ca.json`
4. **Verify the Codebase Contract** — re-check every line number above before writing code
5. **Update status** in `sdd/tasks/index/fixgroup-d188effba3ca.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only `tests/sdd_scripts/test_worktree_sync.py`
9. **Close the task** with `parrot sdd task close TASK-5237 fixgroup-d188effba3ca verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: ai-parrot-85 (agent:sdd-fix:b5e88ee1)
**Date**: 2026-11-06
**Notes**: Added `_install_failing_gh_stub`, the `_apply_protection_variant` helper and the three
tests. Each variant test asserts `push_protection_ok` is already False as a precondition, then
proves the refusal carries "host-provisioned" and NOT the failing stub's stderr — which is what
shows `gh` was never reached — and compares both git config files byte-for-byte. `worktree_sync.py`
untouched. 58 passed, 2 skipped (native gates); `ruff check` clean.

**Deviations from spec**: none.
