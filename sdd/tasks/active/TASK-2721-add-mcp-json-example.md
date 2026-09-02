# TASK-2721: Add a tracked `.mcp.json.example` with the portable `sh -c` resolver

**Feature**: FEAT-495 — Portable wikitoolkit config paths
**Spec**: `sdd/specs/portable-wikitoolkit-config-paths.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements Spec §2 / §3 Module 2.

On `dev`, the real `.mcp.json` is intentionally local-only (untracked +
gitignored via `145db5786` / `.gitignore:389`), so a fresh checkout has no
wikitoolkit MCP server until the developer creates one. This task adds a
**tracked** `.mcp.json.example` a developer copies once
(`cp .mcp.json.example .mcp.json`) to get a working, path-independent config with
no hand-editing — from the repo root, a subdirectory, or a worktree.

The example uses the verified `sh -c` spawn-time resolver (brainstorm Option B,
commit `856faec5a`). Empirical verification (brainstorm "Verification Results",
Claude Code 2.1.258) proved the simpler `${CLAUDE_PROJECT_DIR:-.}` form does NOT
work: bare `${CLAUDE_PROJECT_DIR}` is passed verbatim (ENOENT) and
`${CLAUDE_PROJECT_DIR:-.}` collapses to a cwd-relative `.` that breaks from
subdirectories and venv-less worktrees.

---

## Scope

- Create `.mcp.json.example` at the **repo root** containing exactly one
  `mcpServers.wikitoolkit` stdio entry using the `sh -c` + `git rev-parse`
  resolver (see Codebase Contract for the verbatim block).
- The file must be **strict, valid JSON** (no comments) so `cp .mcp.json.example
  .mcp.json` yields a file Claude Code parses.
- The file must contain **no** `/home/...` (or any absolute home) path.

**NOT in scope**: editing `.gitignore` (the `.mcp.json` rule stays; `.example`
is a different path and is not matched by it — verify). Do NOT create or stage a
real `.mcp.json`. Do NOT modify `.claude/settings.json` (that is TASK-2720). Do
NOT add onboarding docs / README (deferred — minimal scope).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.mcp.json.example` | CREATE | Tracked template with the `sh -c` resolver; copied by devs to local `.mcp.json` |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-09-01.

### Exact content to write into `.mcp.json.example`
(verbatim `sh -c` resolver retrieved via `git show 856faec5a:.mcp.json`)
```json
{
  "mcpServers": {
    "wikitoolkit": {
      "type": "stdio",
      "command": "sh",
      "args": [
        "-c",
        "r=\"$CLAUDE_PROJECT_DIR\"; [ -x \"$r/.venv/bin/wikitoolkit\" ] || r=\"$(git rev-parse --show-toplevel 2>/dev/null)\"; [ -x \"$r/.venv/bin/wikitoolkit\" ] || r=\"$(cd \"$(git rev-parse --git-common-dir 2>/dev/null)/..\" 2>/dev/null && pwd)\"; cd \"$r\" && exec \"$r/.venv/bin/wikitoolkit\" mcp"
      ],
      "env": {}
    }
  }
}
```

### Verified facts
- `.gitignore:389` = `.mcp.json` (exact match). `.mcp.json.example` is a distinct
  path and is NOT ignored — confirm with `git check-ignore .mcp.json.example`
  (must print nothing).
- `.venv/bin/wikitoolkit` exists and is executable at the repo root.

### Does NOT Exist
- ~~`${CLAUDE_PROJECT_DIR}` / `${CLAUDE_PROJECT_DIR:-.}` expansion in `.mcp.json`
  command/args/env~~ — verified NOT to work on 2.1.258. Do NOT use it in the
  example.
- ~~An existing `.mcp.json.example` or any tracked `.mcp.json*`~~ — none on `dev`;
  this task creates the first.

---

## Implementation Notes

- Copy the JSON block from the Codebase Contract verbatim — do NOT "tidy" or
  reformat the `sh -c` one-liner (its illegibility is what got it clobbered
  before; keep it exact).
- Validate: `python -m json.tool .mcp.json.example` must exit 0.

---

## Acceptance Criteria

- [ ] `.mcp.json.example` exists at the repo root and is valid JSON
      (`python -m json.tool .mcp.json.example` exits 0).
- [ ] It is **tracked** / not ignored (`git check-ignore .mcp.json.example` prints
      nothing).
- [ ] It contains **no** `/home/` path and uses the `sh -c` resolver (not a bare
      `${CLAUDE_PROJECT_DIR}` command).
- [ ] `.mcp.json` remains untracked/gitignored (`.gitignore` unchanged).
- [ ] Manual verification: `cp .mcp.json.example .mcp.json`, then a Claude Code
      session started from the repo root AND from a subdirectory connects to the
      `wikitoolkit` MCP server. (Clean up the local `.mcp.json` afterward if
      undesired.)
- [ ] No unrelated files modified by the commit.

---

## Test Specification

```bash
# valid JSON
python -m json.tool .mcp.json.example >/dev/null

# tracked (not ignored)
test -z "$(git check-ignore .mcp.json.example)"

# no hardcoded home path; uses the sh -c resolver
! grep -q "/home/" .mcp.json.example
grep -q 'git rev-parse --show-toplevel' .mcp.json.example

# real .mcp.json stays ignored
git check-ignore -q .mcp.json
```

---

## Agent Instructions

1. Read the spec at the path above for full context.
2. `Depends-on` is none — proceed (independent of TASK-2720).
3. Verify the Codebase Contract (gitignore rule, venv binary) before writing.
4. Update the per-spec index status to `in-progress`.
5. Create `.mcp.json.example` per scope; validate JSON.
6. Verify all acceptance criteria.
7. Move this file to `sdd/tasks/completed/TASK-2721-add-mcp-json-example.md`.
8. Update the index → `done`.
9. Fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
