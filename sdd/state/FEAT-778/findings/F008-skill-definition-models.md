---
id: F008
query_id: Q027
type: read
intent: "Read skill models: SkillDefinition / frontmatter Pydantic shape (template for ExpertManifest)."
executed_at: 2026-10-30T16:42:58Z
duration_ms: 600
parent_id: null
depth: 0
merged_from: [FC-008-skill-definition-models, FC-009-skill-tenancy-shadowing, FW-014-skills-composite-bundle]
---

# F008 — `SkillDefinition` carries name/description/triggers/priority/version/token_count/file_path/assets_dir/global_only; DB `SkillVersion` already hashes content with SHA-256

## Summary

*[FC-008-skill-definition-models]* `skills/models.py` (334 lines). File-based `SkillDefinition` (Pydantic) has `token_count` (pre-counted body size), `assets_dir`, `global_only` (cannot be shadowed per tenant) and `suggestions`. DB-backed `Skill`/`SkillVersion` dataclasses have `namespace` (org/agent or org/_shared), owner ids, versioning with `content_hash` (SHA256) and `parent_version_id`. Two precedents for the expert: token-counted bodies and shared-vs-owned namespaces.

*[FC-009-skill-tenancy-shadowing]* `skills/tenancy.py` (290 lines, FEAT-707). `tenant_skills_dir(agent_root, tenant)` = `agent_root/tenants/{tenant}/skills` (path-safe). `SkillView` computes `shadowing`/`shadowed_triggers`: a tenant skill with the same name shadows the global one, unless the global is `global_only` (tenant skill dropped with a warning). The active tenant/skill live in ContextVars (`current_tenant` from observability.context). This answers the "workspace > package priority" open question with an existing rule set.

*[FW-014-skills-composite-bundle]* `skills/parsers.py` parses frontmatter (`python-frontmatter`) into `SkillDefinition` (models.py:68; `token_count` :83 validated at :100-102, `assets_dir` :85, `global_only` :89), auto-detects `source` (`learned` path → LEARNED), counts body tokens with cl100k_base. `discover_skills_in_dir` iterates sorted entries, accepts `{dir}/{name}.md` or `{dir}/{name}/SKILL.md`, skips `exclude_names`, logs-and-skips malformed skills. `skills/tenancy.py` (FEAT-707) provides `tenant_skills_dir(agent_root, tenant)` = `agent_root/tenants/{tenant}/skills` (secure_path, `RESERVED_TENANT_NAMES`), `SkillView` overlay (tenant shadows global by name and trigger; `global_only` skills cannot be shadowed → dropped with error; learned skills stay global), `TenantTreeReport` audit, and request-local ContextVars (`current_skill_tenant` aliases `observability.context.current_tenant`, `_active_skill`).

## Citations

- path: `packages/ai-parrot/src/parrot/skills/models.py`
  lines: 68-95
  symbol: `SkillDefinition`
  excerpt: |
    class SkillDefinition(BaseModel):
        name: str; description: str; triggers: list[str]
        source: SkillSource = SkillSource.AUTHORED; priority: int = 90; version: str = "1.0"
        template_body: str; token_count: int; file_path: Path
        assets_dir: Path | None; global_only: bool; suggestions: list[SkillSuggestion]

- path: `packages/ai-parrot/src/parrot/skills/models.py`
  lines: 134-157
  symbol: `SkillVersion`
  excerpt: |
    content_hash: str = ""  # SHA256 of reconstructed content
    created_by: str = ""  # agent_id
    parent_version_id: str | None = None

- path: `packages/ai-parrot/src/parrot/skills/models.py`
  lines: 182-205
  symbol: `Skill`
  excerpt: |
    namespace: str = "default"  # org_id/agent_id, or "org_id/_shared" for the
    owner_agent_id: str = ""; owner_user_id: str = ""
    status: SkillStatus = SkillStatus.ACTIVE

- path: `packages/ai-parrot/src/parrot/skills/tenancy.py`
  lines: 54-60
  symbol: `tenant_skills_dir`
  excerpt: |
    return secure_path(agent_root, TENANTS_DIRNAME, validate_tenant_id(tenant), SKILLS_DIRNAME, name="tenant id")

- path: `packages/ai-parrot/src/parrot/skills/tenancy.py`
  lines: 164-248
  symbol: `SkillView`
  excerpt: |
    locked_names = {skill.name: skill for skill in globals_ if skill.global_only}
    "Tenant skill %s (%s) conflicts with global_only skill (%s); dropping tenant skill"
    self.logger.info("Tenant skill %s shadows global skill %s", ...)

- path: `packages/ai-parrot/src/parrot/skills/tenancy.py`
  lines: 90-104
  symbol: `current_skill_tenant / bind_skill_tenant`
  excerpt: |
    _skill_tenant = current_tenant
    def bind_skill_tenant(tenant: Optional[str]) -> Token: return _skill_tenant.set(tenant)

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

*[FC-008-skill-definition-models]* `token_count` on load is exactly what a per-layer KnowledgeContext budget needs.

*[FC-009-skill-tenancy-shadowing]* Precedent for "workspace Tier 2 shadows bundled Tier 1 except locked entries".

*[FW-014-skills-composite-bundle]* This is the closest architectural twin of the expert bundle: frontmatter-validated Markdown + assets dir + token budget + deterministic sorted discovery + an overlay (`SkillView`) that implements "workspace > package" shadowing with lock semantics. `RESERVED_TENANT_NAMES` already reserves `kb`, `documents`, `prompts`, `flows` under an agent root — an `experts` / `knowledge` dir name must be checked against it. `AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/` is the existing per-agent workspace layout the source's `.parrot/knowledge/<slug>/` Tier-2 would parallel.
