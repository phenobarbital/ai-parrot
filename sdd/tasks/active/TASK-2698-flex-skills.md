# TASK-2698: Flex skills — /widget, /infographic, flex-narrative

**Feature**: FEAT-491 — Flex A2UI Dashboard Agent
**Spec**: `sdd/specs/flex-agent-infographic-a2ui.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2696
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Three file-based skills under
`agents/flex_dashboard/skills/`, discovered via the agent's `skill_paths`
(TASK-2696) and activated deterministically through the `/trigger`
middleware. `/widget` exports a single KPI as an A2UI structured envelope;
`/infographic` drives `InfographicToolkit`; `flex-narrative` renders
`narrative_facts` as executive prose for the recipe's optional narrative
step.

---

## Scope

- Create composite skills (`<name>/SKILL.md` layout):
  - `agents/flex_dashboard/skills/widget/SKILL.md` — frontmatter
    `triggers: ["/widget"]`. Body: instructions mapping each KPI name to
    (a) its transformer/computation and (b) the A2UI output mode to emit —
    structured chart for the month series, map for proximity, hero card for
    the totals — leaning on the agent's `output_routing` (FEAT-224) lane;
    include the KPI→dataset/filter table (from the TASK-2695 `datasets.md`
    doc) as an asset or inline.
  - `agents/flex_dashboard/skills/infographic/SKILL.md` — frontmatter
    `triggers: ["/infographic"]`. Body: guide the agent to compose a
    descriptive infographic via `InfographicToolkit` render tools from
    current data, quoting only computed figures.
  - `agents/flex_dashboard/skills/flex-narrative/SKILL.md` — no triggers
    (invoked by `NarrativeMixin.narrate(facts, "flex-narrative")`); copy the
    precision rules of `.agent/skills/budget-narrative/SKILL.md` ("Quote only
    figures present in the facts; never invent a number") adapted to the
    Flex KPI vocabulary.
- Unit test `test_skills_discovered`: the three skills are found through the
  agent's `skill_paths` and `/widget` + `/infographic` carry their triggers.

**NOT in scope**: kb docs (TASK-2695), any change to skills middleware/core.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/flex_dashboard/skills/widget/SKILL.md` | CREATE | /widget skill |
| `agents/flex_dashboard/skills/infographic/SKILL.md` | CREATE | /infographic skill |
| `agents/flex_dashboard/skills/flex-narrative/SKILL.md` | CREATE | narrative skill |
| `packages/ai-parrot/tests/unit/bots/test_flex_dashboard_skills.py` | CREATE | discovery + trigger test |

---

## Codebase Contract (Anti-Hallucination)

### Skill file format (verified sample — `.agent/skills/budget-narrative/SKILL.md`)
```yaml
---
name: budget-narrative
description: >
  Render deterministic budget-variance facts ... never invent a number.
triggers: []
category: domain
version: "1.0"
---
```
Composite layout: `{dir}/{name}/SKILL.md` + adjacent asset files, exposed via
`SkillDefinition.assets_dir` (see `.agent/CONTEXT.md` "Skills": single-file
`{dir}/{name}.md` OR composite `{dir}/{name}/SKILL.md` are both recognized).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/models.py
# SkillDefinition.triggers: list[str]        # line 69/101 — "/trigger" patterns
# packages/ai-parrot/src/parrot/skills/mixin.py
# SkillRegistryMixin._configure_skill_registry()   # lines 142-188 — builds the
#   file registry from skill_paths and registers create_skill_trigger_middleware
# packages/ai-parrot/src/parrot/bots/mixins/narrative.py
class NarrativeMixin(SkillRegistryMixin):          # line 29
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]  # line 54
```

### Does NOT Exist
- ~~a per-skill Python handler file~~ — skills are markdown instructions;
  the `/widget` export executes through the agent's EXISTING tools
  (pandas tool, InfographicToolkit, structured output routing), not new code.
- ~~`SkillDefinition.trigger` (singular)~~ — the field is `triggers: list[str]`.
- ~~skills auto-discovery from `.agent/skills/` for this agent~~ — discovery
  is opt-in via the agent's `skill_paths` (TASK-2696 points it at
  `agents/flex_dashboard/skills/`); `.agent/skills/` belongs to other agents.

---

## Implementation Notes

### Key Constraints
- Skill bodies are LLM instructions: imperative, concrete, with the exact
  KPI names from the spec so `/widget payroll_pct_by_month`-style requests
  resolve unambiguously.
- `/widget` must state the output-mode mapping explicitly:
  month series → STRUCTURED_CHART; proximity → MAP; totals → hero card
  (structured envelope); tables → TABLE.
- Keep each SKILL.md under ~150 lines; put long KPI tables in an adjacent
  asset file within the skill directory (composite layout).
- English, matching every existing skill.

### References in Codebase
- `.agent/skills/budget-narrative/SKILL.md` — frontmatter + precision rules.
- `agents/porygon.py:342-343` — skill registry configuration precedent.

---

## Acceptance Criteria

- [ ] Three skills exist in the composite layout with valid frontmatter.
- [ ] `/widget` and `/infographic` declare their triggers; `flex-narrative`
      declares none.
- [ ] `/widget` body maps every spec KPI to an output mode.
- [ ] Discovery test passes: `pytest packages/ai-parrot/tests/unit/bots/test_flex_dashboard_skills.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_flex_dashboard_skills.py
# Build a SkillFileRegistry/SkillsDirectoryLoader over
# agents/flex_dashboard/skills/ (grep packages/ai-parrot/tests for existing
# SkillsDirectoryLoader tests and mirror their construction).

def test_skills_discovered(registry):
    names = {s.name for s in registry.list()}
    assert {"widget", "infographic", "flex-narrative"} <= names

def test_triggers():
    assert "/widget" in widget_skill.triggers
    assert "/infographic" in infographic_skill.triggers
    assert flex_narrative_skill.triggers == []
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2696 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/flex-agent-infographic-a2ui.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
