---
type: Wiki Overview
title: 'TASK-1576: Composite skill — structured operation response'
id: doc:sdd-tasks-completed-task-1576-skill-structured-operation-response-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 7** of the spec — a composite file-based skill instructing
  the
---

# TASK-1576: Composite skill — structured operation response

**Feature**: FEAT-240 — Odoo PageIndex Documentation Agent
**Spec**: `sdd/specs/odoo-pageindex-documentation-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of the spec — a composite file-based skill instructing the
agent that "how do I do X in Odoo" questions are answered as an **ordered bullet
list** of concrete, version-aware steps grounded in the documentation PageIndex.
Loaded by the agent's Skill Registry (TASK-1574). Resolves part of G10 / AC11.

---

## Scope

- Create `agents/odoo_agent/skills/structured-operation-response/SKILL.md`
  (composite layout) with valid frontmatter (name, description, trigger/`/command`)
  and a body that defines the response contract:
  - Detect "how do I … in Odoo" / operational how-to questions.
  - Respond with an **ordered** (numbered) bullet list of steps.
  - Ground each step in the PageIndex; call out version differences (16 XML-RPC vs
    18/19 JSON-RPC/REST) when relevant.
  - Note when a step is a write that will require HITL confirmation.

**NOT in scope**: the agent wiring (TASK-1574); the install-module skill (TASK-1575).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/odoo_agent/skills/structured-operation-response/SKILL.md` | CREATE | Composite skill definition |

---

## Codebase Contract (Anti-Hallucination)

Documentation/markdown deliverable — no `parrot.*` imports. Contract is the skill
file format, verified from existing composite skills:

```
agents/<agent_id>/skills/<name>/SKILL.md   # composite layout
```

Reference real examples:
- `agents/troc_finance/skills/ebitda_by_division/SKILL.md`
- `agents/troc_finance/skills/revenue_by_division/SKILL.md`

Mirror their frontmatter shape exactly (read one before writing).

### Does NOT Exist
- ~~a JSON skill schema~~ — skills are Markdown + YAML frontmatter.

---

## Implementation Notes

### Key Constraints
- Frontmatter must parse (match an existing composite skill's keys verbatim).
- The skill is behavioural guidance only — it shapes *output format*, it does not
  call tools.
- Be explicit that the list must be **ordered/numbered** steps.

### References in Codebase
- `agents/troc_finance/skills/*/SKILL.md` — composite skill format to copy.

---

## Acceptance Criteria

- [ ] `agents/odoo_agent/skills/structured-operation-response/SKILL.md` exists with valid frontmatter.
- [ ] Body specifies ordered/numbered bullet-list responses, PageIndex-grounded, version-aware.
- [ ] Frontmatter keys match an existing composite skill (parses under the loader).
- [ ] Discoverable by `SkillsDirectoryLoader`.

---

## Test Specification

```python
from pathlib import Path
import yaml

def test_structured_response_skill_frontmatter():
    p = Path("agents/odoo_agent/skills/structured-operation-response/SKILL.md")
    text = p.read_text()
    assert text.startswith("---")
    fm = yaml.safe_load(text.split("---")[1])
    assert "name" in fm and "description" in fm
```

---

## Agent Instructions

1. Read the spec (§3 Module 7) and one existing composite `SKILL.md` first.
2. Update index status → `in-progress`.
3. Author the skill per scope, matching the existing frontmatter shape.
4. Verify acceptance criteria (frontmatter parses).
5. Move this file to `sdd/tasks/completed/`.
6. Update index → `done`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-16
**Notes**: Created `agents/odoo_agent/skills/structured-operation-response/SKILL.md` with valid frontmatter. Body specifies ordered/numbered steps, PageIndex grounding requirement, version-awareness (16 XML-RPC vs 18/19 JSON-RPC/REST), HITL write-operation flagging, and gap learning protocol. Frontmatter parses correctly.

**Deviations from spec**: none
