---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [worktree, sync-base, sandbox, ledger-fix, native-gate]
---

# Feature Specification: sync-base refusal classification, transport hardening, and a runnable native gate

**Feature ID**: FEAT-814
**Date**: 2026-11-05
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.1.0

Source: ledger `issue:24786d65b867` (major, bug), `issue:163389368ca6` (minor, tech_debt) and
`issue:815953379c34` (minor, tech_debt), all discovered from `spec:FEAT-806`. Authored by
`/sdd-fix` (SDD lane, group `fixgroup:b45eda1cf471`). Parent FEAT-806 is closed (PR #1967), so
this is a new feature.

> **Overlap with FEAT-813 (in flight, unmerged).** FEAT-813 (`scripts-worktree-sync-tech-debt`)
> edits the same file: it extracts the failure tail of `sync()` into `_integration_failure()`,
> adds the sandbox reachability check (`_require_reachable`) and a `main()` OSError refusal. By
> operator decision this feature is implemented now on `origin/dev`; whichever of the two merges
> second resolves the conflict by hand. The sandbox *reachability* sub-item of
> `issue:163389368ca6` is left to FEAT-813 and is NOT re-implemented here.

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot sdd worktree sync-base` (`packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py`,
FEAT-806) still has these gaps on `dev`:

- **P1 (24786) — a never-started integration is reported as an unverified rollback.** When
  `git merge` refuses before starting (untracked file would be overwritten) or `git cherry-pick`
  refuses (merge SHA without `-m`), no in-progress state exists; `_rollback()` then runs
  `merge --abort` / `cherry-pick --abort`, which fails, and the result is `status=error`,
  "automatic rollback was not verified" although HEAD and the tree never moved. The `--ff-only`
  divergence case is special-cased but still reports `status=error`. `_rollback()` also calls
  `_status()`, which raises `SyncError(EXIT_TARGET)` after a mutation instead of reporting exit 6.
- **P2 (1633) — mailbox trailer insertion does not match `git mailinfo`.** `_patch_with_trailer`
  inserts the `(cherry picked from commit …)` trailer before the first line starting with `---`.
  `git mailinfo` ends the message at `diff -`, `Index: `, `--- <name>` or a whitespace-only `---`
  line — so a body with a pasted diff loses the trailer, and a body line such as `------` is
  wrongly treated as the separator.
- **P3 (1633) — no timeout / prompt suppression on network calls.** `git fetch` (also run by
  `stale_base_summary` from `parrot sdd launch worker`) and `gh api` can hang forever on an
  SSH/network stall or a credential prompt.
- **P4 (1633) — CLI hygiene.** Non-JSON refusals are printed to stdout; a detached-HEAD target is
  accepted for a mutating sync.
- **P5 (8159) — the native sandbox gate can never run.** `test_native_policy_*` resolve the
  `claude` CLI from `PATH` *after* `_install_gh_stub` rewrote `PATH` to `<tmp>:/usr/bin`, so they
  always skip with "Claude CLI is unavailable"; the in-sandbox command also runs bare `python`,
  which on that `PATH` is not the project interpreter. TASK-5212 (FEAT-806) was therefore closed
  `partial`.

### Goals
- G1: classify a failed integration by the real post-state: unchanged & no operation in progress
  → `status="refused"`; restored after abort → `conflict`; otherwise `error` (exit 6, never 2).
- G2: trailer insertion follows `git mailinfo`'s patch-break rules.
- G3: network calls (`git fetch`, `gh api`) are bounded and never prompt; a timeout is an exit-5
  transport refusal.
- G4: non-JSON refusals go to stderr; mutating sync of a detached HEAD is refused (exit 2).
- G5: the native gate runs on a normal host with `PARROT_TEST_REAL_LLM=1`, and its evidence is
  recorded; TASK-5212 is re-stamped `verified` only if both gate tests pass.

### Non-Goals (explicitly out of scope)
- Sandbox reachability check (FEAT-813 `_require_reachable`).
- Changing exit-code values or the `SyncResult` schema.
- Push-protection provisioning (FEAT-813 TASK-5219).

---

## Governing Decisions

None beyond the FEAT-806 spec (exit codes, JSON shape, host/sandbox transports).

---

## 2. Architectural Design

### Overview

All behaviour changes stay inside `worktree_sync.py`; the gate fix is test-only.

- `_operation_in_progress(wt) -> bool` — true when any of `MERGE_HEAD`, `CHERRY_PICK_HEAD`,
  `REVERT_HEAD` or the `rebase-apply` / `rebase-merge` directories exist under
  `git rev-parse --git-path`.
- `_unchanged(wt, before) -> bool` — `HEAD == before`, clean status, no operation in progress.
  Used on every integration failure (host merge / ff-only / cherry-pick and sandbox `am`) BEFORE
  `_rollback()`; when true the result is `refused`/exit 6 with the first line of Git's stderr.
- `_rollback()` catches `SyncError` from `_status()` and reports `restored=False` with the detail.
- `_is_patch_break(line) -> bool` mirrors mailinfo's `patchbreak()` (without scissors).
- `_git(wt, *args, timeout=None)` always sets `GIT_TERMINAL_PROMPT=0`; the fetch passes
  `timeout=NETWORK_TIMEOUT` and a `subprocess.TimeoutExpired` becomes `SyncError(EXIT_TRANSPORT)`.
  `_gh` gets the same timeout handling. `NETWORK_TIMEOUT` defaults to 120 s and may be overridden
  by `PARROT_SDD_SYNC_TIMEOUT` (positive integer seconds; invalid values fall back to 120).
- `check_guards()` refuses a detached HEAD (`EXIT_TARGET`).
- `main()` prints the message to stderr when `exit_code != 0` in non-JSON mode.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `stale_base_summary` | uses `sync(dry_run=True)` | gains bounded fetch; already catches `SyncError` |
| `parrot sdd worktree sync-base` CLI | `main()` | stderr routing only |
| `tests/sdd_scripts/test_worktree_sync.py` | test helpers | `_native_cli`, native command |

### Data Models

No change. `SyncResult.status` already allows `"refused"`.

### New Public Interfaces

None (helpers are private; `NETWORK_TIMEOUT` is a module constant).

---

## 3. Module Breakdown

### Module 1: sync-base refusal classification and transport hardening (TASK-5220)
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py`,
  `tests/sdd_scripts/test_worktree_sync.py`
- **Responsibility**: P1–P4.

### Module 2: runnable native gate (TASK-5221)
- **Path**: `tests/sdd_scripts/test_worktree_sync.py`, `sdd/tasks/index/worktree-sync-base.json`,
  `sdd/tasks/completed/TASK-5212-worktree-sync-native-qualification.md`
- **Responsibility**: P5 — make the gate runnable, run it, record evidence, re-stamp TASK-5212.
- **Depends on**: Module 1 (same test file).

---

## 4. Test Specification

### Unit / Integration Tests (real temporary Git repositories)

| Test | Module | Description |
|---|---|---|
| `test_untracked_overwrite_merge_is_refused_unchanged` | 1 | merge refused by an untracked file → `refused`, exit 6, HEAD unchanged |
| `test_ff_only_divergence_is_refused` | 1 | diverged `--ff-only` → `refused`, exit 6 |
| `test_cherry_pick_merge_commit_is_refused_unchanged` | 1 | host cherry-pick of a merge SHA → `refused`, exit 6 |
| `test_rollback_status_error_is_reported_as_exit_6` | 1 | `_status` raising inside `_rollback` → `restored=False`, no exception |
| `test_patch_break_matches_mailinfo` | 1 | `diff -`, `Index: `, `--- a/x`, `---`, `---  ` break; `------`, `---x` do not |
| `test_trailer_survives_pasted_diff_body` | 1 | sandbox patch whose body contains `diff --git` keeps the trailer |
| `test_fetch_timeout_is_transport_refusal` | 1 | `TimeoutExpired` from the fetch → `SyncError(EXIT_TRANSPORT)` |
| `test_git_disables_terminal_prompt` | 1 | `_git` passes `GIT_TERMINAL_PROMPT=0` |
| `test_detached_head_is_refused` | 1 | mutating sync on detached HEAD → `SyncError(EXIT_TARGET)` |
| `test_cli_refusal_goes_to_stderr` | 1 | non-JSON refusal message on stderr, stdout empty |
| `test_short_sha_refused_before_gh` | 1 | sandbox `--cherry-pick abc` refused (exit 2) before `gh` runs |
| `test_native_policy_*` (existing) | 2 | runnable with `PARROT_TEST_REAL_LLM=1` |

### Validation Contract

```bash
PYTHONPATH=packages/ai-parrot/src pytest tests/sdd_scripts/test_worktree_sync.py -q
PARROT_TEST_REAL_LLM=1 PYTHONPATH=packages/ai-parrot/src pytest tests/sdd_scripts/test_worktree_sync.py -k native_policy -rs -q
```

### E2E Scenarios

None (`e2e` policy defaults to optional; the native gate above is the real-boundary check).

---

## 5. Acceptance Criteria

- [ ] AC1: merge refused by untracked overwrite, diverged `--ff-only`, and host cherry-pick of a
  merge SHA each return `status="refused"`, `exit_code=6`, `before == after`, clean tree.
- [ ] AC2: a real conflict still returns `conflict` (existing tests unchanged and green).
- [ ] AC3: `_rollback` never raises; a `_status` failure yields `restored=False`.
- [ ] AC4: `_is_patch_break` matches mailinfo for the cases in §4; the trailer survives a pasted diff.
- [ ] AC5: fetch and `gh api` are bounded; timeout → exit 5; every `_git` call sets `GIT_TERMINAL_PROMPT=0`.
- [ ] AC6: detached HEAD refused (exit 2) for mutating sync; dry-run still works.
- [ ] AC7: non-JSON refusals print on stderr.
- [ ] AC8: both native gate tests run (not skip) on a host with the `claude` CLI and
  `PARROT_TEST_REAL_LLM=1`; result and log recorded under `artifacts/logs/`; TASK-5212 re-stamped
  `verified` only when both pass, otherwise the failure is recorded and TASK-5212 stays `partial`.
- [ ] AC9: `ruff check` clean on changed files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.sdd.scripts import native_claude_sandbox, worktree_sync  # tests/sdd_scripts/test_worktree_sync.py:12
from parrot.sdd.scripts.native_claude_sandbox import BACKEND_ENV     # worktree_sync.py:17
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py (origin/dev b3b854ea85)
EXIT_OK, EXIT_TARGET, EXIT_DIRTY, EXIT_LIVE, EXIT_TRANSPORT, EXIT_CONFLICT = 0, 2, 3, 4, 5, 6  # :22
class SyncError(Exception): def __init__(self, exit_code: int, message: str) -> None  # :26
class SyncResult(BaseModel): status: Literal["synced","up-to-date","refused","conflict","error"]  # :34,46
def _git(wt: Path, *args: str) -> subprocess.CompletedProcess[str]  # :52
def _head(wt: Path) -> str  # :57  (returns "" on failure, never raises)
def _branch(wt: Path) -> str | None  # :63
def _status(wt: Path) -> list[str]  # :69  (raises SyncError(EXIT_TARGET))
def _validate_commit(commit: str) -> None  # :86  (runs before the sandbox branch in sync(), :347)
def check_guards(wt: Path) -> None  # :180
def _rollback(wt: Path, before: str, command: str) -> tuple[bool, list[str], str]  # :249
def _gh(wt: Path, endpoint: str, *, patch: bool = False) -> str  # :278
def _patch_with_trailer(patch: str, source_sha: str) -> str  # :289
def sync(wt, base, *, cherry_picks=(), ff_only=False, dry_run=False) -> SyncResult  # :335
def main(argv: Sequence[str] | None = None) -> int  # :505
```

```python
# tests/sdd_scripts/test_worktree_sync.py (origin/dev)
def _install_gh_stub(tmp_path, monkeypatch, responses) -> None  # :45 — sets PATH to f"{tmp_path}:/usr/bin" at :67
def _native_cli() -> Path  # :78 — scans os.environ["PATH"] at call time
def _native_session(feature: Path, command: str) -> subprocess.CompletedProcess[str]  # :92
def test_native_policy_sync_with_protected_config(...)  # :244 — command runs bare `python`
def test_native_policy_missing_protection_refuses(...)  # :290 — command runs bare `python`
```

### Does NOT Exist (Anti-Hallucination)
- `_integration_failure`, `_require_reachable`, `push_protection_ok` — FEAT-813 branch only, not on dev.
- `NETWORK_TIMEOUT`, `_operation_in_progress`, `_unchanged`, `_is_patch_break` — created by this feature.

---

## 7. Implementation Notes & Constraints

### Known Risks / Gotchas
- FEAT-813 conflict in `sync()`'s failure tail and `main()` (see banner). Keep the new
  classification in a small helper called right before `_rollback`, so the merge is mechanical.
- Never put a timeout on local mutating Git commands (merge/cherry-pick/am): a kill mid-operation
  leaves in-progress state. Only the network calls are bounded.
- The native gate costs real model usage (Haiku, ≤ $0.20 per test) and needs the native sandbox.

---

## 8. Open Questions

None.

---

## 10. Documentation

`docs/sdd/worktree-sync-base.md`: note `status="refused"` for a never-started integration,
the `PARROT_SDD_SYNC_TIMEOUT` knob, and stderr routing.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-11-05 | Jesus Lara (with Claude) | Initial, from `/sdd-fix` group `fixgroup:b45eda1cf471` |
