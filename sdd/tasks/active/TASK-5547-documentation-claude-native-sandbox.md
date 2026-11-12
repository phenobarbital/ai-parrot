# TASK-5547: Documentation — wiki/sdd-tooling/dev_loop/claude-native-sandbox.md

**Feature**: FEAT-881 — Legacy shell-prefix fixes
**Spec**: `sdd/specs/scripts-native-claude-sandbox-fixes.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5545, TASK-5546
**Assigned-to**: unassigned
**Discovered-from**: `issue:1f3a8f42fbc6`

---

## Context

Spec §2 M5 / `docs.policy: required`. The page's "Legacy shell prefix" section describes the old behaviour.

---

## Scope

- Update "Legacy shell prefix": MCP servers come from the primary `.mcp.json` via `--mcp-config` + `--strict-mcp-config` (no copy into the worktree); runtime copy in the session directory; hook-only token; hook-side validation; minimum Claude Code 2.1.321; `owner.pid` session expiry.
- Add `--strict-mcp-config` to the rejected caller options list.

**NOT in scope**: Any other wiki page; any code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md` | MODIFY | legacy shell prefix section + launcher reference |

---

## Codebase Contract (Anti-Hallucination)

Verified against `2d45f09fd9`.

### Verified Imports
```python
# No new imports from other packages: both scripts are standard-library only.
```

### Existing Signatures to Use
```python
# wiki/sdd-tooling/dev_loop/claude-native-sandbox.md
### Legacy shell prefix            # line 81
### `launch_worker.sh` reference   # line 145 — "Rejected caller options" bullet at 149
```

### Does NOT Exist
- ~~a separate wiki page for the shell prefix~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/sdd-tooling/dev_loop/claude-native-sandbox.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Standard library only; the module also runs as a script (keep the `if __package__: … else: …` import pairs).
- Google-style docstrings and type hints on every new function; 120-column lines.
- These files are the sandbox's own policy: implement from a host session, never a sandboxed `sdd-worker`.
- In a worktree run pytest with an ABSOLUTE `PYTHONPATH=<worktree>/packages/ai-parrot/src`.

---

## Implementation Blueprint

### Steps (in order)
1. Rewrite the affected sentences in place — *why*: the page is the operator reference; the old text tells them servers are recorded from the worktree.
2. Run the techwiki check — *why*: it is this task's gate.

### `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '### Legacy shell prefix') -->
<!-- FILL IN: revise the paragraph under that heading and the rejected-options bullet — bounded by the Scope list -->
```
**Why**: documentation must match the shipped launcher.

### FILL IN checklist
- [ ] the revised paragraphs

---

## Acceptance Criteria

- [ ] The page states where MCP servers are read from and that no `.mcp.json` copy is needed.
- [ ] `parrot sdd techwiki check --spec <spec> --root .` passes.
- [ ] `ruff check` is clean on the changed files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_shell_prefix.py -q`

Also: `parrot sdd techwiki check --spec sdd/specs/scripts-native-claude-sandbox-fixes.spec.md --root .` (documentation gate, run alongside)

---

## Test Specification

```python
# documentation only — no new test
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug scripts-native-claude-sandbox-fixes --feature-id FEAT-881`).
2. Check every `Depends-on` task is `done` in `sdd/tasks/index/scripts-native-claude-sandbox-fixes.json`.
3. Verify the Codebase Contract, mark the task `in-progress`, implement from the blueprint.
4. Run the Validation Commands, commit only the listed files.
5. Close with `parrot sdd task close TASK-5547 scripts-native-claude-sandbox-fixes verified`, fill the Completion Note, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
