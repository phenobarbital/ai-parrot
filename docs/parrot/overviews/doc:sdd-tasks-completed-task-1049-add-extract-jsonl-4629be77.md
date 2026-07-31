---
type: Wiki Overview
title: 'TASK-1049: Add `ExtractJsonLd` BrowserAction Model'
id: doc:sdd-tasks-completed-task-1049-add-extract-jsonld-action-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The toolkit's plan-driven scraping system uses Pydantic-modelled
relates_to:
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.utils.jsonld_extractors
  rel: mentions
---

# TASK-1049: Add `ExtractJsonLd` BrowserAction Model

**Feature**: FEAT-154 — WebScrapingToolkit `extract_jsonld` Browser Action
**Spec**: `sdd/specs/webscrapingtoolkit-jsonld.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1048
**Assigned-to**: unassigned

---

## Context

The toolkit's plan-driven scraping system uses Pydantic-modelled
BrowserActions plus an `ACTION_MAP` lookup table and a discriminated
`ActionList` union. Adding a new action requires three coordinated edits in
`models.py`: declare the class, register it in `ACTION_MAP`, and extend
the discriminator union. Without all three, the LLM-facing JSON schema will
not advertise the action and `ScrapingStep.from_dict()` cannot deserialize
plans that mention it.

This task implements **Module 3** from the spec (§3 — *`ExtractJsonLd`
action model*) and is purely a model/registration change. No execution
behavior is added here — that lives in TASK-1050.

Reference: spec §2 *Architectural Design — Overview (2)*, §2 *Data Models*,
§3 *Module 3*, §6 *Codebase Contract* (existing `Extract` and `ACTION_MAP`
anchors).

---

## Scope

- Add a new `ExtractJsonLd(BrowserAction)` Pydantic class in
  `parrot_tools/scraping/models.py` immediately after the existing
  `Extract` class and before `Submit` (so JSON-LD-related actions stay
  grouped near each other for readability).
- Register the new class in `ACTION_MAP` under the key `"extract_jsonld"`.
- Add `ExtractJsonLd` to the `ActionList` discriminated union.
- Add four unit tests covering: model defaults, `ACTION_MAP` wiring,
  `ActionList` parser acceptance, and `ScrapingStep.from_dict` round-trip.

**NOT in scope**:
- The runtime executor handler (`_action_extract_jsonld`) — covered by
  TASK-1050.
- Adding a CSS/XPath `selector` field, `selector_type`, `extract_type`,
  `attribute`, `multiple`, or `fields` to the new class — JSON-LD
  extraction is selector-free; the spec explicitly forbids carrying those
  fields over from `Extract`.
- Modifying any other action class.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py` | MODIFY | Add `ExtractJsonLd` class, register in `ACTION_MAP`, extend `ActionList`. |
| `packages/ai-parrot-tools/tests/scraping/test_jsonld_action_model.py` | CREATE | Four unit tests for the new model + registration. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
# Already present at the top of parrot_tools/scraping/models.py (lines 1-11):
from __future__ import annotations
from typing import Optional, List, Dict, Any, Union, Literal, Annotated
from abc import ABC
import time
from dataclasses import dataclass, field
from pydantic import BaseModel, Field, field_validator, model_validator
from bs4 import BeautifulSoup
# No new imports are required for this task.
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:14
class BrowserAction(BaseModel, ABC):
    name: str = Field(default="", description="Optional name for this action")
    action: str = Field(default="", description="Action opcode used for union discrimination")
    description: str = Field(default="", description="Human-readable description of this action")
    timeout: Optional[int] = Field(default=None, ...)
    def get_action_type(self) -> str: ...   # line 24


# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:146 — REFERENCE PATTERN
class Extract(BrowserAction):
    name: str = "extract"
    action: Literal["extract"] = "extract"
    description: str = Field(default="Extract data from the page", ...)
    selector: str = Field(...)
    # ... (do NOT copy these fields verbatim — see "Does NOT Exist")
    extract_name: str = Field(default="", description="Key under which the result is stored ...")


# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:671
ActionList = Annotated[
    Union[
        Navigate, Click, Hover, Fill, Type, Select, Evaluate, PressKey,
        Refresh, Back, Scroll, GetCookies, SetCookies, Wait, Authenticate,
        AwaitHuman, AwaitKeyPress, AwaitBrowserEvent,
        GetText, GetHTML, Extract, Submit, WaitForDownload, UploadFile,
        Screenshot, Loop, Conditional,
    ],
    Field(discriminator="action"),
]
# Add `ExtractJsonLd` next to `Extract` for visual grouping.


# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:683-685
Authenticate.model_rebuild()
Loop.model_rebuild()
Conditional.model_rebuild()
# These rebuilds happen AFTER the ActionList declaration. Inserting
# ExtractJsonLd into the union is enough — no rebuild call is needed for
# the new class because it has no forward references to ActionList.


# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:688
ACTION_MAP = {
    "navigate": Navigate, "click": Click, ...
    "extract": Extract, "submit": Submit, ...
}
# Add the new entry next to "extract" for grouping:
#     "extract_jsonld": ExtractJsonLd,


# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:718
@dataclass
class ScrapingStep:
    action: BrowserAction
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScrapingStep":   # line 750
        action_type = data.get('action')
        action_class = ACTION_MAP.get(action_type)
        ...
# from_dict already routes via ACTION_MAP — no changes needed here once
# the new entry is registered.
```

### Does NOT Exist

- ~~`ExtractJsonLd.selector` / `.selector_type` / `.extract_type` /
  `.attribute` / `.multiple` / `.fields`~~ — JSON-LD extraction is selector-
  free. Do NOT carry these fields over from `Extract`. The new class has
  exactly four model fields beyond the `BrowserAction` base: `name`,
  `action`, `description`, `extract_name`, plus the new `types` field.
- ~~`ExtractJsonLD` (yelling-case acronym)~~ — Python convention is
  `ExtractJsonLd` (PascalCase, treat the acronym as a word).
- ~~`Extract.types`~~ — the existing `Extract` class has no `types`
  field. The new `types: Optional[List[str]]` lives only on
  `ExtractJsonLd`.
- ~~`ACTION_MAP.register("extract_jsonld", ExtractJsonLd)`~~ —
  `ACTION_MAP` is a plain `dict`. Add the entry by direct assignment in
  the literal.

---

## Implementation Notes

### Pattern to Follow

```python
# Insert IMMEDIATELY AFTER the existing `Extract` class (around line 191
# in the current models.py) and before `class Submit(BrowserAction)`:

class ExtractJsonLd(BrowserAction):
    """Extract structured data from JSON-LD blocks on the current page.

    Iterates every ``<script type="application/ld+json">`` block, walks
    the JSON graph (descending into ``@graph`` and arrays), and dispatches
    typed nodes through the shared ``EXTRACTOR_REGISTRY`` from
    ``parrot.utils.jsonld_extractors``. Result is a flat list of dicts,
    one per extracted ``JsonLdItem``, written to
    ``step_extracted[extract_name]``.

    Two filtering modes:
    - ``types=None`` (default): extract every registered ``@type``.
    - ``types=["Product", "Recipe"]``: only those types.
    """
    name: str = "extract_jsonld"
    action: Literal["extract_jsonld"] = "extract_jsonld"
    description: str = Field(
        default="Extract JSON-LD structured data",
        description="Extract structured data from <script type='application/ld+json'> blocks",
    )
    extract_name: str = Field(
        default="jsonld",
        description=(
            "Key under which the result list is stored in extracted_data. "
            "Falls back to the step's `name` field, then 'jsonld'."
        ),
    )
    types: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional whitelist of schema.org @type values to extract "
            "(e.g. ['Product', 'Recipe']). None = every type registered "
            "in EXTRACTOR_REGISTRY."
        ),
    )
```

### Key Constraints

- The `action: Literal["extract_jsonld"]` line is what the Pydantic
  discriminated union uses to dispatch — the string MUST match the
  `ACTION_MAP` key exactly.
- Default `extract_name="jsonld"` (NOT empty string) — the executor
  handler (TASK-1050) falls back to this when no name is set, and an empty
  default would land collisions in `step_extracted[""]`.
- `types: Optional[List[str]] = None` — a real `None` default, not an
  empty list. Empty list MUST mean "filter to nothing" (matching loader
  semantics in `WebScrapingLoader._jsonld_types`); `None` means "everything".
- Do not add any `field_validator` / `model_validator` — none are needed.
- Do not pre-validate that `types` strings are present in `EXTRACTOR_REGISTRY`
  at model-construction time — keep the model decoupled from the registry
  so it remains importable in environments where the core registry hasn't
  loaded yet (e.g. JSON schema generation for LLM tooling).

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:146-190`
  — `Extract` class (reference for field shape and Field-description style).
