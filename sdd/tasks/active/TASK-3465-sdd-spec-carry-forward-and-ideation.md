# TASK-3465: `/sdd-spec` carries `projects`/`tags` forward; `sdd-ideation` fills them

**Feature**: FEAT-576 — SDD Document Taxonomy (`projects` and `tags` frontmatter)
**Spec**: `sdd/specs/sdd-spec-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3459, TASK-3460
**Assigned-to**: unassigned

---

## Context

Implements the `/sdd-spec` + dev-loop half of spec §3 **Module 3** (G5, AC6, AC7).
`/sdd-spec` must copy the brainstorm/proposal taxonomy into the spec, and the dev-loop
`sdd-ideation` agent (which writes brainstorms/proposals unattended) must fill it. Both
have byte-parity tests, so edits must be applied identically to their twins.

---

## Scope

- `/sdd-spec` (3 copies): add the carry-forward row to the §2a mapping table, add
  `projects`/`tags` to the §5 frontmatter shape, and add a §5 sanity-check item.
- `sdd-ideation` (4 copies): add `projects: [...]` / `tags: [...]` lines to the Step 3
  frontmatter block plus a one-paragraph fill rule.

**NOT in scope**: brainstorm/proposal/fromjira commands (TASK-3464); `/sdd-task` (no index
header caching — spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-spec.md` | MODIFY | §2a row, §5 frontmatter + sanity check |
| `.agent/workflows/sdd-spec.md` | MODIFY | byte-identical edit (parity-tested) |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | step 10 bullet |
| `.claude/agents/sdd-ideation.md` | MODIFY | Step 3 frontmatter + rule |
| `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` | MODIFY | byte-identical to `.claude/agents/sdd-ideation.md` |
| `.agent/agents/sdd-ideation/agent.md` | MODIFY | same lines (older copy) |
| `.agents/agents/sdd-ideation/agent.md` | MODIFY | same lines (older copy) |

---

## Codebase Contract (Anti-Hallucination)

### Existing anchors (verified 2026-09-19)
```text
.claude/commands/sdd-spec.md
  :70  "| Parallelism Assessment | Worktree Strategy section |"                       (occurrences: 1)
  :71  "| Open Questions (see 2b) | §8 Open Questions (with resolved/unresolved state preserved) |"
  :446 "### 5. Scaffold the Spec"
  :454-461 frontmatter shape block:  ---/type: feature        # or: hotfix/base_branch: dev     # or: main .../# reuse_feature_id .../---
  :532 "4. Before finishing, sanity-check the spec against the brainstorm:"         (occurrences: 1)
.agents/skills/sdd-spec/SKILL.md
  :92  "   - frontmatter `type` and `base_branch`"
.claude/agents/sdd-ideation.md  (386 lines; byte-identical to _subagent_data copy — `cmp` verified)
  :174 "Every document you write starts with the FEAT-145 frontmatter, verbatim:"
  :182 "base_branch: <the payload's `base_branch` value, verbatim — `dev` when it is `dev`>"
  :183 "---"
  :186-187 "`type` is always `feature`; `base_branch` comes from the payload — do not\nhard-code `dev`."
.agent/agents/sdd-ideation/agent.md and .agents/agents/sdd-ideation/agent.md (345 lines each, older)
  :136 "Every document you write starts with the FEAT-145 frontmatter, verbatim:"
  :144 "base_branch: dev"
```
Parity tests that MUST stay green:
- `tests/sdd_scripts/test_command_twin_parity.py` — `.agent/workflows/sdd-spec.md` must equal
  `.claude/commands/sdd-spec.md` after the ONE substitution at :20-33
  (`- Worktree policy: \`CLAUDE.md\` (section "Worktree Policy")` → `AGENTS.md and sdd/WORKFLOW.md`).
- `packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py::test_prompt_parity_with_repo_twin`
  (:260) — `_subagent_data/sdd-ideation.md` == `.claude/agents/sdd-ideation.md`.

