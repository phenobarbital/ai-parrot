---
type: Wiki Overview
title: 'TASK-1575: Composite skill — install an Odoo module'
id: doc:sdd-tasks-completed-task-1575-skill-install-odoo-module-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 6** of the spec — a composite file-based skill teaching
  the
---

# TASK-1575: Composite skill — install an Odoo module

**Feature**: FEAT-240 — Odoo PageIndex Documentation Agent
**Spec**: `sdd/specs/odoo-pageindex-documentation-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec — a composite file-based skill teaching the
agent how to install a new Odoo module, via the `odoo-bin`/`odoo-cli` shell tools
(TASK-1571) and via Apps/RPC where applicable. Loaded by the agent's Skill
Registry (TASK-1574). Resolves part of G10 / AC11.

---

## Scope

- Create `agents/odoo_agent/skills/install-odoo-module/SKILL.md` (composite layout)
  with valid frontmatter (name, description, trigger/`/command`) and a body that
  walks through: prerequisites, locating the module, installing via
  `odoo_shell_install_module` (or `odoo-bin -i`), restart, and verification.
- Optionally add adjacent asset files (e.g. an example command snippet) referenced
  from the skill.

**NOT in scope**: the agent wiring (TASK-1574); the shell tools (TASK-1571); the
structured-response skill (TASK-1576).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/odoo_agent/skills/install-odoo-module/SKILL.md` | CREATE | Composite skill definition |
| `agents/odoo_agent/skills/install-odoo-module/example.md` | CREATE (optional) | Example asset |

---

## Codebase Contract (Anti-Hallucination)

This is a documentation/markdown deliverable — no `parrot.*` imports. The contract
is the **skill file format**, verified from existing composite skills:

```
agents/<agent_id>/skills/<name>/SKILL.md   # composite layout (verified discovery
                                           # supports single-file {name}.md AND
                                           # composite {name}/SKILL.md + assets)
```

Reference real examples in the repo:
- `agents/troc_finance/skills/consolidated_brand/SKILL.md`
- `agents/troc_finance/skills/revenue_by_division/SKILL.md`

Mirror their frontmatter shape exactly (read one before writing).

### Does NOT Exist
- ~~a JSON skill schema~~ — skills are Markdown + YAML frontmatter.
- ~~RPC-only module install~~ — module install requires the shell tools (TASK-1571)
  or the Odoo Apps UI; reference `odoo_shell_install_module` for the programmatic path.

---

## Implementation Notes

### Key Constraints
- Frontmatter must parse (match an existing composite skill's keys verbatim).
- Keep guidance grounded and version-aware (16/18/19) where install differs.
- Reference the `odoo_shell_install_module` tool by its exact name.

### References in Codebase
- `agents/troc_finance/skills/*/SKILL.md` — composite skill format to copy.
- `.agent/skills/` — additional skill examples / conventions.

---

## Acceptance Criteria

- [ ] `agents/odoo_agent/skills/install-odoo-module/SKILL.md` exists with valid frontmatter.
- [ ] Body covers prerequisites → install (`odoo_shell_install_module` / `odoo-bin -i`) → restart → verify.
- [ ] Frontmatter keys match an existing composite skill (parses under the loader).
- [ ] Discoverable by `SkillsDirectoryLoader` (single-file vs composite handled).

---

## Test Specification

```python
# Lightweight parse check (or rely on the agent's test_skills_discovered in TASK-1574)
from pathlib import Path
import yaml

def test_install_module_skill_frontmatter():
    p = Path("agents/odoo_agent/skills/install-odoo-module/SKILL.md")
    text = p.read_text()
    assert text.startswith("---")
    fm = yaml.safe_load(text.split("---")[1])
    assert "name" in fm and "description" in fm
```

---

## Agent Instructions

1. Read the spec (§3 Module 6) and one existing composite `SKILL.md` first.
2. Update index status → `in-progress`.
3. Author the skill per scope, matching the existing frontmatter shape.
4. Verify acceptance criteria (frontmatter parses).
5. Move this file to `sdd/tasks/completed/`.
6. Update index → `done`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-16
**Notes**: Created `agents/odoo_agent/skills/install-odoo-module/SKILL.md` with valid frontmatter (name, description, trigger, license, compatibility, metadata). Body covers prerequisites, install via `odoo_shell_install_module` (HITL-noted), Apps UI, and RPC. Also added `example.md` as an optional asset. Frontmatter parses correctly.

**Deviations from spec**: none
