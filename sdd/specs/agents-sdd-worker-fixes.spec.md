---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd, sdd-worker, assets, c29, ledger-fix]
---

# Feature Specification: sdd-worker agent — drop bare `python` from execution_id guidance

**Feature ID**: FEAT-797
**Date**: 2026-11-03
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

`packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py::test_no_c29_findings_in_shipped_files`
fails on `dev`. The C29 audit (`parrot/sdd/audit.py`, kind `bare-python`) forbids running a bare
`python` command in shipped SDD assets, because many hosts (Ubuntu, Debian, macOS) ship no `python`
binary. The execution_id guidance added to `.claude/agents/sdd-worker.md:335` (and its shipped twin
`packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md:335`) reads
`python -c 'import uuid; print(uuid.uuid4())'`.

Source: ledger `issue:6480940ab36a` (discovered from `task:HOTFIX-sdd-worker-gh-only-sandbox-2`).

### Goals
- The C29 gate passes over the shipped set.
- Both copies of `sdd-worker.md` stay byte-identical.

### Non-Goals
- No change to the audit rules, the allowlists or any other asset.

## 2. Architectural Design

Replace `python -c` with `python3 -c` on that line in both copies. `python3` is not matched by the
`bare-python` rule and the semantics (a canonical lowercase UUID from a command) are unchanged; the
`/proc/sys/kernel/random/uuid` fallback stays.

## 3. Module Breakdown

| Module | Change |
|---|---|
| `.claude/agents/sdd-worker.md` | `python -c` → `python3 -c` (line 335) |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | same edit (twin) |

## 4. Test Specification

Existing tests only: `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` (C29 gate, among others).

## 5. Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q` passes.
- [ ] `cmp .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` is silent.

## 6. Codebase Contract

- `packages/ai-parrot/src/parrot/sdd/audit.py:71` — `bare-python`: `python` (never `python3`) run as a command.
- `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py:99` — `_C29_GATED_KINDS = ("bare-python", "worktree-artifact")`.

## 7. Implementation Notes & Constraints

Two-line doc change; single task.

## 8. Open Questions

None.

## Worktree Strategy

Single task, one feature worktree `feat-FEAT-797-agents-sdd-worker-fixes` off `origin/dev`.

## Revision History

- 2026-11-03 — created by /sdd-fix from `issue:6480940ab36a`.
