---
id: FW-014
query_id: Q014
type: wiki_query
intent: "Skills composite bundle: SKILL.md + assets, frontmatter, tenant shadowing"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-014 — Skills are the in-repo directory-bundle precedent: `discover_skills_in_dir` (single `.md` or `<name>/SKILL.md` + assets), frontmatter → `SkillDefinition` (name/description/triggers/source/priority/version/category/global_only/token_count/assets_dir), token-counted with tiktoken, and `SkillView` tenant-over-global shadowing with `global_only` locks

## Summary

`skills/parsers.py` parses frontmatter (`python-frontmatter`) into `SkillDefinition` (models.py:68; `token_count` :83 validated at :100-102, `assets_dir` :85, `global_only` :89), auto-detects `source` (`learned` path → LEARNED), counts body tokens with cl100k_base. `discover_skills_in_dir` iterates sorted entries, accepts `{dir}/{name}.md` or `{dir}/{name}/SKILL.md`, skips `exclude_names`, logs-and-skips malformed skills. `skills/tenancy.py` (FEAT-707) provides `tenant_skills_dir(agent_root, tenant)` = `agent_root/tenants/{tenant}/skills` (secure_path, `RESERVED_TENANT_NAMES`), `SkillView` overlay (tenant shadows global by name and trigger; `global_only` skills cannot be shadowed → dropped with error; learned skills stay global), `TenantTreeReport` audit, and request-local ContextVars (`current_skill_tenant` aliases `observability.context.current_tenant`, `_active_skill`).

## Citations

- path: `packages/ai-parrot/src/parrot/skills/parsers.py`
  lines: 1-220
  symbol: `parse_skill_file` / `parse_skill_directory` / `discover_skills_in_dir`
  wiki_page_id: file:packages/ai-parrot/src/parrot/skills/parsers.py
  score: 42.96
  excerpt: |
    def parse_skill_directory(skill_dir: Path) -> SkillDefinition:
        skill_md = skill_dir / "SKILL.md"
        skill = parse_skill_file(skill_md)
        return skill.model_copy(update={"assets_dir": skill_dir})
    def discover_skills_in_dir(directory, logger=_LOGGER, exclude_names=()) -> List[SkillDefinition]:
        for entry in sorted(directory.iterdir()):
            if entry.is_file() and entry.suffix == ".md": skills.append(parse_skill_file(entry))
            elif entry.is_dir() and (entry / "SKILL.md").exists(): skills.append(parse_skill_directory(entry))

- path: `packages/ai-parrot/src/parrot/skills/models.py`
  lines: 53-102
  symbol: `SkillDefinition`
  excerpt: |
    class SkillSource(str, Enum):          # :53
    class SkillDefinition(BaseModel):      # :68
        token_count: int                   # :83
        assets_dir: Path | None = Field(   # :85
        global_only: bool = Field(         # :89
        @field_validator("token_count") def validate_token_count(cls, v)   # :100-102

- path: `packages/ai-parrot/src/parrot/skills/tenancy.py`
  lines: 1-260
  symbol: `SkillView` / `tenant_skills_dir` / `RESERVED_TENANT_NAMES`
  wiki_page_id: file:packages/ai-parrot/src/parrot/skills/tenancy.py
  score: 32.42
  excerpt: |
    RESERVED_TENANT_NAMES = frozenset({"skills","learned","tenants","prompts","queries","kb","documents","flows","routes","_drafts","_shared"})
    def tenant_skills_dir(agent_root: Path, tenant: str) -> Path:
        return secure_path(agent_root, TENANTS_DIRNAME, validate_tenant_id(tenant), SKILLS_DIRNAME, name="tenant id")
    class SkillView:  # tenant first, then unshadowed globals; global_only locks names + triggers

- path: `sdd/proposals/per-tenant-skills.brainstorm.md`
  symbol: `FEAT-707 per-tenant skills`
  wiki_page_id: file:sdd/proposals/per-tenant-skills.brainstorm.md
  score: 33.64
  excerpt: |
    Brainstorm: Per-Tenant Skills for `SkillRegistryMixin`

## Notes

This is the closest architectural twin of the expert bundle: frontmatter-validated Markdown + assets dir + token budget + deterministic sorted discovery + an overlay (`SkillView`) that implements "workspace > package" shadowing with lock semantics. `RESERVED_TENANT_NAMES` already reserves `kb`, `documents`, `prompts`, `flows` under an agent root — an `experts` / `knowledge` dir name must be checked against it. `AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/` is the existing per-agent workspace layout the source's `.parrot/knowledge/<slug>/` Tier-2 would parallel.
