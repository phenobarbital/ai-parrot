# TASK-2263: Block Models, I18nText & DocumentMeta

**Feature**: FEAT-301 — Themed Component Catalog — HTML Renderer v2
**Spec**: `sdd/specs/infographic-theme-catalog-a2ui.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec (§3). This is the foundation task: every
other task in FEAT-301 except TASK-2251 (themes) and TASK-2258 (deps) depends
on the model names, field names, and `type` discriminator literals defined
here. Getting the field names right matters more than anything else in this
feature — the HTML renderer, the system prompt, and the A2UI adapter all read
these fields by name.

The infographic pipeline currently ships 15 block types. This task extends it
to 19 (`chain`, `steps`, `code`, `card_grid`), adds the bilingual `I18nText`
union, and adds `DocumentMeta` for document chrome.

---

## Scope

- Add 4 members to `BlockType`: `CHAIN = "chain"`, `STEPS = "steps"`,
  `CODE = "code"`, `CARD_GRID = "card_grid"`.
- Add `I18nText = Union[str, Dict[str, str]]` type alias with a docstring.
- Add support models: `ChainNode`, `StepItem`, `GridCard`, `ChangelogEntry`.
- Add block models: `ChainBlock`, `StepsBlock`, `CodeBlock`, `CardGridBlock`.
- Add `DocumentMeta` model.
- Extend the `InfographicBlock` union with the 4 new block models.
- Add `InfographicResponse.document_meta: Optional[DocumentMeta] = None`.
- Update `packages/ai-parrot/src/parrot/models/__init__.py` exports: add the 4
  new block models, their support models, `DocumentMeta`, `ChangelogEntry`,
  `I18nText`, **and** the 3 currently-missing `AccordionBlock`,
  `ChecklistBlock`, `TabViewBlock` (spec §7 Known Risk 1).
- Update the existing assertion `tests/test_infographic_models.py:38`
  (`assert len(BlockType) == 15`) → `19`.
- Write unit tests for all new models.

**NOT in scope**:
- ThemeConfig v2 fields, `CodePalette`, `MethodBadgePalette`, `derive_soft()`,
  the `petrol` theme → TASK-2251.
- Any change to `infographic_html.py` (renderers, `_BLOCK_MODEL_MAP`, i18n
  emitter, chrome, CSS) → TASK-2252 / 2253 / 2254 / 2255.
- Any change to `INFOGRAPHIC_SYSTEM_PROMPT` → TASK-2256.
- Any change to the A2UI adapter → TASK-2257.
- Making renderers actually *render* the new blocks — this task only defines
  and validates the models.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | Enum members, `I18nText`, 4 block models + support models, `DocumentMeta`, `ChangelogEntry`, union, `document_meta` field |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | Add new exports to the `from .infographic import (...)` block (lines 24-49) |
| `tests/test_infographic_models.py` | MODIFY | Update `len(BlockType) == 15` → `19`; add tests for new models |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-19.

### Verified Imports

```python
# already present at packages/ai-parrot/src/parrot/models/infographic.py
from typing import List, Optional, Any, Annotated, ClassVar, Dict, Literal, Tuple, Union  # line 25
from enum import Enum                                                                     # line 38
from pydantic import BaseModel, Discriminator, Field, field_validator, model_validator     # line 39
```

No new third-party imports are needed. `Union`, `Dict`, `Literal`, `Optional`,
`List` are all already imported — do NOT re-import them.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/infographic.py

class BlockType(str, Enum):          # line 71 — 15 members, TAB_VIEW = "tab_view" is last (line 87)
    TITLE = "title"
    HERO_CARD = "hero_card"
    SUMMARY = "summary"
    CHART = "chart"
    BULLET_LIST = "bullet_list"
    TABLE = "table"
    IMAGE = "image"
    QUOTE = "quote"
    CALLOUT = "callout"
    DIVIDER = "divider"
    TIMELINE = "timeline"
    PROGRESS = "progress"
    ACCORDION = "accordion"
    CHECKLIST = "checklist"
    TAB_VIEW = "tab_view"            # line 87 — append the 4 new members AFTER this

InfographicBlock = Union[            # lines 825-841 — 15 members, TabViewBlock last
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock, BulletListBlock,
    TableBlock, ImageBlock, QuoteBlock, CalloutBlock, DividerBlock,
    TimelineBlock, ProgressBlock, AccordionBlock, ChecklistBlock, TabViewBlock,
]

class InfographicResponse(BaseModel):                                    # line 848
    template: Optional[str] = Field(None, description=...)               # line 854
    theme: Optional[str] = Field(None, description=...)                  # line 858
    blocks: List[Annotated[InfographicBlock, Discriminator("type")]] = Field(...)  # line 862
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)     # line 866

    @model_validator(mode="before")
    @classmethod
    def _normalise_payload(cls, values: Any) -> Any: ...   # fixes common LLM output mismatches

# lines 933-935 — forward-ref resolution; these calls already exist, do NOT duplicate them
AccordionItem.model_rebuild()
TabPane.model_rebuild()
InfographicResponse.model_rebuild()
```

