---
type: Wiki Overview
title: 'TASK-1699: Update sdd-codereview Subagent Prompt'
id: doc:sdd-tasks-completed-task-1699-update-codereview-subagent-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: N/A — this is a prompt file, not Python code.
---

# TASK-1699: Update sdd-codereview Subagent Prompt

**Feature**: FEAT-270 — Multi-Dispatcher Code Review Gate
**Spec**: `sdd/specs/new-codereviewers.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 8 from the spec — updating the `sdd-codereview`
> subagent prompt to allow fixing issues (Edit/Write tools) and committing
> fixes to the worktree branch, rather than operating read-only.

---

## Scope

- Modify `_subagent_data/sdd-codereview.md`:
  - Remove `permissionMode: plan` from frontmatter (or change to `default`)
  - Update `tools:` to include `Read, Write, Edit, Bash, Grep, Glob`
  - Remove "Read-only" cardinal rule
  - Add "Fix and commit" instructions:
    - When a finding is fixable, fix it using Edit/Write
    - After all fixes, stage and commit to the current branch
    - Report fixed files in `files_modified` field of the verdict
  - Update the output contract to include `files_modified` field
  - Keep the "Judge against acceptance criteria first" rule
  - Keep the AI-Parrot standards checklist
- Write no code tests (this is a prompt file, not code).

**NOT in scope**: Code changes (all other tasks), creating separate prompt files for Codex/Gemini.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-codereview.md` | MODIFY | Update prompt |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
N/A — this is a prompt file, not Python code.

### Existing Signatures to Use
```markdown
# Current frontmatter (packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-codereview.md):
---
name: sdd-codereview
model: sonnet
color: red
permissionMode: plan
tools: Read, Bash, Grep, Glob
---
```

### Does NOT Exist
- ~~`sdd-codereview-codex.md`~~ — no separate Codex prompt file exists or is created by this task
- ~~`sdd-codereview-gemini.md`~~ — no separate Gemini prompt file exists or is created by this task

---

## Implementation Notes

### Key Changes to the Prompt

1. **Frontmatter**: Change `permissionMode: plan` → `permissionMode: default` and
   `tools: Read, Bash, Grep, Glob` → `tools: Read, Write, Edit, Bash, Grep, Glob`

2. **Cardinal rules**: Replace "Read-only" rule with "Fix what you find" rule:
   - Fix issues using Edit/Write when the fix is clear and safe
   - Stage and commit fixes: `git add <files> && git commit -m "codereview: fix <summary>"`
   - If a fix is risky or unclear, report it as a finding instead of fixing

3. **Output contract**: Add `files_modified` field:
   ```json
   {
     "passed": true,
     "findings": [...],
     "summary": "...",
     "files_modified": ["parrot/sync.py", "tests/test_sync.py"]
   }
   ```

4. **Finding format**: Update findings to include severity, file, line:
   ```json
   {
     "passed": false,
     "findings": [
       {"message": "Missing null guard", "severity": "critical", "file": "sync.py", "line": 88}
     ],
     "summary": "...",
     "files_modified": []
   }
   ```

### Key Constraints
- The prompt must work with Claude Code's subagent system — it's loaded by
  `ClaudeCodeDispatcher` from `_subagent_data/`
- Codex and Gemini dispatchers will also use this prompt (loaded as system instruction)
  so keep it generic — no Claude-specific references
- Commit messages should use a recognizable prefix (e.g. `codereview:`) so the
  QA re-run can distinguish reviewer commits from developer commits

---

## Acceptance Criteria

- [ ] `permissionMode` changed to `default` (or removed)
- [ ] `tools` includes `Write` and `Edit`
- [ ] "Read-only" rule removed from cardinal rules
- [ ] "Fix and commit" instructions added
- [ ] Output contract updated with `files_modified` and structured findings
- [ ] Prompt is vendor-neutral (no Claude-specific references)

---

## Agent Instructions

When you pick up this task:

1. **Read** the current `sdd-codereview.md` file fully
2. **Update status** in `sdd/tasks/index/new-codereviewers.json` → `"in-progress"`
3. **Modify** the prompt per scope above
4. **Verify** acceptance criteria are met by reviewing the file
5. **Move this file** to `sdd/tasks/completed/TASK-1699-update-codereview-subagent.md`
6. **Update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Frontmatter: `permissionMode: plan` → `default`, `tools: Read, Bash,
Grep, Glob` → `Read, Write, Edit, Bash, Grep, Glob`. Replaced the "Read-only"
cardinal rule with "Fix what you find" / "Stage and commit your fixes" /
"Report every file you touched" rules (`codereview:` commit-message prefix).
Kept "Judge against the acceptance criteria first" and the AI-Parrot
standards checklist unchanged. Updated the Output Contract: `findings` is
now a list of `{message, severity, file, line}` objects (matching
`CodeReviewFinding`) instead of plain strings, and added `files_modified`.
Added step 4-5 to the Steps section (apply safe fixes, commit them) before
the verdict decision step. Kept the prompt vendor-neutral (no Claude-specific
references) since Codex/Gemini also load it as their system instruction, per
the task's constraint.

**Deviations from spec**: Updated
`test_subagent_codereview.py::test_codereview_body_is_read_only_posture`
(not in this task's file list) — it asserted `"read-only" in body`, which is
exactly the phrase this task requires removing. Renamed it to
`test_codereview_body_is_write_enabled_posture`, asserting the new
`fix`/`commit`/`files_modified` vocabulary instead. Left
`_subagent_defs.py`'s module docstring (still says "read-only qualitative
code-review gate") untouched — it's an unenforced doc comment with no test
coverage, so leaving it stale poses no regression risk and touching it would
exceed this task's file list without a test-driven reason.
