---
name: remove-worktree
description: Inspect and safely remove stalled or finished SDD worktrees, refusing any worktree with a live sdd-worker inside
---

# Remove Worktree

## Full procedure and Codex adaptations

Before executing, read the [full remove-worktree procedure](../../../.claude/commands/remove-worktree.md)
and the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract).
Follow the full procedure for details omitted from this summary. The adaptation
contract and the Codex-specific instructions below override Claude runtime syntax
and legacy shell examples; retain all workflow gates and evidence requirements.

Invocation: `remove-worktree [<branch|FEAT-id|dir>] [--stale] [--delete-branch] [--force] [--dry-run]`.

## Workflow

1. Run `parrot sdd worktree list` and show the user every worktree and orphan directory with its state.
2. Dry-run first: `parrot sdd worktree remove <target> --dry-run`.
3. Remove only after the user agrees: `parrot sdd worktree remove <target>` (`--stale` for orphan directories).

## Safety gates (all enforced by the tool)

| Gate | Overridable |
|---|---|
| Primary repository checkout | never |
| `main` / `dev` / `staging` / `master` branch | never |
| Live process with cwd inside | **never** — stop the process |
| Uncommitted changes | `--force` |
| Commits not on origin | `--force` |

An exact match on a protected branch name is refused up front, so
`remove-worktree dev` cannot silently resolve to
`feat-FEAT-378-devloop-enhancement` by substring.
