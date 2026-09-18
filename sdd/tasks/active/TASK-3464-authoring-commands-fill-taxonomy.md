# TASK-3464: Authoring commands fill `projects`/`tags` — brainstorm, proposal, fromjira

**Feature**: FEAT-576 — SDD Document Taxonomy (`projects` and `tags` frontmatter)
**Spec**: `sdd/specs/sdd-spec-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3459, TASK-3460
**Assigned-to**: unassigned

---

## Context

Implements the brainstorm/proposal/fromjira half of spec §3 **Module 3** (goal G5, AC6).
These three commands create the exploration docs that `/sdd-spec` later carries forward
(TASK-3465). Each exists in three hand-maintained copies that must all change.

---

## Scope

For each of `sdd-brainstorm`, `sdd-proposal`, `sdd-fromjira`, in **all three** copies:
- Add an instruction to fill `projects` and `tags` in the document frontmatter:
  - `projects`: derived from the doc's Code Context / Localization paths using the
    mapping below; state the chosen values in the command's output summary. Never leave
    `projects: []` when code paths are known.
  - `tags`: propose 2–6 lowercase kebab-case keywords.
  - Values follow the vocabulary in `KNOWN_PROJECTS` (`scripts/sdd/sdd_meta.py`); an unknown
    project is allowed but warns.
- `/sdd-fromjira`'s inline frontmatter example gains `projects:` / `tags:` lines.
- Add each command's output line `Projects: <...>  Tags: <...>`.

**NOT in scope**: `sdd-spec` and `sdd-ideation` (TASK-3465); status/next/tojira (TASK-3466/3467).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-brainstorm.md` | MODIFY | fill step §10 + output |
| `.agent/workflows/sdd-brainstorm.md` | MODIFY | identical edit (twin) |
| `.agents/skills/sdd-brainstorm/SKILL.md` | MODIFY | guardrail bullet |
| `.claude/commands/sdd-proposal.md` | MODIFY | §8 "Set frontmatter" bullets + output |
| `.agent/workflows/sdd-proposal.md` | MODIFY | identical edit (twin) |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | guardrail bullet |
| `.claude/commands/sdd-fromjira.md` | MODIFY | §12 frontmatter example + fill step |
| `.agent/workflows/sdd-fromjira.md` | MODIFY | identical edit (twin) |
| `.agents/skills/sdd-fromjira/SKILL.md` | MODIFY | guardrail bullet |

---

## Codebase Contract (Anti-Hallucination)

### Existing anchors (verified 2026-09-19)
```text
.claude/commands/sdd-brainstorm.md
  :163  ### 10. Save and Commit
  :167-168  "**Update the frontmatter `type` and `base_branch` values to match the\n   user's Round 0 answers.** Do NOT strip the frontmatter."
  :169  "3. Set `Status: exploration`."
  :182  ### 11. Output
.claude/commands/sdd-proposal.md
  :378  "Set frontmatter:"   (followed by three `- status: ...` bullets, :379-381)
  :451  ## Output
.claude/commands/sdd-fromjira.md
  :259  ### 12. Save and Commit
  :270-271  "   type: feature\n   base_branch: dev"   (inside the frontmatter example)
  :272  "   jira: NAV-8036"
  :296  ### 13. Output
.agents/skills/sdd-brainstorm/SKILL.md:28  "- Preserve the YAML frontmatter from the template."
.agents/skills/sdd-proposal/SKILL.md:31   "- Persist state under `sdd/state/<FEAT-ID>/`."
.agents/skills/sdd-fromjira/SKILL.md:22   "- Set flow type in frontmatter: `type: feature, base_branch: dev` (or `hotfix`/`main` for bug tickets)."
```
- `.agent/workflows/<name>.md` differs from `.claude/commands/<name>.md` by exactly ONE line
  today (the "Worktree policy" reference line — sdd-brainstorm:203, sdd-proposal:507,
  sdd-fromjira:336). Apply every edit byte-identically to both so the diff stays one line.
- `.agents/skills/*/SKILL.md` are condensed rewrites (not twins) — add one guardrail bullet each.

### Path → project mapping to quote in the commands (same table as spec §3 M8)
`packages/<dist>/…` → `<dist>`; `packages/ai-parrot-server/ui/` → `admin-ui`; `parrot_tools` /
`parrot_loaders` / `parrot_pipelines` → `ai-parrot-tools` / `ai-parrot-loaders` / `ai-parrot-pipelines`;
`scripts/sdd/`, `.claude/commands/`, `sdd/templates/` → `sdd-tooling`; `flows/dev_loop` →
`dev-loop`; other `parrot/…` → `ai-parrot`. Aliases accepted: `parrot-core`, `formdesigner`.

