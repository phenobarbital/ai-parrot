# TASK-4796: Skill frontmatter `suggestions:` → `SkillDefinition.suggestions`

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (skill half) and G4. A skill author opts in to chips by declaring them in the YAML frontmatter;
`SkillSuggestionProvider` (TASK-4798) emits them when that skill is the turn's skill. This task only adds the model
and the parser support — no chip logic.

---

## Scope

- Add `SkillSuggestion` model and `SkillDefinition.suggestions: list[SkillSuggestion]` (default `[]`).
- `parse_skill_file()` reads an optional `suggestions` key: absent → `[]`; a list of mappings → parsed; any other
  type → `ValueError` naming the file (same style as the `triggers` check).
- Tests in `tests/unit/test_skill_suggestions_frontmatter.py`.

**NOT in scope**: validating `output_mode` against `OutputMode` (the provider does it, TASK-4798); DB-backed
`SkillRegistry` skills; tenant shadowing (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/models.py` | MODIFY | `SkillSuggestion` + `SkillDefinition.suggestions` |
| `packages/ai-parrot/src/parrot/skills/parsers.py` | MODIFY | Read optional `suggestions` frontmatter |
| `packages/ai-parrot/tests/unit/test_skill_suggestions_frontmatter.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.models import SkillDefinition, SkillSource   # verified: skills/models.py:60, :53
from parrot.skills.parsers import parse_skill_file              # verified: skills/parsers.py:69
# skills/models.py already has: from pydantic import BaseModel, Field, field_validator  (line 21)
#                               from __future__ import annotations (line 11)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/models.py
class SkillSource(str, Enum): ...                                   # line 53-57  ← SkillSuggestion goes after this, before :60
class SkillDefinition(BaseModel):                                   # line 60
    name: str; description: str; triggers: list[str]; source = AUTHORED; priority = 90; version = "1.0"
    category: str | None = None; template_body: str; token_count: int; file_path: Path      # lines 67-76
    assets_dir: Path | None = Field(default=None, ...)              # line 77-80
    global_only: bool = Field(                                      # line 81-84  ← new field after this block
    MAX_TOKENS: ClassVar[int] = 1000                                # line 86

# packages/ai-parrot/src/parrot/skills/parsers.py
def parse_skill_file(file_path: Path) -> SkillDefinition:          # line 69
    metadata = post.metadata                                        # line 86
    # triggers type-check with ValueError f"... {file_path}"        # lines 91-100 (style to mirror)
    global_only = _parse_bool(metadata.get("global_only", False))   # line 123  ← read suggestions after this
    return SkillDefinition(..., global_only=global_only, ...)       # line 128-140, kwarg at :136 ← pass suggestions=
```

### Does NOT Exist
- ~~`SkillDefinition.suggestions`~~ / ~~`SkillSuggestion`~~ — created here.
- ~~an import of the core chip model (FEAT-752 `Suggestion`) from `skills/models.py`~~ — do NOT import it; `SkillSuggestion.output_mode` is
  a plain `str | None` validated later by the provider (keeps `parrot.skills` free of `parrot.models` coupling).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/skills/parsers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_suggestions_frontmatter.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/models.py#SkillDefinition",
    "sym:packages/ai-parrot/src/parrot/skills/parsers.py#parse_skill_file"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `SkillSuggestion` before `class SkillDefinition` — *why*: pydantic resolves the annotation at class creation.
2. Add the `suggestions` field after `global_only` — *why*: spec §3 M3 edit site.
3. Parse the key in `parse_skill_file` and pass it to the constructor — *why*: G4.
4. Tests; run Validation Commands including the existing skill tests (field is optional, nothing else may break).

### `packages/ai-parrot/src/parrot/skills/models.py` (MODIFY — model)
```python
# occurrences: 1 (verified: grep -c '^class SkillDefinition(BaseModel):' packages/ai-parrot/src/parrot/skills/models.py)
# BEFORE — insert above `class SkillDefinition(BaseModel):` (verified: models.py:60), after SkillSource (:53-57)
class SkillSuggestion(BaseModel):
    """A follow-up chip declared under ``suggestions:`` in skill frontmatter (FEAT-752)."""

    label: str = Field(min_length=1, max_length=40)
    prompt: str = Field(min_length=1, max_length=500)
    output_mode: str | None = None  # validated against OutputMode by SkillSuggestionProvider, not here
```

### `packages/ai-parrot/src/parrot/skills/models.py` (MODIFY — field)
```python
# occurrences: 1 (verified: grep -c '    global_only: bool = Field(' packages/ai-parrot/src/parrot/skills/models.py)
# AFTER — insert below the closing `    )` of the global_only block (verified: models.py:81-84)
    suggestions: list[SkillSuggestion] = Field(
        default_factory=list,
        description="Follow-up chips emitted when this skill is the turn's skill (FEAT-752).",
    )
```

### `packages/ai-parrot/src/parrot/skills/parsers.py` (MODIFY — read)
```python
# occurrences: 1 (verified: grep -c 'global_only = _parse_bool(metadata.get("global_only", False))' parsers.py)
# AFTER — insert below that line (verified: parsers.py:123)
    raw_suggestions = metadata.get("suggestions", None)
    if raw_suggestions is None:
        suggestions: list = []
    elif isinstance(raw_suggestions, list):
        suggestions = raw_suggestions
    else:
        raise ValueError(f"Skill file 'suggestions' must be a list: {file_path}")
```

### `packages/ai-parrot/src/parrot/skills/parsers.py` (MODIFY — constructor kwarg)
```python
# occurrences: 1 (verified: grep -c '        global_only=global_only,' parsers.py)
# AFTER — insert below `        global_only=global_only,` (verified: parsers.py:136)
        suggestions=suggestions,
```
**Why**: pydantic coerces each mapping into `SkillSuggestion`; an invalid entry (e.g. 41-char label) raises a
`ValidationError` from the constructor, which callers already treat as an unparseable skill file.

### FILL IN checklist
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] `suggestions:` list → `SkillDefinition.suggestions` with `SkillSuggestion` items (incl. `output_mode`).
- [ ] Absent key → `[]`; scalar/mapping value → `ValueError` mentioning the file path.
- [ ] Existing skill tests (`test_skill_definition.py`, `test_skill_global_only.py`) stay green.
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_suggestions_frontmatter.py -q`
- `pytest packages/ai-parrot/tests/unit/test_skill_definition.py -q`
- `pytest packages/ai-parrot/tests/unit/test_skill_global_only.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_skill_suggestions_frontmatter.py
import pytest
from parrot.skills.parsers import parse_skill_file

SKILL = """---
name: sales-analyst
description: Monthly sales analysis helpers
triggers: [/sales]
suggestions:
  - label: "vs last month"
    prompt: "Compare the same figures against the previous month"
  - label: "As KPI"
    prompt: "Show the headline number as a KPI card"
    output_mode: card
---
Body.
"""


def test_skill_frontmatter_suggestions_parsed(tmp_path):
    f = tmp_path / "sales.md"
    f.write_text(SKILL)
    skill = parse_skill_file(f)
    assert [s.label for s in skill.suggestions] == ["vs last month", "As KPI"]
    assert skill.suggestions[1].output_mode == "card"


def test_skill_frontmatter_suggestions_absent(tmp_path):
    # FILL IN: same file without the suggestions block -> skill.suggestions == []
    ...


def test_skill_frontmatter_suggestions_not_a_list(tmp_path):
    # FILL IN: `suggestions: "x"` -> pytest.raises(ValueError, match="suggestions")
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src`, commit only listed files,
`scripts/sdd/close_task.sh TASK-4796 followup-suggestion-chips verified`).

---

## Completion Note

*(Agent fills this in when done)*
