# TASK-5229: Sandbox dirty guard checks tracked changes only

**Feature**: FEAT-814 — sync-base refusal classification, transport hardening, and a runnable native gate
**Spec**: `sdd/specs/scripts-worktree-sync-tech-debt-2.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-5220
**Assigned-to**: unassigned
**Discovered-from**: `issue:815953379c34`

---

## Context

Found by TASK-5221 once the native gate actually ran (`artifacts/logs/FEAT-814-native-gate.log`).
Claude Code's native sandbox runtime (CLI 2.1.318) places mount placeholders for its protected paths
(`.bashrc`, `.profile`, `.claude/agents`, `.claude/settings.json`, `.mcp.json`, `.gitconfig`, `.vscode`,
`.idea`, …) inside the session's working directory. Git sees them as untracked files, so
`check_guards()` refuses every sandboxed `sync-base` with exit 3 (dirty) — sandbox patch sync can
never succeed. The runtime also leaves a 0-byte `config.worktree` placeholder in the worktree's Git
admin directory (we list it in `denyWrite`, `native_claude_sandbox.py:230`); an empty config file sets
nothing, so it is harmless, but `test_native_policy_missing_protection_refuses` asserts it is absent.

Operator decision (2026-11-05): inside the sandbox, dirtiness means tracked changes only.

---

## Scope

- `check_guards(wt)`: when `in_sandbox()`, compute dirtiness from
  `git status --porcelain --untracked-files=no`; the host keeps the full porcelain check (untracked
  files included). Refusal message and exit code (3) unchanged.
- Safety argument (record in the docstring): `git am -3` refuses to overwrite an untracked file, and
  TASK-5220 reports such a refusal as `status="refused"` (exit 6) without any abort.
- `test_native_policy_missing_protection_refuses`: replace `assert not worktree_config.exists()` (after
  the session) with "absent or empty" (`not exists() or read_bytes() == b""`) — no config key written.
  The pre-session `assert not worktree_config.exists()` stays.
- Unit tests: sandbox ignores untracked files; sandbox still refuses a tracked change; host still
  refuses an untracked file.
- Operator guide: one sentence on the sandbox dirty rule.

**NOT in scope**: changing `native_claude_sandbox`'s `denyWrite` list; host behaviour.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` | MODIFY | `check_guards` sandbox rule |
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY | unit tests + native assertion |
| `docs/sdd/worktree-sync-base.md` | MODIFY | sandbox dirty rule |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
- `worktree_sync.check_guards(wt: Path) -> None` (detached-HEAD check from TASK-5220, then `_status`).
- `worktree_sync.in_sandbox() -> bool`, `worktree_sync._git(wt, *args, timeout=None)`.
- `tests/sdd_scripts/test_worktree_sync.py::test_native_policy_missing_protection_refuses`.

### Does NOT Exist
- No placeholder-name allowlist anywhere — do not add one.

---

## Acceptance Criteria

- [ ] Sandboxed sync with untracked files present proceeds; with a tracked change refuses exit 3.
- [ ] Host sync with an untracked file still refuses exit 3.
- [ ] Both native gate tests pass with `PARROT_TEST_REAL_LLM=1` (verified under TASK-5221).
- [ ] `ruff check` clean.

---

## Validation Commands

Run with `PYTHONPATH=packages/ai-parrot/src` from the worktree.

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`

---

## Agent Instructions

Implement in the FEAT-814 worktree; TASK-5221 re-runs the real gate afterwards.

---

## Completion Note

Implemented in 7c04cfa1bc. `check_guards()` uses `status --porcelain --untracked-files=no` when
`in_sandbox()`; the host keeps `_status()`. Root cause was read from the session transcript of the first
real gate run (an in-sandbox `git status --porcelain --ignored` listed `.bashrc`, `.profile`, `.zshrc`,
`.gitconfig`, `.gitmodules`, `.mcp.json`, `.idea`, `.vscode`, `.claude/{agents,commands,hooks,skills,...}`
as untracked — none exist on the host after the session).

The commit also carries TASK-5221's two gate-assertion corrections (same file): the empty
`config.worktree` placeholder is accepted, and the protected-config test no longer counts the target
branch's own advance as a foreign ref change (verified in the leftover repo: the only moved ref was
`refs/heads/feat-FEAT-999-sync`, reflog `am: native gh patch`).

Validation: 3 new unit tests; `test_worktree_sync.py` + push-protection + process-exclusion + sdd launch +
sdd cli suites 139 passed / 2 skipped (gate, needs PARROT_TEST_REAL_LLM); real gate 2/2 passed twice.
ruff + black clean.
