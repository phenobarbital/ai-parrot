# TASK-2720: Remove the duplicate hardcoded wiki hook from `.claude/settings.json`

**Feature**: FEAT-495 — Portable wikitoolkit config paths
**Spec**: `sdd/specs/portable-wikitoolkit-config-paths.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements Spec §2 / §3 Module 1.

`.claude/settings.json` is tracked and contains **two** `PreToolUse`
`Grep|Glob|Read|Bash` wiki hooks: a portable one using `$CLAUDE_PROJECT_DIR`
(kept) and a **duplicate** with a hardcoded `/home/jesuslara/...` absolute path.
The duplicate (a) reintroduces a machine-specific path on every merge — the
collision Arturo and Jesus keep hitting — and (b) makes the wiki `claude-hook`
fire **twice** per matching tool call. Removing it is the sole tracked fix
remaining (the `.mcp.json` half is already local-only on `dev` via `145db5786`).

---

## Scope

- Delete the entire duplicate `PreToolUse` hook object whose matcher is
  `Grep|Glob|Read|Bash` and whose command is the hardcoded
  `/home/jesuslara/proyectos/ai-parrot/.venv/bin/wikitoolkit claude-hook`
  (lines 30–39 on `dev` at spec-write time — re-locate by content, not by line
  number, in case the file shifted).
- Keep the portable `Grep|Glob|Read|Bash` wiki hook
  (`"$CLAUDE_PROJECT_DIR/.venv/bin/wikitoolkit" claude-hook`).
- Preserve everything else verbatim: the `permissions` block, the
  `Bash|Edit|Write|MultiEdit` → `dangerous-actions-blocker.sh` hook, and both
  `sdd-worker-format.sh` hooks (`SubagentStop` + `Stop`).
- Result must remain valid JSON with existing 2-space indentation.

**NOT in scope**: touching `.mcp.json`, `.gitignore`, or creating
`.mcp.json.example` (that is TASK-2721). Do NOT re-track `.mcp.json`. Do NOT
add any CI/pre-commit guard (deferred, spec §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/settings.json` | MODIFY | Delete the duplicate hardcoded wiki-hook object; keep the `$CLAUDE_PROJECT_DIR` one |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` (worktree) 2026-09-01. Re-confirm by content before editing.

### Verified current structure of `.claude/settings.json`
```jsonc
// "permissions": { "allow": ["Bash(ruff:*)", "Bash(touch:*)"] }          ← PRESERVE
// PreToolUse[0] matcher "Grep|Glob|Read|Bash":
//   command: "\"$CLAUDE_PROJECT_DIR/.venv/bin/wikitoolkit\" claude-hook"  ← KEEP (line ~15)
// PreToolUse[1] matcher "Bash|Edit|Write|MultiEdit":
//   command: "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/dangerous-actions-blocker.sh\""  ← PRESERVE
// PreToolUse[2] matcher "Grep|Glob|Read|Bash"  (DUPLICATE):
//   command: "/home/jesuslara/proyectos/ai-parrot/.venv/bin/wikitoolkit claude-hook"  ← DELETE whole object (lines ~30-39)
// SubagentStop[0] matcher "sdd-worker" → sdd-worker-format.sh              ← PRESERVE
// Stop[0] → sdd-worker-format.sh                                          ← PRESERVE
```

### Does NOT Exist
- ~~A tracked `.mcp.json` on `dev`~~ — untracked/gitignored since `145db5786`
  (`.gitignore:389`). This task must not create or stage it.
- ~~Any other `/home/...` path in a tracked file besides this one hook~~ — this
  duplicate is the only remaining hardcoded path (verified via `git grep /home/`).

---

## Implementation Notes

- Edit precisely; remove the one object plus its trailing/leading comma so the
  `PreToolUse` array stays valid JSON. After editing, the array should contain
  exactly the KEEP hook and the `dangerous-actions-blocker.sh` hook.
- Validate: `python -m json.tool .claude/settings.json` must exit 0.

---

## Acceptance Criteria

- [ ] `.claude/settings.json` contains **no** `/home/` (or any absolute home) path
      (`grep -R "/home/" .claude/settings.json` prints nothing).
- [ ] Exactly **one** `wikitoolkit ... claude-hook` command remains, and it is the
      `$CLAUDE_PROJECT_DIR` form.
- [ ] All other hooks and the `permissions` block are unchanged.
- [ ] `python -m json.tool .claude/settings.json` exits 0 (valid JSON).
- [ ] No unrelated files modified by the commit.

---

## Test Specification

> Deterministic shell assertions (no pytest — static JSON config).

```bash
# valid JSON
python -m json.tool .claude/settings.json >/dev/null

# no hardcoded home path
! grep -R "/home/" .claude/settings.json

# exactly one wiki claude-hook, and it is the portable form
test "$(grep -c 'wikitoolkit.*claude-hook' .claude/settings.json)" -eq 1
grep -q 'CLAUDE_PROJECT_DIR/.venv/bin/wikitoolkit\\?" claude-hook' .claude/settings.json
```

---

## Agent Instructions

1. Read the spec at the path above for full context.
2. `Depends-on` is none — proceed.
3. Verify the Codebase Contract by content (the duplicate hook object) before editing.
4. Update the per-spec index status to `in-progress`.
5. Make the edit per scope; validate JSON.
6. Verify all acceptance criteria.
7. Move this file to `sdd/tasks/completed/TASK-2720-dedupe-settings-wiki-hook.md`.
8. Update the index → `done`.
9. Fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
