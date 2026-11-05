# TASK-5220: sync-base refusal classification and transport hardening

**Feature**: FEAT-814 — sync-base refusal classification, transport hardening, and a runnable native gate
**Spec**: `sdd/specs/scripts-worktree-sync-tech-debt-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:24786d65b867`, `issue:163389368ca6`

---

## Context

Implements spec §2 P1–P4 (AC1–AC7, AC9). A never-started integration is misreported as an
unverified rollback; the mailbox trailer does not follow `git mailinfo`; network calls can hang;
refusals go to stdout and a detached HEAD is accepted.

---

## Scope

- `_operation_in_progress(wt)` and `_unchanged(wt, before)` helpers; call `_unchanged` on every
  integration failure (sandbox `am`, host merge / ff-only / cherry-pick) before `_rollback`; when
  true return `status="refused"`, `EXIT_CONFLICT`, message `"integration refused before starting;
  worktree unchanged: <first stderr line>"` (ff-only: `"fast-forward not possible; worktree
  unchanged"`). Replace the existing ff-only special case with this path.
- `_rollback`: catch `SyncError` from `_status()` → `restored=False`, detail = the message.
- `_is_patch_break(line)` mirroring mailinfo `patchbreak()`; `_patch_with_trailer` uses it and
  starts its search after the header block (first blank line after `Subject:`).
- `NETWORK_TIMEOUT` (120 s, env `PARROT_SDD_SYNC_TIMEOUT`); `_git(..., timeout=None)` always sets
  `GIT_TERMINAL_PROMPT=0`; the fetch passes the timeout; `TimeoutExpired` → `SyncError(EXIT_TRANSPORT)`.
  `_gh` gets the same timeout + conversion.
- `check_guards`: refuse detached HEAD with `EXIT_TARGET`.
- `main()`: non-JSON, `exit_code != 0` → message to stderr.
- Operator guide note; tests.

**NOT in scope**: sandbox reachability check (FEAT-813); exit-code values; `SyncResult` schema.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` | MODIFY | P1–P4 |
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY | tests listed below |
| `docs/sdd/worktree-sync-base.md` | MODIFY | `refused` for exit 6, timeout knob, stderr |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.scripts import native_claude_sandbox, worktree_sync  # tests/sdd_scripts/test_worktree_sync.py:12
```

### Existing Signatures to Use
See spec §6 (all verified on origin/dev b3b854ea85): `_git` :52, `_head` :57 (never raises),
`_branch` :63, `_status` :69 (raises), `check_guards` :180, `_result` :219, `_rollback` :249,
`_gh` :278, `_patch_with_trailer` :289, `sync` :335 (ff-only special case :437-448), `main` :505.

### Does NOT Exist
- `_integration_failure`, `_require_reachable` (FEAT-813 branch only).

---

## Implementation Notes

### Key Constraints
- Only network calls get a timeout; never local merge/cherry-pick/am.
- Keep the classification a small helper invoked just before `_rollback` (eases the FEAT-813 merge).
- mailinfo `patchbreak()`: `diff -` prefix; `Index: ` prefix; `---` followed by a space and a
  non-space char; `---` followed by only whitespace. Nothing else (no scissors).

---

## Acceptance Criteria

- [ ] AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC9 of the spec.

---

## Validation Commands

Run with `PYTHONPATH=packages/ai-parrot/src` from the worktree.

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`

---

## Test Specification

New tests in `tests/sdd_scripts/test_worktree_sync.py`:
`test_untracked_overwrite_merge_is_refused_unchanged`, `test_ff_only_divergence_is_refused`,
`test_cherry_pick_merge_commit_is_refused_unchanged`, `test_rollback_status_error_is_reported_as_exit_6`,
`test_patch_break_matches_mailinfo`, `test_trailer_survives_pasted_diff_body`,
`test_fetch_timeout_is_transport_refusal`, `test_git_disables_terminal_prompt`,
`test_detached_head_is_refused`, `test_cli_refusal_goes_to_stderr`, `test_short_sha_refused_before_gh`.

---

## Agent Instructions

Implement exactly the scope above inside the FEAT-814 worktree; run the validation command with
`PYTHONPATH` pointing at the worktree; commit `feat(scripts-worktree-sync-tech-debt-2): TASK-5220 — …`.

---

## Completion Note

_(filled at close)_
