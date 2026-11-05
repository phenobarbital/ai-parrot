# TASK-5221: Make the native sync-base gate runnable, run it, re-stamp TASK-5212

**Feature**: FEAT-814 — sync-base refusal classification, transport hardening, and a runnable native gate
**Spec**: `sdd/specs/scripts-worktree-sync-tech-debt-2.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-5220, TASK-5229
**Assigned-to**: unassigned
**Discovered-from**: `issue:815953379c34`

---

## Context

Implements spec §2 P5 (AC8). `test_native_policy_sync_with_protected_config` and
`test_native_policy_missing_protection_refuses` always skip with "Claude CLI is unavailable":
`_native_cli()` scans `PATH` after `_install_gh_stub` rewrote it to `<tmp>:/usr/bin`. The in-sandbox
command also runs bare `python`, which on that `PATH` is not the project interpreter.

---

## Scope

- Capture the host `PATH` at test-module import; `_native_cli()` resolves `claude` with
  `shutil.which("claude", path=<captured PATH>)`.
- Both native commands run `sys.executable` (quoted) instead of bare `python`.
- Run `PARROT_TEST_REAL_LLM=1 ... -k native_policy -rs` on the host; save the log to
  `artifacts/logs/FEAT-814-native-gate.log`.
- If both pass: set TASK-5212 `verification` to `verified` in `sdd/tasks/index/worktree-sync-base.json`
  and append a dated addendum to TASK-5212's Completion Note citing the log. If either fails: record
  the failure in this task's Completion Note, leave TASK-5212 `partial`, and close this task
  `done-with-issues`.

**NOT in scope**: changing `native_claude_sandbox`; changing the assertions of the gate tests
(unless a failure proves an assertion wrong — then stop and record it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY | CLI resolution + interpreter |
| `sdd/tasks/index/worktree-sync-base.json` | MODIFY | TASK-5212 verification (only on pass) |
| `sdd/tasks/completed/TASK-5212-worktree-sync-native-qualification.md` | MODIFY | addendum (only on pass) |
| `artifacts/logs/FEAT-814-native-gate.log` | CREATE | gate evidence (`git add -f` if ignored) |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
- `tests/sdd_scripts/test_worktree_sync.py`: `_install_gh_stub` :45 (PATH rewrite :67),
  `_native_cli` :78, `_native_session` :92, native commands at :264-268 and :317.

### Does NOT Exist
- Any `PARROT_TEST_CLAUDE_CLI` override — do not invent one.

---

## Acceptance Criteria

- [ ] AC8 of the spec.

---

## Validation Commands

Run with `PYTHONPATH=packages/ai-parrot/src` from the worktree; the second one also needs
`PARROT_TEST_REAL_LLM=1` and the host `claude` CLI.

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py -k native_policy -rs -q`

---

## Agent Instructions

The second command spends real model usage (Haiku, ≤ $0.20 per test); run it once from the host.

---

## Completion Note

_(filled at close)_