```python
# packages/ai-parrot/src/parrot/models/__init__.py:24-49 — the export block to extend
from .infographic import (
    BlockType, ChartType, TrendDirection, CalloutLevel,
    InfographicBlock, InfographicResponse,
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock, ChartDataSeries,
    BulletListBlock, TableBlock, ImageBlock, QuoteBlock, CalloutBlock,
    DividerBlock, TimelineBlock, TimelineEvent, ProgressBlock, ProgressItem,
    ThemeConfig, ThemeRegistry, theme_registry,
)
```

```python
# tests/test_infographic_models.py:38 — the assertion that MUST be updated
assert len(BlockType) == 15
```

### Does NOT Exist

- ~~`parrot.models.infographic.I18nText`~~ — create it
- ~~`parrot.models.infographic.ChainBlock` / `ChainNode`~~ — create them
- ~~`parrot.models.infographic.StepsBlock` / `StepItem`~~ — create them
- ~~`parrot.models.infographic.CodeBlock`~~ — create it
- ~~`parrot.models.infographic.CardGridBlock` / `GridCard`~~ — create them
- ~~`parrot.models.infographic.DocumentMeta` / `ChangelogEntry`~~ — create them
- ~~`InfographicResponse.document_meta`~~ — field does not exist yet
- ~~`AccordionBlock` / `ChecklistBlock` / `TabViewBlock` in `parrot.models.__init__`~~ —
  NOT re-exported today; `infographic_html.py` imports them straight from
  `...models.infographic` (lines 30-60)
- ~~`packages/ai-parrot/tests/models/test_infographic*.py`~~ — the model tests
  do NOT live under `packages/ai-parrot/tests/models/`. They are at repo root:
  `tests/test_infographic_models.py`
- ~~`tests/models/` and `tests/outputs/` directories~~ — do not exist; the spec
  §5 acceptance-criteria paths are wrong, use the real paths below

---

## Implementation Notes

### Pattern to Follow

Block models are plain `BaseModel` — **no** `frozen=True`, **no**
`extra="forbid"` (spec §7, finding F108). The `type` field must be first and
must be a `Literal`, because `InfographicBlock` is discriminated on it:

```python
class CodeBlock(BaseModel):
    """Code snippet block with optional language hint and line highlights."""
    type: Literal["code"] = "code"
    title: Optional[I18nText] = None
    code: str = Field(..., description="Raw source text, rendered verbatim")
    language: Optional[str] = Field(None, description="Language hint, e.g. 'python'")
    highlight_lines: Optional[List[int]] = Field(None, description="1-based line numbers")
```

Field shapes from spec §2 "Data Models" — use these exact names, downstream
tasks are written against them:

- `ChainBlock`: `type`, `title: Optional[I18nText]`, `nodes: List[ChainNode]`,
  `direction: Literal["horizontal", "vertical"] = "horizontal"`
- `StepsBlock`: `type`, `title: Optional[I18nText]`, `steps: List[StepItem]`,
  `style: Literal["numbered", "icon"] = "numbered"`
- `CodeBlock`: `type`, `title`, `code: str`, `language: Optional[str]`,
  `highlight_lines: Optional[List[int]]`
- `CardGridBlock`: `type`, `title`, `cards: List[GridCard]`,
  `columns: int = Field(default=3, ge=1, le=6)`
- `DocumentMeta`: `version`, `status`, `author`, `changelog: Optional[List[ChangelogEntry]]`
- `ChangelogEntry`: `version: str`, `date: str`, `summary: I18nText`

For the support models, keep them minimal and give every text field
`I18nText` where a human will read it (`ChainNode.label`, `StepItem.label` /
`.description`, `GridCard.title` / `.body`). Follow `TimelineEvent` /
`ProgressItem` (already in this file) for the support-model style.

### Key Constraints

- **Backward compatibility is a hard requirement.** `I18nText` is
  `Union[str, Dict[str, str]]`, so every existing payload that passes a plain
  `str` keeps validating unchanged. Do not reorder the union — `str` must come
  first so Pydantic v2 prefers it in smart-union mode.
- `document_meta` must be `Optional[...] = None`. Existing `InfographicResponse`
  payloads have no such key and must keep validating.
- Place the 4 new block models **before** the `InfographicBlock` union
  (line 825) so the union can reference them.
