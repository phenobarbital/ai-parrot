# TASK-4117: Operator documentation + feature regression gate

**Feature**: FEAT-637 — JiraToolkit Template Support
**Spec**: `sdd/specs/jiratoolkit-template-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4116
**Assigned-to**: unassigned

---

## Context

Implements spec AC17, AC18 and AC19. Writes the operator guide for Jira text
templates and runs the whole feature's test set once more, after every code
task has landed, as the final regression gate.

---

## Scope

- Create `docs/tools/jira-templates.md` with: configuration (`templates_dir`, `JIRA_TEMPLATES_DIR`, `templates=`), precedence, directory layout and convention order per kind, the template context table (spec §2 Data Models), error behaviour (`JiraTemplateError`, `JiraTemplateNotFound`, missing variables, empty render, `fields['description']` conflict, truncation at 32 767 chars), `jira_list_templates`, the auth note (the tool is gated by `_pre_execute` like every tool), and a worked `nav/bug.j2` example written in **Jira wiki markup** (`h2.`, `*bold*`, `{code}`), not Markdown.
- Run the Validation Commands and confirm AC17 with the `git diff` check below.

**NOT in scope**: any code change. If a validation command fails, stop and report it in the Completion Note — do not fix code in this task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/tools/jira-templates.md` | CREATE | operator guide |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none — documentation task
```

### Existing Signatures to Use
Document exactly the names fixed by the spec and created by TASK-4113..4116:
`JiraToolkit(templates_dir=..., templates=...)`, env `JIRA_TEMPLATES_DIR`,
`jira_create_issue / jira_update_issue / jira_add_comment(..., template=, template_params=)`,
`jira_list_templates(project=None)`, `JiraTemplateError`, `JiraTemplateNotFound`.
Existing docs folder: `docs/tools/` (verified; holds e.g. `jira-transition-actions.md`).

### Does NOT Exist
- ~~`JiraToolkitConfig.templates_dir` / an Agent Studio field~~ — not in v1 (spec §8 Q2 is a follow-up); say so in the doc.
- ~~Markdown → Jira conversion~~ — templates must be written in Jira wiki markup.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/tools/jira-templates.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the four implemented code tasks' Completion Notes for any deviation — *why*: the doc must describe what shipped.
2. Write the doc from the skeleton below — *why*: section order mirrors the spec so reviewers can diff behaviour against AC.
3. Run the Validation Commands and the AC17 check.

### `docs/tools/jira-templates.md` (CREATE)
```markdown
# Jira text templates (JiraToolkit)

Compose Jira issue descriptions and comment bodies from Jinja2 templates (FEAT-637).

## Configure
<!-- FILL IN: kwarg vs JIRA_TEMPLATES_DIR precedence; inline `templates=` shadows files; missing dir ⇒ WARNING -->

## Layout and selection
<!-- FILL IN: tree example (_default.j2, comment.j2, update.j2, nav/bug.j2, nav/_default.j2, nav/comment.j2);
     explicit `template=` (with/without .j2) wins; convention order per kind; lower-casing -->

## Template context
<!-- FILL IN: the per-kind key table from spec §2; template_params override; `fields` never included -->

## Errors and limits
<!-- FILL IN: missing variables (all names listed, nothing sent to Jira), empty render, unknown name,
     fields['description'] conflict, comment needs body or template, truncation marker at 32 767 chars -->

## Discovering templates
<!-- FILL IN: jira_list_templates(project=...) return shape -->

## Example: nav/bug.j2
<!-- FILL IN: wiki-markup template + the call that uses it + the rendered result -->

## Not in v1
<!-- FILL IN: Agent Studio field (follow-up), issue metadata in update/comment context (follow-up) -->
```

### FILL IN checklist
- [ ] every section above, consistent with shipped behaviour

---

## Acceptance Criteria

- [ ] `docs/tools/jira-templates.md` covers config, layout, context, errors, listing and a wiki-markup example (spec AC18).
- [ ] `git diff --name-only origin/dev...HEAD` lists none of: `packages/ai-parrot/src/parrot/template/engine.py`, `packages/ai-parrot-tools/src/parrot_tools/jira_config.py`, `packages/ai-parrot/src/parrot/interfaces/jira.py`, `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` (spec AC17).
- [ ] All Validation Commands pass (spec AC19).

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_config.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_render.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_writes.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_list_templates.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py -q`
- `pytest packages/ai-parrot/tests/test_jiratoolkit_permissions.py -q`

Run inside the worktree with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.

---

## Test Specification

No new tests: this task is the feature-level regression gate over the four test modules created by TASK-4113..4116.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4116 is `done`.
2. Mark `in-progress`; write the doc; run the Validation Commands and the AC17 check.
3. Commit only `docs/tools/jira-templates.md`.
4. Close with `scripts/sdd/close_task.sh TASK-4117 jiratoolkit-template-support verified`, fill the Completion Note, commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
