---
id: F007
query_id: Q026
type: read
intent: "Read the skills directory loader: composite bundle discovery, frontmatter validation, assets."
executed_at: 2026-10-30T16:42:58Z
duration_ms: 500
parent_id: null
depth: 0
merged_from: [FC-007-skills-composite-loader]
---

# F007 — `SkillsDirectoryLoader` discovers single-file `{dir}/{name}.md` and composite `{dir}/{name}/SKILL.md` bundles; malformed entries warn and are skipped

## Summary

104 lines. Takes a list of base paths; `discover()` skips missing/non-dir bases and malformed skill files with a warning; `load_into(registry)` registers each definition, logging individual failures. Composite layout = directory with `SKILL.md` plus adjacent assets. This is the closest existing "directory bundle discovered by presence" precedent for an expert bundle.

## Citations

- path: `packages/ai-parrot/src/parrot/skills/loader.py`
  lines: 26-54
  symbol: `SkillsDirectoryLoader`
  excerpt: |
    - **Composite**: {dir}/{name}/SKILL.md — a directory containing
      SKILL.md plus adjacent asset files (scripts, templates, etc.).

- path: `packages/ai-parrot/src/parrot/skills/loader.py`
  lines: 62-104
  symbol: `SkillsDirectoryLoader.discover / load_into`
  excerpt: |
    async def discover(self) -> List[SkillDefinition]:
        """... Skips non-existent paths and malformed skill files with a warning."""
    async def load_into(self, registry: SkillFileRegistry) -> int:
        """... Individual registration failures are logged as warnings."""

## Notes

Pinned by `tests/unit/test_skills_directory_loader.py` (FC-021).
