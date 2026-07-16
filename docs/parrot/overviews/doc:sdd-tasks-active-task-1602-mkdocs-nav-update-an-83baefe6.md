---
type: Wiki Overview
title: 'TASK-1602: mkdocs.yml Nav Update & Page Cleanup'
id: doc:sdd-tasks-active-task-1602-mkdocs-nav-update-and-cleanup-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: '"Bots & Agents" nav sections:'
---

# TASK-1602: mkdocs.yml Nav Update & Page Cleanup

**Feature**: FEAT-249 — Update AgentCrew & AgentsFlow Documentation
**Spec**: `sdd/specs/update-agentcrew-agentflow-documentation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1599, TASK-1600, TASK-1601
**Assigned-to**: unassigned

---

## Context

> This task implements Module 4 from the spec. It updates the mkdocs.yml
> navigation structure to point to the three new guides created by
> TASK-1599/1600/1601, removes the superseded pages, and ensures the nav
> structure is clean and consistent.

---

## Scope

- Update `mkdocs.yml` to restructure the "Orchestration & Flows" and
  "Bots & Agents" nav sections:

  **New "Orchestration & Flows" section:**
  ```yaml
  - Orchestration & Flows:
      - AgentCrew Guide: orchestration/agentcrew.md
      - AgentsFlow Guide: orchestration/agentsflow.md
      - Node Types Reference: orchestration/node-types.md
      - Decision Node Usage: DECISION_NODE_USAGE.md
      - Bot Cleanup Lifecycle: bot-cleanup-lifecycle.md
  ```

  **Updated "Bots & Agents" section** — remove superseded entries:
  - Remove: `Crews: crew.md`
  - Remove: `Crew Summary: crew_summary.md`
  - Remove: `Orchestration: orchestration.md`
  - Remove: `Advanced Orchestration: ORCHESTRATION.md`
  - Keep: `Crew Handler: crew_handler.md` (handler-specific, different audience)
  - Keep all other entries unchanged

- Delete superseded files:
  - `docs/crew.md` (superseded by `orchestration/agentcrew.md`)
  - `docs/ORCHESTRATION.md` (superseded by new guides)
  - `docs/orchestration.md` (Spanish-language, superseded)
  - `docs/crew_summary.md` (folded into `orchestration/agentcrew.md`)

- Verify `mkdocs build --strict` passes after all changes.

**NOT in scope**:
- Modifying any of the three new guide files (those are done by TASK-1599/1600/1601)
- Modifying `docs/crew_handler.md`
- Modifying `docs/DECISION_NODE_USAGE.md`
- Modifying `docs/EXECUTION_MEMORY.md`
- Modifying architecture docs (`docs/architecture/07-agentcrew.md`, `08-agentsflow-dag.md`)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `mkdocs.yml` | MODIFY | Update nav structure |
| `docs/crew.md` | DELETE | Superseded by `orchestration/agentcrew.md` |
| `docs/ORCHESTRATION.md` | DELETE | Superseded by new guides |
| `docs/orchestration.md` | DELETE | Spanish-language, superseded |
| `docs/crew_summary.md` | DELETE | Folded into `orchestration/agentcrew.md` |

---

## Codebase Contract (Anti-Hallucination)

### Verified File Locations

```
# Files that MUST exist before this task runs (created by prior tasks)
docs/orchestration/agentcrew.md    # created by TASK-1600
docs/orchestration/agentsflow.md   # created by TASK-1601
docs/orchestration/node-types.md   # created by TASK-1599

# Files that MUST still exist after this task (NOT to be deleted)
docs/crew_handler.md               # handler-specific, different audience
docs/DECISION_NODE_USAGE.md        # deep-dive on DecisionFlowNode
docs/EXECUTION_MEMORY.md           # memory docs, separate concern
docs/architecture/07-agentcrew.md  # internal architecture reference
docs/architecture/08-agentsflow-dag.md  # internal architecture reference
docs/bot-cleanup-lifecycle.md      # lifecycle docs
```

### Current mkdocs.yml Nav Structure (to be modified)

The current nav has these sections that need changes:

```yaml
# In "Bots & Agents" — lines to REMOVE:
- Crews: crew.md                    # line ~143
- Crew Summary: crew_summary.md     # line ~145
- Orchestration: orchestration.md   # line ~146
- Advanced Orchestration: ORCHESTRATION.md  # line ~147

