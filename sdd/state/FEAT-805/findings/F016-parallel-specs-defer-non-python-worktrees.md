---
id: F016
query_id: Q016
type: git_log
intent: "Is anyone already specifying this, and what did adjacent specs leave out?"
executed_at: 2026-11-04T22:48:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F016 — FEAT-802 and FEAT-804 (both 2026-11-04) explicitly defer non-Python worktree config to a follow-up spec

## Summary

Two specs written the same day, from the evaluation of the packaged flow on the external
`fieldsync` repository, list this work as a non-goal. FEAT-802 moves the worktree root
to `.parrot/worktrees/`; FEAT-804 unifies the portable rule and the install root. Neither
mentions `[tool.parrot.sdd]`. No proposal, spec or remote branch covers the topic;
FEAT-583 (`portable-sdd-flow`) is superseded by FEAT-633 and FEAT-709 is closed.

## Citations

- path: `sdd/specs/worktree-root-under-parrot.spec.md`
  lines: 62-63
  symbol: null
  excerpt: |
    - Preparing worktrees of non-Python repositories (`[tool.parrot.worktree]` outside `pyproject.toml`).
      Separate spec.

- path: `sdd/specs/installer-portability-gaps.spec.md`
  lines: 86-87
  symbol: null
  excerpt: |
    - Non-Python repositories' worktree provisioning (`[tool.parrot.worktree]` outside `pyproject.toml`) —
      separate follow-up spec.

- path: `sdd/specs/portable-sdd-flow.spec.md`
  lines: 8-17
  symbol: null
  excerpt: |
    status: superseded
    **Status**: superseded by FEAT-633 (sdd/specs/parrot-installer.spec.md)

## Notes

Commits on `origin/dev`: `c7bf629e48` "sdd: add spec for FEAT-804 —
installer-portability-gaps", `62a24634d9` "sdd: reserve 1 feature id(s) for
worktree-root-under-parrot". Index status: `parrot-installer` FEAT-633 54/54 done
(completed 2026-11-03), `language-agnostic-validation-runners` FEAT-709 23/23 done.
Interaction to respect: FEAT-802 makes `.parrot/` the worktree root and keeps it fully
git-ignored; FEAT-804 changes how installers resolve the install root and refuses
linked worktrees. A new committed config file must not live under `.parrot/`.
Related open ledger issues: `issue:29e8e7ad138f` (runner registry read from the
seat-writable worktree) and `issue:1ec3dc062b34` (`_set_pyproject_sandbox` text edit).
