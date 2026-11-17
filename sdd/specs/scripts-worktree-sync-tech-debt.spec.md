---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [worktree, sync-base, sandbox, push-protection, ledger-fix]
---

# Feature Specification: sync-base sandbox reachability check, clean OSError refusal, and host-provisioned push protection

**Feature ID**: FEAT-813
**Date**: 2026-11-05
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.1.0

Source: ledger `issue:e613f365cf61` (major, tech_debt) and `issue:891a632132e0` (minor, tech_debt),
both discovered from `spec:FEAT-806`. Authored by `/sdd-fix` (SDD lane, group
`fixgroup:4ec46fc2c05f`). Parent FEAT-806 is closed, so this is a new feature.

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot sdd worktree sync-base` (`packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py`,
FEAT-806) has four gaps found in the FEAT-806 review:

- **P1 (e613) — sandbox cherry-pick skips the reachability check.** The host path refuses a
  `--cherry-pick <sha>` that is not an ancestor of `origin/<base>`
  (`git merge-base --is-ancestor`, exit 5). The sandbox path (`_sandbox_patches`) only checks the
  commit exists, is canonical and single-parent, so any commit on any branch of the repository can be
  applied in the sandbox.
- **P2 (891a-1) — missing `git`/`gh` binary gives a traceback.** `main()` catches only `SyncError`;
  `FileNotFoundError`/`OSError` from `subprocess.run` escapes. `stale_base_summary` already handles it.
- **P3 (891a-2) — push protection is a manual step.** Sandbox cherry-picks require
  `extensions.worktreeConfig=true` and exactly one effective `remote.origin.pushurl=no_push` on the
  target worktree. No code sets this up; `docs/sdd/worktree-sync-base.md` describes it as a manual
  host step, so every sandbox cherry-pick exits 5 until someone does it by hand. Automatic setup must
  not break the host's own later push from that worktree (`/sdd-done` Step 8 runs
  `git -C <worktree> push origin <branch>`, which `no_push` would make fail).
- **P4 (891a-3) — duplication and an exit-code clash.** The "rollback → conflict / unverified-error"
  result block is duplicated between the sandbox and host branches of `sync()`. `EXIT_TARGET = 2` is
  the spec value but collides with argparse's usage-error exit code 2; this is undocumented.

### Goals

- G1: the sandbox path refuses (exit 5, no worktree change) a cherry-pick that is not reachable from
  `<base>` on GitHub, matching the host path's guarantee.
- G2: `main()` turns `OSError`/`subprocess.SubprocessError` into a `refused` result with exit 5
  (JSON-safe), never a traceback.
- G3: a host command provisions and removes sandbox push protection on one linked worktree; the
  worker launcher provisions it before starting a worker, and `/sdd-done` removes it before pushing.
- G4: one shared rollback-result helper in `sync()`; exit code 2's double meaning documented.

### Non-Goals

- Changing exit-code values (2 stays `EXIT_TARGET`, per the FEAT-806 spec).
- Migrating a repository that has a common `core.worktree` or `core.bare=true`: provisioning refuses
  and points at the manual procedure in the docs instead.
- Removing `extensions.worktreeConfig` once enabled (it is harmless and repository-wide).
- Provisioning from inside a sandbox (host only; the sandbox keeps only the read-only check).
- Network enforcement — the sandbox's network policy stays the primary push barrier; `no_push` is
  defence in depth.

---

## 2. Architectural Design

### P1 — sandbox reachability

`_sandbox_patches(wt, cherry_picks, base)` gains the `base` argument (`sync()` passes it). After the
existing metadata validation of each commit, it calls
`gh api repos/<owner>/<repo>/compare/<base>...<source_sha>` through the existing `_gh` helper and
parses `status`. GitHub reports `status` for `head` relative to `base`: `behind` or `identical` means
the commit is an ancestor of (or equal to) the base tip. Any other status (`ahead`, `diverged`), a
missing/invalid `status`, or invalid JSON raises
`SyncError(EXIT_TRANSPORT, _sandbox_hint(f"cherry-pick {sha} is not reachable from origin/{base}"))`.
The check runs inside the existing "validate everything before any mutation" loop, so a refusal
leaves the worktree untouched (dry run included). `base` was already validated by
`_validate_base` (check-ref-format), so it is passed unquoted.

### P2 — clean refusal in `main()`

`main()` catches `(OSError, subprocess.SubprocessError)` in addition to `SyncError` and builds the
refusal via `_refusal` with a `SyncError(EXIT_TRANSPORT, f"required tool unavailable: {exc}")`.

### P3 — push protection provisioning

New module `packages/ai-parrot/src/parrot/sdd/scripts/worktree_push_protection.py`, exposed as
`parrot sdd worktree push-protection {enable|disable|status} <target> [--json]` (new `VERBS` entry in
`parrot/sdd/cli.py`). It reuses `worktree_sync.resolve_target` (registered, non-primary linked
worktree only) and `worktree_sync.in_sandbox`.

- `enable(wt)`: refuse in a sandbox (exit 5). Refuse (exit 2) when the common config has any
  `core.worktree`, or `core.bare=true`, or any `remote.origin.pushurl` (a common push URL would make
  the effective value multi-valued; the operator must resolve it by hand, see docs). Otherwise
  `git config extensions.worktreeConfig true` and
  `git -C <wt> config --worktree --replace-all remote.origin.pushurl no_push`. Idempotent. Never
  touches sibling worktrees or the common push URL.
- `disable(wt)`: refuse in a sandbox. `git -C <wt> config --worktree --unset-all
  remote.origin.pushurl` when `extensions.worktreeConfig` is true; "not set" (git exit 5) is
  success. Idempotent; a no-op on a worktree that was never protected.
- `status(wt)`: reports `protected: bool` using the same rule as
  `worktree_sync._check_sandbox_push_protection` (shared predicate — refactor that function to call a
  new `push_protection_ok(wt) -> bool`).
- Exit codes reuse `worktree_sync`'s constants (0 ok, 2 target/config refusal, 5 sandbox/transport).

Wiring:
- `parrot/flows/dev_loop/feature_launcher.py`: on the host, after `_preflight_sandbox` and the
  stale-base advisory and before either launch path (direct or tmux), call `enable(worktree)` and
  print a one-line result to stderr. A refusal is a warning, never a launch failure (the sandbox
  cherry-pick then exits 5 with its existing guidance, as today).
- `/sdd-done` Step 8 (all six copies: `.claude/commands/sdd-done.md`, `.agent/workflows/sdd-done.md`,
  `.agents/skills/sdd-done/SKILL.md` and their `packages/ai-parrot/src/parrot/sdd/_assets/` twins):
  run `parrot sdd worktree push-protection disable "<worktree-path>"` immediately before the first
  `git -C <worktree-path> push`. Assets regenerated with
  `python -m scripts.sdd.check_asset_sync --write`.
- `docs/sdd/worktree-sync-base.md`: "Host setup" section documents the command and the launcher /
  `/sdd-done` wiring, keeping the manual procedure for refused cases.

### P4 — refactor

Extract `_integration_failure(wt, base, mode, before, commits, abort_command) -> SyncResult` in
`worktree_sync.py` (rollback, then `conflict`/EXIT_CONFLICT if restored else the unverified-recovery
`error`), used by both branches. Behavior unchanged. Add a comment at the exit-code constants and a
note under "Exit codes" in the docs that exit 2 is also argparse's usage-error code (distinguish by
the `--json` body: a usage error emits none).

---

## 3. Acceptance Criteria

- AC1: in sandbox mode, a cherry-pick whose compare status is `ahead` or `diverged` raises
  `SyncError` with exit 5 and "not reachable" in the message; HEAD and status are unchanged; this holds
  for `dry_run=True` too.
- AC2: in sandbox mode, `behind` and `identical` compare statuses still sync (existing sandbox tests
  stay green with the gh stub serving a `behind` compare by default).
- AC3: `worktree_sync.main([...])` with `git` missing from `PATH` returns 5 and, with `--json`,
  prints a `refused` result; no traceback.
- AC4: `push-protection enable` on a linked worktree makes
  `worktree_sync._check_sandbox_push_protection` pass; `disable` makes it fail again and lets
  `git push` from that worktree reach a local bare origin; both are idempotent; the primary
  checkout's and a sibling worktree's effective `remote.origin.pushurl` are unchanged.
- AC5: `enable` refuses (exit 2, no config written) when common config has `core.worktree`,
  `core.bare=true`, or a common `remote.origin.pushurl`; `enable`/`disable` refuse with exit 5 in
  sandbox mode.
- AC6: `parrot sdd worktree push-protection --help` works through the installed CLI.
- AC7: the feature launcher calls `enable` on the host before launching (direct and tmux paths); an
  enable refusal does not stop the launch.
- AC8: every `/sdd-done` copy runs `push-protection disable` before its first worktree push, and
  `check_asset_sync --check` is clean.
- AC9: `sync()` behavior for conflict/unverified-rollback is unchanged (existing conflict tests green).

---

## 4. Task Breakdown

1. **TASK-5218** — P1 + P2 + P4 in `worktree_sync.py` (+ tests, exit-code doc note).
   Discovered-from `issue:e613f365cf61`, `issue:891a632132e0`.
2. **TASK-5219** — P3: `worktree_push_protection.py`, CLI verb, launcher wiring, `/sdd-done` copies,
   docs (+ tests). Discovered-from `issue:891a632132e0`. Depends on TASK-5218 (both edit
   `worktree_sync.py`).

---

## 5. Risks

- R1: GitHub's compare API on a very large divergence may be slow; it is one call per requested
  commit, same order as the existing metadata/patch calls.
- R2: A host push from a worker-provisioned worktree outside `/sdd-done` (manual, `/remove-worktree`
  hint) fails with `'no_push' does not appear to be a git repository` until `push-protection disable`
  is run. Documented in the docs; the error names the URL, so it is diagnosable.
- R3: `extensions.worktreeConfig` changes how git reads `config.worktree` repository-wide; enabling it
  with only `core.bare=false` common (this repository's state) keeps every worktree's effective
  config unchanged.