# In "Orchestration & Flows" — REPLACE entire section:
# Current (lines ~193-198):
- Orchestration & Flows:
    - Decision Nodes: DECISION_NODE_USAGE.md
    - Bot Cleanup Lifecycle: bot-cleanup-lifecycle.md
    - ...
```

### Does NOT Exist

- ~~`docs/orchestration/index.md`~~ — not needed; no index page for this section
- ~~`docs/flows.md`~~ — does not exist and should not be created

---

## Implementation Notes

### Step-by-step

1. **Verify prerequisites**: confirm `docs/orchestration/agentcrew.md`,
   `docs/orchestration/agentsflow.md`, and `docs/orchestration/node-types.md`
   all exist.
2. **Update mkdocs.yml**: modify the nav sections as specified in the scope.
3. **Delete superseded files**: `git rm` the four files listed above.
4. **Run `mkdocs build --strict`**: verify no broken links or warnings.
5. **Fix any build issues**: typically broken cross-references from other
   pages that linked to the deleted files.

### Key Constraints

- Use `git rm` to delete files (so git tracks the removal).
- After deleting files, check if any OTHER docs reference them:
  ```bash
  grep -rn "crew\.md\|ORCHESTRATION\.md\|orchestration\.md\|crew_summary\.md" docs/ mkdocs.yml
  ```
  If any remaining docs link to the deleted pages, update those links to point
  to the appropriate new guide.
- The nav order should be: AgentCrew → AgentsFlow → Node Types → Decision
  Node Usage → Bot Cleanup Lifecycle (general → specific → reference → legacy).
- Keep the "Infographic Handler API", "VectorStore Handler API", and
  "Jira Specialist Prompt Layers" entries somewhere sensible (they were in the
  old "Orchestration & Flows" section but aren't orchestration docs — move
  them to "Advanced" or keep in the section if they fit).

### References in Codebase

- `mkdocs.yml` — lines 114-227 (nav section)

---

## Acceptance Criteria

- [ ] `mkdocs.yml` nav updated with new "Orchestration & Flows" section
- [ ] Superseded pages deleted: `crew.md`, `ORCHESTRATION.md`, `orchestration.md`, `crew_summary.md`
- [ ] `docs/crew_handler.md` still exists and is in the nav
- [ ] `docs/DECISION_NODE_USAGE.md` still exists and is in the nav
- [ ] No broken cross-references from other docs to the deleted pages
- [ ] `mkdocs build --strict` passes with no errors or warnings
- [ ] Non-orchestration entries previously in "Orchestration & Flows" are
      moved to an appropriate nav section

---

## Test Specification

```bash
# Build docs
source .venv/bin/activate
mkdocs build --strict

# Verify deleted files are gone
ls docs/crew.md docs/ORCHESTRATION.md docs/orchestration.md docs/crew_summary.md 2>&1
# Expected: all "No such file or directory"

# Verify new files are in the nav
grep -n "orchestration/agentcrew.md\|orchestration/agentsflow.md\|orchestration/node-types.md" mkdocs.yml
# Expected: three matches

# Verify no dangling references to deleted files
grep -rn "crew\.md\b\|ORCHESTRATION\.md\b\|orchestration\.md\b\|crew_summary\.md\b" docs/ mkdocs.yml | grep -v "\.pyc\|\.git"
# Expected: no output (or only in comments)

# Verify preserved files are still in nav
grep -n "crew_handler\.md\|DECISION_NODE_USAGE\.md" mkdocs.yml
# Expected: both present
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/update-agentcrew-agentflow-documentation.spec.md`
2. **Check dependencies** — verify TASK-1599, TASK-1600, TASK-1601 are in `sdd/tasks/completed/`
3. **Verify prerequisites** — confirm the three new guide files exist
4. **Update `mkdocs.yml`** nav as specified
5. **Delete superseded files** with `git rm`
6. **Check for dangling references** in other docs
7. **Run `mkdocs build --strict`** and fix any issues
8. **Verify** all acceptance criteria are met
9. **Move this file** to `sdd/tasks/completed/TASK-1602-mkdocs-nav-update-and-cleanup.md`
10. **Update index** → `"done"`
11. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
