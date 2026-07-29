---
type: Wiki Summary
title: parrot.skills.models
id: mod:parrot.skills.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SkillRegistry Models for AI-Parrot Framework.
relates_to:
- concept: class:parrot.skills.models.ContentType
  rel: defines
- concept: class:parrot.skills.models.DeprecateSkillArgs
  rel: defines
- concept: class:parrot.skills.models.ExtractedSkill
  rel: defines
- concept: class:parrot.skills.models.ReadSkillArgs
  rel: defines
- concept: class:parrot.skills.models.SearchSkillArgs
  rel: defines
- concept: class:parrot.skills.models.Skill
  rel: defines
- concept: class:parrot.skills.models.SkillCategory
  rel: defines
- concept: class:parrot.skills.models.SkillDefinition
  rel: defines
- concept: class:parrot.skills.models.SkillMetadata
  rel: defines
- concept: class:parrot.skills.models.SkillSearchResult
  rel: defines
- concept: class:parrot.skills.models.SkillSource
  rel: defines
- concept: class:parrot.skills.models.SkillStatus
  rel: defines
- concept: class:parrot.skills.models.SkillVersion
  rel: defines
- concept: class:parrot.skills.models.SkillVersionsArgs
  rel: defines
- concept: class:parrot.skills.models.UploadSkillArgs
  rel: defines
---

# `parrot.skills.models`

SkillRegistry Models for AI-Parrot Framework.

Git-like versioned skill/knowledge registry that allows:
- Agents to document learned skills and patterns
- Version control with unified diffs
- Skill discovery and retrieval
- Provenance tracking (who created/updated)

## Classes

- **`SkillStatus(str, Enum)`** — Lifecycle status of a skill.
- **`SkillCategory(str, Enum)`** — Categories for organizing skills.
- **`ContentType(str, Enum)`** — How the version content is stored.
- **`SkillSource(str, Enum)`** — Origin of the skill.
- **`SkillDefinition(BaseModel)`** — Parsed skill from a .md file with YAML frontmatter.
- **`SkillMetadata`** — Searchable metadata for a skill.
- **`SkillVersion`** — A single immutable version of a skill.
- **`Skill`** — A versioned skill/knowledge document.
- **`SkillSearchResult`** — Result from skill search.
- **`UploadSkillArgs(BaseModel)`** — Arguments for uploading/updating a skill.
- **`SearchSkillArgs(BaseModel)`** — Arguments for searching skills.
- **`ReadSkillArgs(BaseModel)`** — Arguments for reading a skill.
- **`SkillVersionsArgs(BaseModel)`** — Arguments for listing skill versions.
- **`DeprecateSkillArgs(BaseModel)`** — Arguments for deprecating a skill.
- **`ExtractedSkill(BaseModel)`** — LLM-extracted skill from conversation.
