---
id: FC-030
query_id: Q050
type: read
intent: "Tests pinning the skills loader (what a parallel ExpertLoader must replicate)."
executed_at: 2026-10-30T16:46:28Z
duration_ms: 200
parent_id: null
depth: 0
---

# FC-030 — `tests/unit/test_skills_directory_loader.py` pins single-file, composite (`dir/SKILL.md`), mixed and nonexistent-path discovery; subdirs without SKILL.md are ignored

## Summary

Fixture writes a composite `SKILL.md` plus a subdirectory without one ("should be ignored"); tests: `test_discover_single_file`, `test_discover_composite`, `test_discover_mixed`, `test_discover_nonexistent_path`. An `experts/` loader would need the same four behaviours plus manifest validation.

## Citations

- path: `tests/unit/test_skills_directory_loader.py`
  lines: 26-33
  symbol: `skill_dir fixture`
  excerpt: |
    (composite / "SKILL.md").write_text(
    # Subdirectory without SKILL.md (should be ignored)

- path: `tests/unit/test_skills_directory_loader.py`
  lines: 52-78
  symbol: `test_discover_single_file / test_discover_composite / test_discover_mixed / test_discover_nonexistent_path`
  excerpt: |
    async def test_discover_single_file(skill_dir):
    async def test_discover_composite(skill_dir):   """Discovers composite dir/SKILL.md skills."""
    async def test_discover_mixed(skill_dir):
    async def test_discover_nonexistent_path():

## Notes

Lives at repo-root `tests/unit/`, not under `packages/ai-parrot/tests/`.