- `model_rebuild()` calls at lines 933-935 already exist and will pick up the
  widened union automatically (spec §7) — do not add new ones.
- Google-style docstrings on every new model, per project convention.

### References in Codebase

- `packages/ai-parrot/src/parrot/models/infographic.py` — `TitleBlock`,
  `HeroCardBlock`, `TimelineBlock`/`TimelineEvent`, `ProgressBlock`/`ProgressItem`
  are the patterns to copy
- `tests/test_infographic_models.py` — existing model-test style

---

## Acceptance Criteria

- [ ] `BlockType` has exactly 19 members
- [ ] `ChainBlock`, `StepsBlock`, `CodeBlock`, `CardGridBlock` validate with the
      field names listed above
- [ ] `I18nText` accepts a plain `str` AND a `{"en": ..., "es": ...}` dict
- [ ] `CardGridBlock.columns` rejects `0` and `7` (`ge=1, le=6`)
- [ ] `InfographicResponse` validates with `document_meta=None` and with a fully
      populated `DocumentMeta`
- [ ] An existing 15-block payload still validates unchanged (regression)
- [ ] The 4 new block types resolve through `Discriminator("type")` — i.e.
      `InfographicResponse(blocks=[{"type": "code", "code": "x"}])` produces a
      `CodeBlock`, not a dict
- [ ] `tests/test_infographic_models.py:38` updated to `19` and passing
- [ ] Imports work: `from parrot.models import ChainBlock, StepsBlock, CodeBlock, CardGridBlock, DocumentMeta, I18nText, AccordionBlock, ChecklistBlock, TabViewBlock`
- [ ] Tests pass: `pytest tests/test_infographic_models.py -v`
- [ ] Existing renderer tests still pass: `pytest tests/test_infographic_html.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/infographic.py`

---

## Test Specification

```python
# tests/test_infographic_models.py (extend the existing file)
import pytest
from pydantic import ValidationError

from parrot.models.infographic import (
    BlockType, InfographicResponse, I18nText,
    ChainBlock, ChainNode, StepsBlock, StepItem,
    CodeBlock, CardGridBlock, GridCard,
    DocumentMeta, ChangelogEntry,
)


def test_block_type_enum_19_members():
    assert len(BlockType) == 19
    for member in ("CHAIN", "STEPS", "CODE", "CARD_GRID"):
        assert hasattr(BlockType, member)


def test_chain_block_model():
    block = ChainBlock(nodes=[ChainNode(label="A"), ChainNode(label="B")])
    assert block.type == "chain"
    assert block.direction == "horizontal"


def test_steps_block_model():
    block = StepsBlock(steps=[StepItem(label="Step 1", description="Do thing")])
    assert block.style == "numbered"


def test_code_block_model():
    block = CodeBlock(code="print('hi')", language="python", highlight_lines=[1])
    assert block.type == "code"


def test_card_grid_block_model():
    block = CardGridBlock(cards=[GridCard(title="C1", body="x")], columns=2)
    assert block.columns == 2
    with pytest.raises(ValidationError):
        CardGridBlock(cards=[], columns=7)


def test_i18n_text_plain_str():
    assert CodeBlock(code="x", title="Plain").title == "Plain"


def test_i18n_text_dict():
    block = CodeBlock(code="x", title={"en": "Hello", "es": "Hola"})
    assert block.title["es"] == "Hola"


def test_document_meta_optional():
    resp = InfographicResponse(blocks=[{"type": "divider"}])
    assert resp.document_meta is None


def test_document_meta_populated():
    resp = InfographicResponse(
        blocks=[{"type": "divider"}],
        document_meta=DocumentMeta(
            version="1.0", status="approved", author="Jesus",
            changelog=[ChangelogEntry(version="1.0", date="2026-08-19",
                                      summary={"en": "First", "es": "Primero"})],
        ),
    )
    assert resp.document_meta.changelog[0].version == "1.0"


def test_new_blocks_resolve_through_discriminator():
    resp = InfographicResponse(blocks=[{"type": "code", "code": "x"}])
    assert isinstance(resp.blocks[0], CodeBlock)


def test_infographic_response_backward_compat():
    """A payload using only the original 15 block types still validates."""
    resp = InfographicResponse(blocks=[
        {"type": "title", "title": "T"},
        {"type": "hero_card", "label": "L", "value": "42"},
        {"type": "divider"},
    ])
    assert len(resp.blocks) == 3
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none; this task can start immediately
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm the line numbers still point at the listed constructs (the file is
     ~1250 lines; line numbers drift as you edit — re-grep rather than trusting them)
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists
4. **Update status** in `sdd/tasks/index/infographic-theme-catalog-a2ui.json` →
   `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2263-block-models-i18ntext.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
