# TASK-5634: Optional `procedure` field in skill frontmatter

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (skill side) and design research S5: the skill parser copies frontmatter fields by
hand, so graph metadata is lost unless the parser carries it. `SkillDefinition` keeps the **raw
mapping**; it is validated into a `ProcedureSpec` later by `skill_spec` (TASK-5635). This keeps
`parrot.skills` free of any import of `parrot.knowledge.wiki`.

---

## Scope

- Add `procedure: dict[str, Any] | None` to `SkillDefinition`.
- Make `parse_skill_file` read the optional `procedure` frontmatter key: `None` when absent; a
  non-mapping value raises `ValueError`.
- Add tests to the existing skill test file.

**NOT in scope**: validating the mapping's content, `ProcedureSpec`, registries, toolkits, the
learned-skill writer. A skill without the key must behave exactly as today.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/models.py` | MODIFY | New optional field on `SkillDefinition` |
| `packages/ai-parrot/src/parrot/skills/parsers.py` | MODIFY | Read and type-check the `procedure` key |
| `packages/ai-parrot/tests/unit/test_skill_definition.py` | MODIFY | Three new tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev).

### Verified Imports
```python
from typing import Any, ClassVar                      # already imported: skills/models.py:19
from pydantic import BaseModel, Field, field_validator # already imported: skills/models.py:21
from parrot.memory.skills.models import SkillSource, SkillDefinition   # test file line 4 (deprecated shim, keep as is)
from parrot.memory.skills.parsers import parse_skill_file              # test file line 5 (shim: `from parrot.skills.parsers import *`)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/models.py
class SkillDefinition(BaseModel):                        # :68
    suggestions: list[SkillSuggestion] = Field(          # :93  (field ends with `    )` at :96)
        default_factory=list,
        description="Follow-up chips emitted when this skill is the turn's skill (FEAT-752).",
    )
    MAX_TOKENS: ClassVar[int] = 1000                     # :98

# packages/ai-parrot/src/parrot/skills/parsers.py
def parse_skill_file(file_path: Path) -> SkillDefinition:   # :69
    metadata = post.metadata                                 # :86
    raw_suggestions = metadata.get("suggestions", None)      # :124
    ...
        raise ValueError(f"Skill file 'suggestions' must be a list: {file_path}")   # :130
    return SkillDefinition(... suggestions=suggestions, ...)  # :135-148, `suggestions=suggestions,` at :144
```

### Does NOT Exist
- ~~`SkillDefinition.procedure`~~, ~~`.applies_to`~~, ~~`.preconditions`~~, ~~`.mode`~~ — not fields today.
- ~~A `procedure` handling in `parse_skill_file`~~ — the parser copies fields one by one; an
  unknown frontmatter key is silently dropped today.
- ~~An import of `parrot.knowledge.wiki` in `parrot/skills/`~~ — must not be added.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/skills/parsers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_definition.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/models.py#SkillDefinition",
    "sym:packages/ai-parrot/src/parrot/skills/parsers.py#parse_skill_file"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- The new error message must follow the `suggestions` one exactly in style (spec §3 M2).
- Do not touch the token counting, the source detection or any other field.

---

## Implementation Blueprint

### Steps (in order)
1. Add the model field — *why*: the parser cannot pass a value the model does not declare.
2. Add the parser lines — *why*: the parser builds `SkillDefinition` field by field.
3. Add the tests to the existing class — *why*: the file is in the feature's Validation Contract.

### `packages/ai-parrot/src/parrot/skills/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    MAX_TOKENS: ClassVar[int] = 1000' packages/ai-parrot/src/parrot/skills/models.py)
# BEFORE — insert above `    MAX_TOKENS: ClassVar[int] = 1000` (verified: packages/ai-parrot/src/parrot/skills/models.py:98),
# i.e. right after the `suggestions` field that ends at :96, keeping one blank line before MAX_TOKENS.
    procedure: dict[str, Any] | None = Field(
        default=None,
        description="Optional graph fields (FEAT-891); validated into a ProcedureSpec by the producer.",
    )
```
**Why**: the raw mapping is stored untouched; validation happens in the producer.

### `packages/ai-parrot/src/parrot/skills/parsers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c "        raise ValueError(f\"Skill file 'suggestions' must be a list: {file_path}\")" packages/ai-parrot/src/parrot/skills/parsers.py)
# AFTER — insert below that line (verified: packages/ai-parrot/src/parrot/skills/parsers.py:130)
    raw_procedure = metadata.get("procedure", None)
    if raw_procedure is not None and not isinstance(raw_procedure, dict):
        raise ValueError(f"Skill file 'procedure' must be a mapping: {file_path}")

# occurrences: 1 (verified: grep -c '        suggestions=suggestions,' packages/ai-parrot/src/parrot/skills/parsers.py)
# AFTER — insert below `        suggestions=suggestions,` (verified: packages/ai-parrot/src/parrot/skills/parsers.py:144)
        procedure=raw_procedure,
```
**Why**: same contract as `suggestions` — absent means the default, a wrong type is an error that
names the file.

### `packages/ai-parrot/tests/unit/test_skill_definition.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class TestParseSkillFile:' packages/ai-parrot/tests/unit/test_skill_definition.py)
# Add these methods at the END of `class TestParseSkillFile:` (verified: packages/ai-parrot/tests/unit/test_skill_definition.py:61).
# Reuse the way the existing tests in that class write a skill file into tmp_path.
    def test_skill_without_procedure_unchanged(self, tmp_path):
        """A skill with no `procedure` key parses as before; the new field is None."""
        # FILL IN: write a minimal valid skill file, parse it, assert skill.procedure is None and that
        # name / description / triggers / template_body equal what was written.

    def test_skill_procedure_mapping_kept(self, tmp_path):
        """A `procedure` mapping is stored unchanged."""
        # FILL IN: frontmatter with `procedure: {mode: advisory, intents: [refund]}`; assert the dict.

    def test_skill_procedure_not_mapping_raises(self, tmp_path):
        """`procedure: "x"` raises ValueError naming the file."""
        # FILL IN: pytest.raises(ValueError, match="'procedure' must be a mapping")
```

### FILL IN checklist
- [ ] `test_skill_definition.py` — three test bodies; bounded by their docstrings

---

## Acceptance Criteria

- [ ] A skill file with no `procedure` key produces the same `SkillDefinition` as before, apart from `procedure` being `None`.
- [ ] A mapping is kept as a `dict`; a string or a list raises `ValueError` naming the file.
- [ ] `parrot/skills/` gains no import of `parrot.knowledge.wiki`.
- [ ] Every existing test in the file still passes.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_definition.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
3. Implement only the files listed above; complete every `FILL IN`.
4. Run `ruff check --fix` on the touched files and the Validation Commands.
5. Commit the code, then close with `parrot sdd task close TASK-5634 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
