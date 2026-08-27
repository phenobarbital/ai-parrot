---
name: skill-writer
description: The frontmatter contract for writing a valid skill file (per-agent or shared catalog)
triggers:
  - write a skill
  - create a skill
  - new skill
  - publish a skill
category: agent-development
---

# Skill Writer

Every skill file is Markdown with YAML frontmatter followed by the skill
body:

```markdown
---
name: resumen
description: Resume long texts into bullet points
triggers:
  - /resumen
  - summarize this
category: general
---

<skill instructions body — what the agent should do when this skill fires>
```

## Required frontmatter fields

- `name` — required, non-empty.
- `description` — required, non-empty.
- `triggers` — required key (a list is fine, even empty for composite
  skills structured around a directory rather than trigger phrases).

## Optional frontmatter fields

- `category` — free text; the shared catalog constrains this to
  `parrot.skills.models.SkillCategory`'s values (out-of-vocabulary values
  fall back to `"general"`).
- `version` — defaults to `"1.0"`.
- `priority` — defaults to `90`.
- `source` — `"authored"` (default) or `"learned"`; never set this to
  anything else.

## Two targets — pick the right tool

- **Per-agent skill** (only that agent uses it): call
  `write_skill_file(agent_name, filename, content)`. `filename` is either
  `<name>.md` (single-file) or `<name>/SKILL.md` plus any
  `<name>/<asset>` companion files (composite). The definition file
  (`<name>.md` or `<name>/SKILL.md`) is validated against this contract
  before writing; composite assets are written as-is.
- **Shared, org-wide skill** (any agent can import it): call
  `publish_skill_to_catalog(name, description, category, triggers, body)`
  — `body` is the FULL markdown including frontmatter, following the
  same contract above. Fails clearly if the name is already taken.

Never invent a skill body without first checking whether something
similar already exists — call `list_available_tools` if the skill wraps
tool usage guidance.
