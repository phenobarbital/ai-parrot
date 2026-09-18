# TASK-3467: `/sdd-tojira` — map `projects ∪ tags` to Jira labels

**Feature**: FEAT-576 — SDD Document Taxonomy (`projects` and `tags` frontmatter)
**Spec**: `sdd/specs/sdd-spec-changes.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3459
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 7** (G8, AC10). Exported Stories get the spec's projects and tags
as Jira labels so Jira boards can be filtered the same way as `/sdd-status`. Labels already
on a ticket (human-added) must never be removed on UPDATE.

---

## Scope

In all three copies of `sdd-tojira`:
- Extraction table (§2): add a row `Frontmatter projects/tags | projects ∪ tags (sorted, deduped) | Jira labels`.
- Describe how to compute the labels:
  `python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse_taxonomy; t = parse_taxonomy(Path('<spec>')); print(' '.join(sorted(set(t.projects + t.tags))))"`.
- CREATE (MCP + curl): add `labels`.
- UPDATE (MCP + curl): **add** labels with the Jira `update` verb (`{"update": {"labels": [{"add": "<l>"}, …]}}`),
  never `fields.labels` (which would replace existing labels).
- No prefix on project labels (v1 default; spec §8 Q "prefix labels" remains open).

**NOT in scope**: Jira components (stay `Nav-AI`); subtask labels.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-tojira.md` | MODIFY | table row, label computation, create/update payloads |
| `.agent/workflows/sdd-tojira.md` | MODIFY | identical edit (twin) |
| `.agents/skills/sdd-tojira/SKILL.md` | MODIFY | workflow step 3 bullet |

---

## Codebase Contract (Anti-Hallucination)

### Existing anchors (verified 2026-09-19)
```text
.claude/commands/sdd-tojira.md
  :131  ### 2. Extract Spec Content
  :139  "| Components | Module Breakdown / Impact | Jira components |"          (occurrences: 1)
  :193  '    components="Nav-AI",'          (MCP create; occurrences: 1)
  :209  '      "components": [{"name": "Nav-AI"}],'   (curl create; occurrences: 1)
  :216  #### If MODE = UPDATE
  :221-222 "Only update description, AC, estimate, and components."
  :225-229 jira_update_issue(... additional_fields='{"timeoriginalestimate": "<TOTAL_SECONDS>"}')
  :233-243 curl -X PUT ... '{"fields": {"description": ..., "timeoriginalestimate": 28800}}'
.agents/skills/sdd-tojira/SKILL.md  workflow step 3 "Create or update Story:" / "- Set summary, description, component, and AC."
```
- Twin differs by one line today (:433 "Auto-commit rule" line). Keep it that way.
- `parse_taxonomy` is importable via `scripts.sdd.sdd_meta` once TASK-3459 lands.

### Does NOT Exist
- ~~a `labels=` keyword on `jira_create_issue`~~ — pass labels inside `additional_fields` JSON:
  `additional_fields='{"labels": ["ai-parrot", "memory"], "timeoriginalestimate": "<TOTAL_SECONDS>"}'`
  *(unverified against the live Jira MCP server — the implementer must check the tool schema
  and adjust; record the result in the Completion Note)*

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-tojira.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-tojira.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-tojira/SKILL.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the table row and a "Labels" paragraph with the `parse_taxonomy` one-liner after the table — *why*: one computation shared by create and update.
2. Add `labels` to both CREATE payloads — *why*: AC10.
3. Add the additive `update.labels` form to both UPDATE payloads and amend :221-222 to say "and add labels (never remove)" — *why*: AC10's no-removal rule.
4. Mirror to the twin; add the SKILL bullet.

### `.claude/commands/sdd-tojira.md` + twin (MODIFY — table)
```markdown
# occurrences: 1 (verified: grep -c '^| Components | Module Breakdown / Impact | Jira components |$' .claude/commands/sdd-tojira.md)
# AFTER :139 insert:
| Labels (FEAT-576) | Frontmatter `projects` ∪ `tags` (sorted, deduped) | Jira labels |
```

### CREATE payloads (MODIFY)
```text
# MCP (:193) — AFTER `    components="Nav-AI",` change the additional_fields line to include "labels": [<labels>]
# curl (:209) — AFTER `      "components": [{"name": "Nav-AI"}],` insert:
      "labels": ["ai-parrot", "memory"],
```

### UPDATE payloads (MODIFY)
```text
# curl PUT body becomes:
  -d '{
    "fields": {
      "description": {"type": "doc", "version": 1, "content": [...]},
      "timeoriginalestimate": 28800
    },
    "update": {"labels": [{"add": "ai-parrot"}, {"add": "memory"}]}
  }'
# MCP: FILL IN — use the jira_update_issue form that ADDS labels (check the MCP tool schema) — bounded by AC10 (never remove existing labels)
```

### `.agents/skills/sdd-tojira/SKILL.md` (MODIFY)
```markdown
# AFTER "- Set summary, description, component, and AC." add:
   - Add labels = frontmatter `projects` ∪ `tags` (FEAT-576); on update only add, never remove.
```

### FILL IN checklist
- [ ] MCP update form for additive labels (verify tool schema)

---

## Acceptance Criteria

- [ ] CREATE sends `labels` from `projects ∪ tags` (AC10)
- [ ] UPDATE only adds labels, never replaces (AC10)
- [ ] Twin diff remains exactly one line
- [ ] `tests/sdd_scripts/test_command_contracts.py` passes

---

## Validation Commands
- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Test Specification

No new test file (prompt document). Verify the `parse_taxonomy` one-liner on
`sdd/specs/sdd-spec-changes.spec.md` prints `ai-parrot frontmatter sdd sdd-tooling taxonomy templates`
and record it in the Completion Note.

---

## Agent Instructions

1. Read spec §3 Module 7. Confirm TASK-3459 is done.
2. Apply edits; run the one-liner and Validation Commands; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
