---
type: feature
base_branch: dev
projects: [sdd]
tags: [sdd-tooling, worktree, git, push-protection]
docs:
  policy: none
---

# Feature Specification: Guard the shared push URL against worktree push-protection bypass

**Feature ID**: FEAT-865
**Date**: 2026-11-10
**Status**: approved
**Discovered-from**: `issue:d0c89274743b`

## 1. Problem

A `/sdd-done` session hit the FEAT-813 sandbox guard (`remote.origin.pushurl=no_push`
in the worktree's `config.worktree`), bypassed it with `git remote set-url --push origin <url>`,
pushed, then "restored" it with `git remote set-url --push origin no_push`. `git remote set-url`
writes the **common** `.git/config`, so the primary checkout and every worktree lost push;
`reserve_ids` and `/sdd-fix` failed on the host until the operator removed it by hand.

## 2. Goals

- G1: `parrot sdd worktree push-protection disable` refuses (exit 2) when a common
  `remote.origin.pushurl` is set, naming the exact host remedy, instead of reporting success
  while the push would still be refused.
- G2: `push-protection status` reports a common push URL in its message.
- G3: every `/sdd-done` twin forbids `git remote set-url --push` / `git config remote.origin.pushurl`
  as a bypass, and tells the agent to stop and report when `disable` refuses.

## 3. Non-goals

- Automatically removing a common push URL (it may be operator-intended).
- Changing `enable()` (it already refuses a common push URL).

## 4. Design

`worktree_push_protection.disable()` reads the common config with `_common_values` and raises
`SyncError(EXIT_TARGET, ...)` when `remote.origin.pushurl` is present there, with the remedy
`git config --file <common config> --unset-all remote.origin.pushurl`. `main()` `status` appends
`; common remote.origin.pushurl is set (<values>)` to the message when present.

Docs: the push step of `sdd-done` in `.claude/commands/`, `.agent/workflows/`, `.agents/skills/`
and their `_assets` twins gains one rule line.

## 5. Acceptance Criteria

- AC1: `disable` on a worktree whose common config holds `remote.origin.pushurl` exits 2,
  writes nothing, and the message contains `--unset-all remote.origin.pushurl`.
- AC2: `status --json` message mentions the common push URL when set.
- AC3: all six sdd-done files contain `never use \`git remote set-url --push\``; twins stay byte-identical.
- AC4: `tests/sdd_scripts/test_worktree_push_protection.py` passes.

## 6. Tasks

- TASK-5457 — common push URL guard + sdd-done rule.