### Does NOT Exist
- ~~`projects`/`tags` in the per-spec task index header~~ — explicitly not added (spec Non-Goals)
- ~~a parity test for `.agent/agents/` / `.agents/agents/` ideation copies~~ — update them anyway

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-spec/SKILL.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-ideation.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md", "action": "MODIFY"},
    {"path": ".agent/agents/sdd-ideation/agent.md", "action": "MODIFY"},
    {"path": ".agents/agents/sdd-ideation/agent.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit `.claude/commands/sdd-spec.md`; then apply the SAME hunks to `.agent/workflows/sdd-spec.md` — *why*: the parity test fails on any other difference.
2. Edit `.claude/agents/sdd-ideation.md`; then `cp` it over `_subagent_data/sdd-ideation.md` — *why*: those two must be byte-identical; copying guarantees it.
3. Apply the equivalent lines to the two older ideation copies — *why*: other hosts load them.
4. Run both parity tests.

### `.claude/commands/sdd-spec.md` (MODIFY — §2a table)
```markdown
# occurrences: 1 (verified: grep -c '^| Parallelism Assessment | Worktree Strategy section |$' .claude/commands/sdd-spec.md)
# AFTER — insert below `| Parallelism Assessment | Worktree Strategy section |` (verified: :70)
| Frontmatter `projects` / `tags` (FEAT-576) | Spec frontmatter `projects` / `tags` — verbatim; extend `projects` only with a distribution §4 research shows the feature touches |
```

### `.claude/commands/sdd-spec.md` (MODIFY — §5 frontmatter shape)
```yaml
# occurrences: 1 (verified: grep -c '     base_branch: dev     # or: main (mandatory for hotfix)' .claude/commands/sdd-spec.md)
# AFTER — insert below `     base_branch: dev     # or: main (mandatory for hotfix)` (verified: :456)
     projects: [ai-parrot]  # FEAT-576 — parts of the codebase; carried from the brainstorm/proposal
     tags: [memory]         # FEAT-576 — 2–6 kebab-case keywords; carried from the brainstorm/proposal
```
And after the block's closing fence, add a bullet:
`   - **projects / tags** (FEAT-576): copy from the exploration doc; with no exploration doc, derive projects from §4 research (mapping in /sdd-brainstorm §10) and propose 2–6 tags. Vocabulary: KNOWN_PROJECTS in scripts/sdd/sdd_meta.py (unknown values warn).`
# FILL IN: exact bullet placement right after the frontmatter fence (before "- **Feature ID — SKIP ENTIRELY …") — bounded by: one bullet, identical in the twin

### `.claude/commands/sdd-spec.md` (MODIFY — §5 sanity check)
```markdown
# occurrences: 1 (verified: grep -c '^4. Before finishing, sanity-check the spec against the brainstorm:$' .claude/commands/sdd-spec.md)
# AFTER the whole item 4 paragraph (ends "before committing." at :536), add:
5. Confirm the spec frontmatter carries the exploration doc's `projects` and
   `tags` (FEAT-576) — `python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse_taxonomy; print(parse_taxonomy(Path('<spec>')))"`
   must list at least the carried values.
```

### `.agents/skills/sdd-spec/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'frontmatter `type` and `base_branch`' .agents/skills/sdd-spec/SKILL.md)
# AFTER :92 add:
   - frontmatter `projects` and `tags`, carried from the exploration doc (FEAT-576)
```

### `.claude/agents/sdd-ideation.md` (MODIFY — then copy to `_subagent_data/`)
```markdown
# occurrences: 1 (verified: grep -c "base_branch: <the payload's" .claude/agents/sdd-ideation.md)
# AFTER — insert below :182 (`base_branch: <the payload's …>`), inside the fenced block:
projects: [<parts of the codebase from your Code Context — e.g. ai-parrot, ai-parrot-server>]
tags: [<2–6 lowercase kebab-case keywords>]

# and AFTER :187 (`hard-code \`dev\`.`) add the paragraph:
`projects` / `tags` (FEAT-576): derive `projects` from the Code Context paths
(`packages/<dist>/…` → `<dist>`; `scripts/sdd/`, `.claude/` → `sdd-tooling`;
`flows/dev_loop` → `dev-loop`; other `parrot/…` → `ai-parrot`) using the
`KNOWN_PROJECTS` vocabulary in `scripts/sdd/sdd_meta.py`; when resuming an
existing document, keep its values and only add missing ones.
```

### `.agent/agents/sdd-ideation/agent.md` and `.agents/agents/sdd-ideation/agent.md` (MODIFY)
```markdown
# occurrences: 1 each (verified: grep -c '^base_branch: dev$' <file>)
# AFTER — insert below :144 `base_branch: dev` the same two frontmatter lines; after the block, the same paragraph.
```

### FILL IN checklist
- [ ] §5 bullet placement in sdd-spec (identical in twin)

---

## Acceptance Criteria

- [ ] `/sdd-spec` §2a has the carry-forward row; §5 frontmatter shape and sanity check mention projects/tags (AC7)
- [ ] `test_command_twin_parity.py` passes (AC6)
- [ ] `test_subagent_defs.py::test_prompt_parity_with_repo_twin` passes (AC6)
- [ ] `cmp .claude/agents/sdd-ideation.md packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` exits 0

---

## Validation Commands
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Test Specification

No new tests: the two existing parity tests are the guard. Run them after every edit.

---

## Agent Instructions

1. Read spec §3 Module 3 and §7 (twin parity gotchas). Confirm TASK-3459/3460 done.
2. Apply edits in the Step order; run Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src`).
3. Fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