### Does NOT Exist
- ~~a generator that syncs the three command copies~~ — edit each file by hand
- ~~a byte-parity test for sdd-brainstorm/proposal/fromjira twins~~ — only `sdd-spec`/`sdd-task`
  are parity-tested (`tests/sdd_scripts/test_command_twin_parity.py:20`); keep the twins identical anyway

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-brainstorm.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-brainstorm.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-brainstorm/SKILL.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-proposal.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-proposal.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-proposal/SKILL.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-fromjira.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-fromjira.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-fromjira/SKILL.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit the `.claude/commands/` file, then copy the identical hunk into the `.agent/workflows/` twin — *why*: keeps the twin diff at one line.
2. Add the `.agents/skills` guardrail bullet — *why*: the Codex-side skills are condensed and need only the rule.
3. Verify twin diffs (see Acceptance Criteria) — *why*: catches accidental drift.

### `.claude/commands/sdd-brainstorm.md` + twin (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c "user's Round 0 answers.\*\* Do NOT strip the frontmatter." .claude/commands/sdd-brainstorm.md)
# AFTER — insert below line 168 (`   user's Round 0 answers.** Do NOT strip the frontmatter.`)
   **Fill `projects` and `tags` (FEAT-576).** `projects` lists the parts of the
   codebase this brainstorm concerns — derive them from the Code Context paths
   (`packages/<dist>/…` → `<dist>`; `packages/ai-parrot-server/ui/` → `admin-ui`;
   `parrot_tools`/`parrot_loaders`/`parrot_pipelines` → their `ai-parrot-*` dist;
   `scripts/sdd/`, `.claude/commands/`, `sdd/templates/` → `sdd-tooling`;
   `flows/dev_loop` → `dev-loop`; other `parrot/…` → `ai-parrot`). The vocabulary
   is `KNOWN_PROJECTS` in `scripts/sdd/sdd_meta.py`; an unknown value is allowed
   but warns. `tags`: 2–6 lowercase kebab-case keywords. Never leave
   `projects: []` when the Code Context names code paths.
```
Plus, in `### 11. Output`, add the line `  Projects: <list>   Tags: <list>` to the printed block.
# FILL IN: exact placement inside the Output block — bounded by: add one line, change nothing else

### `.claude/commands/sdd-proposal.md` + twin (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^Set frontmatter:$' .claude/commands/sdd-proposal.md)
# AFTER — the three `- status: …` bullets under `Set frontmatter:` (verified: :378-381), append:
- `projects` / `tags` (FEAT-576): `projects` from §2.1 Localization paths
  (same mapping as `/sdd-brainstorm` §10; vocabulary `KNOWN_PROJECTS` in
  `scripts/sdd/sdd_meta.py`, unknown values warn); `tags`: 2–6 kebab-case keywords.
```
Plus the Output line as above.

### `.claude/commands/sdd-fromjira.md` + twin (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^   jira: NAV-8036$' .claude/commands/sdd-fromjira.md)
# BEFORE — insert above `   jira: NAV-8036` (verified: :272), inside the frontmatter example:
   projects: [ai-parrot-tools]      # FEAT-576 — parts of the codebase (see /sdd-brainstorm §10 mapping)
   tags: [jira, oauth]              # FEAT-576 — 2–6 kebab-case keywords
```
And after the example's "Validation rule" paragraph (:281-282) add one sentence:
`Fill projects/tags per /sdd-brainstorm §10 (FEAT-576) — Jira components are NOT projects.`

### `.agents/skills/*/SKILL.md` (MODIFY — one bullet each, appended to `## Guardrails`)
```markdown
- Fill frontmatter `projects` (parts of the codebase, vocabulary `KNOWN_PROJECTS` in
  `scripts/sdd/sdd_meta.py`; unknown values warn) and `tags` (2–6 kebab-case keywords) — FEAT-576.
```

### FILL IN checklist
- [ ] Output-block line placement in each of the 3 commands (+ twins)

---

## Acceptance Criteria

- [ ] All 9 files instruct filling `projects` and `tags` (AC6)
- [ ] `diff .claude/commands/sdd-X.md .agent/workflows/sdd-X.md` still shows exactly ONE differing line for X ∈ {brainstorm, proposal, fromjira}
- [ ] `tests/sdd_scripts/test_command_contracts.py` passes

---

## Validation Commands
- `pytest tests/sdd_scripts/test_command_contracts.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`

---

## Test Specification

No new test file: these are prompt documents. Verification is the twin diff check in the
Acceptance Criteria plus the existing command-contract tests.

---

## Agent Instructions

1. Read spec §3 Module 3. Confirm TASK-3459 and TASK-3460 are done (the prose cites their vocabulary and template block).
2. Apply edits, run the twin diff + Validation Commands, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
