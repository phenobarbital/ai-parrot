# HOTFIX-e009ded74983-1: PreToolUse write guard for E2E exploration agents

**Feature**: e2e-explorer-write-scope (BRIEF-e009ded74983)
**Spec**: sdd/briefs/e2e-explorer-write-scope.brief.md
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context
`e2e-api-tester` / `e2e-ui-tester` can `Write` anywhere. Restrict file-writing tools to
`sdd/state/FEAT-*/e2e/exploration/` using an agent-frontmatter PreToolUse hook (precedent:
`.claude/agents/sdd-coder.md:16-22`).

## Scope
- New hook script `.claude/hooks/e2e-exploration-write-guard.sh`: read JSON from stdin, take
  `tool_input.file_path` (or `notebook_path`), resolve it against `$CLAUDE_PROJECT_DIR`
  (realpath, normalizing `..`/symlinks), allow only paths under
  `$CLAUDE_PROJECT_DIR/sdd/state/FEAT-*/e2e/exploration/`; otherwise print reason to
  stderr and `exit 2`. Missing/unparseable path → block (fail closed).
- Add to both agent frontmatters:
  ```yaml
  hooks:
    PreToolUse:
      - matcher: "Write|Edit|MultiEdit|NotebookEdit"
        hooks:
          - type: command
            command: 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/e2e-exploration-write-guard.sh"'
            timeout: 10
  ```
- One sentence in each agent's "Report contract" section: Write is hook-confined to the
  exploration directory; Bash writes remain prompt-discipline only.
- Test `tests/sdd/test_e2e_exploration_write_guard.py` (subprocess the script): allowed path
  → 0; `tests/test_x.py` → 2; `sdd/state/FEAT-1/e2e/exploration/../../../../tests/x.py` → 2;
  absolute path outside repo → 2; empty payload → 2.

**NOT in scope**: restricting Bash; changing evidence.py / ScenarioSpec; settings.json.

## Files to Create / Modify
- CREATE `.claude/hooks/e2e-exploration-write-guard.sh` (chmod +x; `git add -f` if ignored)
- MODIFY `.claude/agents/e2e-api-tester.md`, `.claude/agents/e2e-ui-tester.md`
- CREATE `tests/sdd/test_e2e_exploration_write_guard.py`

## Codebase Contract
- Verified: `.claude/agents/e2e-api-tester.md:26` and `e2e-ui-tester.md:29` = `tools: Read, Bash, Glob, Grep, Write`.
- Verified: frontmatter hooks pattern at `.claude/agents/sdd-coder.md:16-22`.
- Does NOT exist: any write-path guard for these agents.

## Acceptance Criteria
- Both agents block Write outside `sdd/state/FEAT-*/e2e/exploration/`; allowed writes still succeed.
- Traversal and symlink escapes are blocked. The guard blocks (fails closed) when the input is bad.
- Tests pass.

## Validation Commands
- `pytest tests/sdd/test_e2e_exploration_write_guard.py -q`

## Completion Note
