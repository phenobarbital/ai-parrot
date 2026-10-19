# TASK-4493: `global_only` skill frontmatter field

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. A global skill may declare `global_only: true` in its YAML
frontmatter; tenant trees may then not shadow it by name or trigger (collision
matrix rows C3/C4, spec §2). Today `SkillDefinition` has no such field and
`parse_skill_file()` silently ignores unknown frontmatter keys
(design-research S7), so the guard cannot work until this task lands.
`SkillView` (TASK-4494) reads this field.

---

## Scope

- Add `global_only: bool = False` to `SkillDefinition`.
- Parse `global_only` in `parse_skill_file()` and pass it to the constructor.
- Composite skills (`{name}/SKILL.md`) inherit the field automatically through
  `parse_skill_directory()` → `parse_skill_file()` — verify with a test, no code change there.
- Write `packages/ai-parrot/tests/unit/test_skill_global_only.py`.

**NOT in scope**: enforcing the guard (TASK-4494 `SkillView`), learned-skill
frontmatter (learned skills never set it), any change to `SkillFileRegistry`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/models.py` | MODIFY | `SkillDefinition.global_only` field |
| `packages/ai-parrot/src/parrot/skills/parsers.py` | MODIFY | parse and pass `global_only` |
| `packages/ai-parrot/tests/unit/test_skill_global_only.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.models import SkillDefinition, SkillSource          # verified: skills/models.py:60 / :53
from parrot.skills.parsers import parse_skill_file, parse_skill_directory  # verified: skills/parsers.py:60 / :132
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/models.py
class SkillDefinition(BaseModel):                                   # line 60
    name: str; description: str; triggers: list[str]
    source: SkillSource = SkillSource.AUTHORED; priority: int = 90  # line 71
    version: str = "1.0"; category: str | None = None
    template_body: str; token_count: int; file_path: Path
    assets_dir: Path | None = Field(                                # line 77
        default=None,
        description="Filesystem dir for composite skills; None for single-file.",
    )
    MAX_TOKENS: ClassVar[int] = 1000                                # line 82

# packages/ai-parrot/src/parrot/skills/parsers.py
def parse_skill_file(file_path: Path) -> SkillDefinition:           # line 60
    # metadata = post.metadata (frontmatter dict)
    version = str(metadata.get("version", "1.0"))
    category = metadata.get("category", None)
    priority = int(metadata.get("priority", 90))                    # line 113
    token_count = _count_tokens(template_body)
    return SkillDefinition(                                         # line 118
        name=name, description=description, triggers=triggers, source=source,
        priority=priority, version=version, category=category,
        template_body=template_body, token_count=token_count, file_path=file_path,
    )
def parse_skill_directory(skill_dir: Path) -> SkillDefinition:      # line 132
    # skill = parse_skill_file(skill_md) (157); skill.model_copy(update={"assets_dir": skill_dir}) (158)