- `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:671-679`
  — `ActionList` discriminated union (insertion point).
- `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:688-716`
  — `ACTION_MAP` literal (insertion point).
- `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:749-767`
  — `ScrapingStep.from_dict` (round-trip path; uses `ACTION_MAP`).

---

## Acceptance Criteria

- [ ] `class ExtractJsonLd(BrowserAction)` exists in
      `parrot_tools/scraping/models.py` between `Extract` and `Submit`.
- [ ] The class has exactly these declared fields beyond the base:
      `name`, `action`, `description`, `extract_name`, `types`.
- [ ] `ACTION_MAP["extract_jsonld"] is ExtractJsonLd`.
- [ ] `ExtractJsonLd` is included in the `ActionList` discriminated union.
- [ ] Pydantic accepts `{"action":"extract_jsonld","types":["Product"]}`
      and returns an `ExtractJsonLd` instance with `types == ["Product"]`.
- [ ] `ScrapingStep.from_dict({"action":"extract_jsonld",...})` returns a
      `ScrapingStep` whose `.action` is an `ExtractJsonLd` instance.
- [ ] `to_dict` round-trip: `ScrapingStep.from_dict(step.to_dict()) == step`
      for an `ExtractJsonLd`-based step (semantic equality on action fields).
- [ ] All new tests pass:
      `pytest packages/ai-parrot-tools/tests/scraping/test_jsonld_action_model.py -v`.
- [ ] No linting / type errors:
      `ruff check packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`
      and `mypy packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/scraping/test_jsonld_action_model.py

"""Tests for the ExtractJsonLd BrowserAction model — FEAT-154 / TASK-1049."""

import pytest
from pydantic import TypeAdapter

from parrot.tools.scraping.models import (
    ACTION_MAP,
    ActionList,
    ExtractJsonLd,
    ScrapingStep,
)


class TestExtractJsonLdModel:

    def test_extract_jsonld_model_defaults(self) -> None:
        """ExtractJsonLd carries the documented default field values."""
        a = ExtractJsonLd()
        assert a.action == "extract_jsonld"
        assert a.name == "extract_jsonld"
        assert a.extract_name == "jsonld"
        assert a.types is None
        assert a.description.lower().startswith("extract json-ld")

    def test_extract_jsonld_in_action_map(self) -> None:
        """ACTION_MAP routes the discriminator string to the new class."""
        assert ACTION_MAP["extract_jsonld"] is ExtractJsonLd

    def test_action_list_accepts_extract_jsonld(self) -> None:
        """The discriminated ActionList parses an extract_jsonld payload."""
        adapter = TypeAdapter(ActionList)
        payload = {"action": "extract_jsonld", "types": ["Product", "Recipe"]}
        parsed = adapter.validate_python(payload)
        assert isinstance(parsed, ExtractJsonLd)
        assert parsed.types == ["Product", "Recipe"]

    def test_scrapingstep_from_dict_extract_jsonld(self) -> None:
        """ScrapingStep round-trips an extract_jsonld step via ACTION_MAP."""
        data = {
            "action": "extract_jsonld",
            "extract_name": "products",
            "types": ["Product"],
        }
        step = ScrapingStep.from_dict(data)
        assert isinstance(step.action, ExtractJsonLd)
        assert step.action.extract_name == "products"
        assert step.action.types == ["Product"]
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-1048 is in `sdd/tasks/completed/`** — this task does not
   *import* from the moved module, but the next task does.
2. **Read** `parrot_tools/scraping/models.py` — confirm line numbers in
   the contract are still accurate (line shifts of ±5 are normal as the
   file is edited).
3. **Update status** → `"in-progress"` in
   `sdd/tasks/index/webscrapingtoolkit-jsonld.json`.
4. **Implement** following the pattern above.
5. **Verify** all acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
