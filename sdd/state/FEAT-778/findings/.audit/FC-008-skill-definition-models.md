---
id: FC-008
query_id: Q027
type: read
intent: "Read skill models: SkillDefinition / frontmatter Pydantic shape (template for ExpertManifest)."
executed_at: 2026-10-30T16:42:58Z
duration_ms: 600
parent_id: null
depth: 0
---

# FC-008 — `SkillDefinition` carries name/description/triggers/priority/version/token_count/file_path/assets_dir/global_only; DB `SkillVersion` already hashes content with SHA-256

## Summary

`skills/models.py` (334 lines). File-based `SkillDefinition` (Pydantic) has `token_count` (pre-counted body size), `assets_dir`, `global_only` (cannot be shadowed per tenant) and `suggestions`. DB-backed `Skill`/`SkillVersion` dataclasses have `namespace` (org/agent or org/_shared), owner ids, versioning with `content_hash` (SHA256) and `parent_version_id`. Two precedents for the expert: token-counted bodies and shared-vs-owned namespaces.

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

## Notes

`token_count` on load is exactly what a per-layer KnowledgeContext budget needs.
