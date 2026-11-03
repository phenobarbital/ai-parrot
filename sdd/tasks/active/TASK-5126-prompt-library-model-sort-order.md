# TASK-5126: `PromptLibrary` model — `sort_order` field and a string `prompt_category` default

**Feature**: FEAT-794 — Prompt Library — writable again, with manual order
**Spec**: `sdd/specs/prompt-library-writable-sort-order.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview item 2 and Module 2. Two model defects break every write and the new column:
- `prompt_category`'s default is the enum member `PromptCategory.OTHER`, but the field is typed `str` under
  `strict = True`, so a create without `prompt_category` returns `400`.
- After `0009`, `SELECT *` returns `sort_order`; asyncdb builds `cls(**dict(row))`, and a strict model without the
  field raises `TypeError` on every read. The field must exist in the same release as the column.

---

## Scope

- Add `sort_order: Optional[int] = Field(required=False, default=None)` to `PromptLibrary`.
- Change the `prompt_category` default to `PromptCategory.OTHER.value`.
- Rewrite the model docstring's DDL block so it states the deployed shape and says `agent_id` and `sort_order` come from
  Studio migration `0009` (so it stops reading like an instruction someone still has to run). Keep FEAT-167's CHECK /
  UNIQUE out of the "deployed" description (spec Q2: not applied).
- Model tests: default validates, `sort_order` optional int, full-row construction; remove the workaround comment.

**NOT in scope**: the migration (TASK-5125), handler hooks (TASK-5127), `UserPrompts`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/bots.py` | MODIFY | New field, default fix, docstring |
| `packages/ai-parrot/tests/handlers/test_prompt_library.py` | MODIFY | Model tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.models.bots import PromptLibrary   # verified: tests/handlers/test_prompt_library.py:19 (re-export)
from parrot.models.bots import PromptLibrary, PromptCategory  # verified: packages/ai-parrot/src/parrot/models/bots.py:610,627
# bots.py already imports: Optional (:9), datetime (:13), Enum (:14), Field (datamodel, :15), Model (asyncdb.models, :16)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/bots.py
class PromptCategory(Enum):                               # :610 ; OTHER = "other" (:624)
class PromptLibrary(Model):                               # :627 ; docstring DDL :628-659
    prompt_id: uuid.UUID = Field(primary_key=True, required=False, default_factory=uuid.uuid4)
    chatbot_id: Optional[uuid.UUID] = Field(required=False, default=None)
    agent_id: Optional[str] = Field(required=False, default=None)               # :670
    prompt_category: str = Field(required=False, default=PromptCategory.OTHER)  # :674  ← the bug
    prompt_tags: list = Field(required=False, default_factory=list)
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: int = Field(required=False)                                     # :677
    updated_at: datetime = Field(required=False, default=datetime.now)          # :678
    class Meta: driver="pg"; name="prompt_library"; schema="navigator"; strict=True; frozen=False
```

### Does NOT Exist
- ~~A second `PromptLibrary` definition~~: `parrot.handlers.models` only re-exports it (one definition).
- ~~`PromptLibrary.sort_order`~~ before this task.
- ~~FEAT-167's CHECK / UNIQUE~~ in any database.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/models/bots.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/handlers/test_prompt_library.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/bots.py#PromptLibrary",
    "sym:packages/ai-parrot/src/parrot/models/bots.py#PromptCategory"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Replace the `prompt_category` line and add `sort_order` after `agent_id` — *why*: spec §2 Data Models.
2. Rewrite the docstring DDL — *why*: the current text documents DDL that never ran and misled FEAT-167.
3. Add the three model tests and drop the workaround comment — *why*: spec §4 Unit Tests; the full-row test is the one
   that would have caught the strict-model trap.

### `packages/ai-parrot/src/parrot/models/bots.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'prompt_category: str = Field(required=False, default=PromptCategory.OTHER)' bots.py)
# REPLACE that line (verified: bots.py:674) with:
    prompt_category: str = Field(required=False, default=PromptCategory.OTHER.value)

# occurrences: 1 (verified: grep -c '    agent_id: Optional[str] = Field(required=False, default=None)' bots.py)
# AFTER — insert below `    agent_id: Optional[str] = Field(required=False, default=None)` (verified: bots.py:670)
    sort_order: Optional[int] = Field(required=False, default=None)
```
**Why**: the string default validates under `strict`; `sort_order` must exist before any database has the column.

### `packages/ai-parrot/tests/handlers/test_prompt_library.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'prompt_category="other",  # use string value; Enum default has pre-existing issue')
# REMOVE that argument line in test_agent_id_field_accepts_slug (:35); the default now validates.

    def test_prompt_category_default_validates(self):
        """No prompt_category → builds and defaults to the string "other"."""
        p = PromptLibrary(chatbot_id=uuid.uuid4(), title="t", query="q")
        assert p.prompt_category == "other"

    def test_sort_order_optional_int(self):
        """sort_order exists, defaults to None and accepts an int."""
        # FILL IN: default None; PromptLibrary(..., sort_order=3).sort_order == 3

    def test_model_builds_from_full_row(self):
        """Every DB column (incl. agent_id, sort_order) builds the strict model — what asyncdb does on SELECT *."""
        # FILL IN: dict with prompt_id, chatbot_id, agent_id=None, title, query, description, prompt_category,
        #          prompt_tags, created_at, created_by, updated_at, sort_order; PromptLibrary(**row) must not raise
```

### FILL IN checklist
- [ ] `test_sort_order_optional_int` and `test_model_builds_from_full_row` bodies — bounded by spec AC3

---

## Acceptance Criteria

- [ ] `PromptLibrary(chatbot_id=…, title=…, query=…)` builds with `prompt_category == "other"`
- [ ] `PromptLibrary(**row)` with every database column, including `sort_order`, does not raise (spec AC3)
- [ ] The docstring describes the deployed table and names Studio migration `0009`
- [ ] Each new assertion goes red when the fix is reverted

---

## Validation Commands

- `pytest packages/ai-parrot/tests/handlers/test_prompt_library.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug prompt-library-writable-sort-order --feature-id FEAT-794`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the per-spec index
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5126 prompt-library-writable-sort-order verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