```

### Does NOT Exist
- ~~`SkillDefinition.global_only`~~ — added by this task.
- ~~`SkillDefinition.tenant`~~ — not part of the design (tenancy is directory-based).
- ~~Editing `parrot.memory.skills.models` / `.parsers`~~ — deprecated re-export shims; never edit them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/skills/parsers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_global_only.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/models.py#SkillDefinition",
    "sym:packages/ai-parrot/src/parrot/skills/parsers.py#parse_skill_file",
    "sym:packages/ai-parrot/src/parrot/skills/parsers.py#parse_skill_directory"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Default `False` keeps every existing skill and test byte-identical (spec AC-B1, AC-0).
- Accept YAML booleans only through `bool(...)`; a string `"false"` is truthy in Python —
  treat strings explicitly (see FILL IN) so `global_only: "false"` does not lock a skill.

### References in Codebase
- `packages/ai-parrot/src/parrot/skills/parsers.py:105-116` — how optional fields are read today.

---

## Implementation Blueprint

### Steps (in order)
1. Add the field to `SkillDefinition` right after `assets_dir` — *why*: keeps optional fields grouped and the default makes it backwards compatible.
2. Read `global_only` in `parse_skill_file()` after `priority` and pass it to the constructor — *why*: the parser is the only place frontmatter becomes a model, and composite skills go through it too.
3. Write the tests — *why*: TASK-4494's collision rows C3/C4 rely on this field being parsed.

### `packages/ai-parrot/src/parrot/skills/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    assets_dir: Path | None = Field(' packages/ai-parrot/src/parrot/skills/models.py)
# AFTER — insert below the closing `)` of the `assets_dir` Field(...) (verified: models.py:77-80)
    global_only: bool = Field(
        default=False,
        description="Tenant skill trees may not shadow this skill by name or trigger (FEAT-707).",
    )
```
**Why**: spec §2 Data Models fixes the name and default; `SkillView` reads it with plain attribute access.

### `packages/ai-parrot/src/parrot/skills/parsers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    priority = int(metadata.get("priority", 90))' packages/ai-parrot/src/parrot/skills/parsers.py)
# AFTER — insert below `    priority = int(metadata.get("priority", 90))` (verified: parsers.py:113)
    global_only = _parse_bool(metadata.get("global_only", False))

# and in the SkillDefinition(...) call at parsers.py:118, add the keyword:
        global_only=global_only,

# NEW module-level helper (place above parse_skill_file, after _count_tokens at parsers.py:55):
def _parse_bool(value: object) -> bool:
    """Coerce a frontmatter value to bool, treating "false"/"no"/"0"/"" strings as False."""
    # FILL IN: return value for bool as-is; for str compare value.strip().lower() against
    #          {"true", "yes", "1", "on"}; anything else falls back to bool(value)
    #          — bounded by Key Constraints (string "false" must not be truthy)
```
**Why**: one parse site covers single-file and composite skills (parsers.py:157-158 calls `parse_skill_file`).

### `packages/ai-parrot/tests/unit/test_skill_global_only.py` (CREATE)
```python
"""FEAT-707 — `global_only` frontmatter parsing (TASK-4493)."""
from pathlib import Path

import pytest

from parrot.skills.models import SkillDefinition
from parrot.skills.parsers import parse_skill_directory, parse_skill_file


def _write_skill(path: Path, extra: str = "") -> Path:
    path.write_text(
        "---\nname: revenue\ndescription: Revenue by division\ntriggers:\n  - /revenue\n"
        f"{extra}---\n\nCompute revenue.\n"
    )
    return path


def test_default_is_false(tmp_path: Path) -> None:
    skill = parse_skill_file(_write_skill(tmp_path / "revenue.md"))
    assert skill.global_only is False


@pytest.mark.parametrize("raw,expected", [("true", True), ("false", False), ('"false"', False), ("yes", True)])
def test_parses_global_only(tmp_path: Path, raw: str, expected: bool) -> None:
    # FILL IN: write a skill with `global_only: {raw}\n` and assert skill.global_only is expected
    ...


def test_composite_inherits_global_only(tmp_path: Path) -> None:
    # FILL IN: tmp_path/"revenue"/SKILL.md with `global_only: true`; parse_skill_directory → True and assets_dir set
    ...


def test_model_default() -> None:
    # FILL IN: construct SkillDefinition(...) without global_only → False
    ...
```

### FILL IN checklist
- [ ] `parsers.py::_parse_bool` — string handling; bounded by Key Constraints
- [ ] `test_skill_global_only.py` — three test bodies

---

## Acceptance Criteria

- [ ] `SkillDefinition.global_only` exists, default `False` (spec §2 Data Models).
- [ ] `global_only: true` parsed for single-file and composite skills; `"false"` string parses as `False`.
- [ ] Pre-existing parser/model tests pass unmodified (spec AC-0).
- [ ] `ruff check` clean on touched files.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_global_only.py -q`
- `pytest tests/unit/test_skill_parsers.py -q`
- `pytest tests/unit/test_skill_models.py -q`
- `pytest packages/ai-parrot/tests/unit/test_skill_definition.py -q`

---

## Test Specification

See the CREATE block above; all four tests must pass.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** `sdd/specs/per-tenant-skills.spec.md` (§2 Collision matrix, §3 Module 2).
3. **Check dependencies** in `sdd/tasks/index/per-tenant-skills.json` — none for this task.
4. **Verify the Codebase Contract** before writing code; re-run each `grep -c` anchor.
5. **Update status** → `"in-progress"` (+ `started_at`) in the per-spec index; commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
7. **Validate** with the Validation Commands using
   `PYTHONPATH=packages/ai-parrot/src` (the shared venv imports the main checkout otherwise).
8. **Commit code** — stage only the files listed above.
9. **Close** with `scripts/sdd/close_task.sh TASK-4493 per-tenant-skills verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note


- Task: TASK-4493
- Feature: per-tenant-skills
- Implementation SHA: 7f7dce775f15331f7475087cf52a8aa44e482375
- Closed at (UTC): 2026-10-19T21:21:23+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 169s · Tokens: n/a |
