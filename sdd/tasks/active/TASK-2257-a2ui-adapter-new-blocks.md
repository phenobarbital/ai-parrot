# TASK-2257: A2UI Adapter — Explicit Converters for the 4 New Block Types

**Feature**: FEAT-301 — Themed Component Catalog — HTML Renderer v2
**Spec**: `sdd/specs/infographic-theme-catalog-a2ui.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2263
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec (§3). `infographic_response_to_envelope()`
lowers an `InfographicResponse` into an A2UI `CreateSurface`. Its `_Converter.walk()`
dispatches known block types to dedicated methods and sends everything else to
`_card_like()`, whose final fallback reads `block.get("content")` /
`block.get("text")` — neither of which exists on `chain`, `steps`, `code`, or
`card_grid`. So today those four blocks would lower to a `Card` with an **empty
body**: no error, just silent data loss.

This task adds four explicit converters. Per spec §1 (Non-Goals), v1 strategy is
**Card-based lowering with semantic hints** — no new A2UI catalog components.

---

## Scope

- Add `_chain(self, block) -> dict` — nodes as a labeled sequence in the Card body.
- Add `_steps(self, block) -> dict` — steps as a numbered body.
- Add `_code(self, block) -> dict` — code in the body, `badge` = language.
- Add `_card_grid(self, block) -> list[dict]` — one `Card` descriptor per grid card.
- Add four `elif` branches to `walk()` **before** the `else: _card_like()`
  fallback. `card_grid` returns a list, so it needs the multi-descriptor loop
  shape that `progress` already uses.
- Write unit tests.

**NOT in scope**:
- New A2UI catalog components for these block types — explicitly a spec Non-Goal.
  Use the existing `Card`.
- Changes to `builders.py`, the catalog, `CreateSurface`, or any renderer.
- `_flatten_container()` — the new blocks are leaves, not containers.
- Touching the 5 existing converter methods or `_card_like()`'s existing branches.
- Model changes → TASK-2263. HTML rendering → TASK-2253.
- I18n handling beyond the flattening rule below — the A2UI envelope is
  single-language in v1.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | 4 `_Converter` methods + 4 `walk()` branches |
| `packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py` | MODIFY | Converter tests (550-line existing file) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-19.

### Verified Imports

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py — full import block
from __future__ import annotations                          # line 62
from typing import Any, Optional                            # line 64
from parrot.outputs.a2ui.builders import build_infographic  # line 66
from parrot.outputs.a2ui.models import CreateSurface        # line 67
```

No new imports needed. Note this module uses `from __future__ import annotations`
and lowercase builtin generics (`dict[str, Any]`, `list[dict]`) — match that
style, not `Dict`/`List`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py

CHART_TYPE_MAP: dict[str, str] = {...}          # lines 76-89 (12 entries)
_MAX_NESTING_DEPTH = 4                          # line 95

def _as_dict(value: Any) -> dict[str, Any]:     # line 100 — model/dict -> dict
def _clean(props: dict[str, Any]) -> dict[str, Any]:  # line 112 — DROPS None values
def _descriptor(component: str, properties: dict[str, Any]) -> dict[str, Any]:  # line 117
    """Build a nested composite child descriptor for the Infographic component."""
    return {"component": component, "properties": _clean(properties)}
def _unique(name: str, taken: dict[str, int]) -> str:  # line 122
def _lines(items: list[Any], *, ordered: bool = False) -> str:  # line 129
    """Render list items as a deterministic text block for a ``Card`` body."""

class _SectionAccumulator:                      # line 138
    # .open(heading=None, text=None), .add(descriptor), .set_text(text) -> bool

class _Converter:                               # line 188
    data_model: dict[str, dict[str, Any]]       # line 192
    def _chart(self, block) -> dict:            # line 204
    def _table(self, block) -> dict:            # line 236
    def _hero_card(self, block) -> dict:        # line 261 — returns _descriptor("KPICard", …)
    def _timeline(self, block) -> dict:         # line 272 — returns _descriptor("Timeline", …)
    def _progress(self, block) -> list[dict]:   # line 287 — returns a LIST of KPICard descriptors
    def _card_like(self, block, block_type) -> dict:  # line 299
    def walk(self, blocks, sections, *, depth=0, seen_title=False) -> tuple[Optional[str], Optional[str], bool]:  # line 357
    def _flatten_container(self, block, block_type, sections, depth):  # line 416

def infographic_response_to_envelope(           # line 447
    response: Any, *, surface_id: str = "infographic",
    title: Optional[str] = None, theme: Optional[str] = None,
) -> CreateSurface:
```

`walk()`'s dispatch tail, verbatim (lines ~400-412) — insert the new branches
between `progress` and `else`:

```python
            if block_type == "chart":
                sections.add(self._chart(block))
            elif block_type == "table":
                sections.add(self._table(block))
            elif block_type == "hero_card":
                sections.add(self._hero_card(block))
            elif block_type == "timeline":
                sections.add(self._timeline(block))
            elif block_type == "progress":
                for descriptor in self._progress(block):
                    sections.add(descriptor)
            else:
                sections.add(self._card_like(block, block_type))
```

The `_progress` pattern is the model for `card_grid` (list-returning converter).

`_card_like`'s final fallback, which is what the new blocks hit today:

```python
        # summary (title present or text slot taken) and any unknown block type
        return _descriptor(
            "Card",
            {
                "title": block.get("title"),
                "body": block.get("content") or block.get("text") or "",
            },
        )
```

The `Card` catalog component's property vocabulary — **verified** at
`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/card.py`:

```python
CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "body": {"type": "string"},
        "image": {"type": "string"},
        "badge": {"type": "string"},
        "footer": {"type": "string"},
    },
    "required": ["title"],
}
```

Only those six properties exist. All are strings. Although `title` is listed as
required, existing converters routinely pass `title=None` (e.g. the `quote`
branch never sets one) and `_clean()` drops it — nested-child lowering does not
enforce `required`. **Follow that precedent**: pass the real title or `None`, do
not fabricate a placeholder title.

### Does NOT Exist

- ~~`_Converter._chain()` / `._steps()` / `._code()` / `._card_grid()`~~ — create all four
- ~~a `Chain` / `Steps` / `Code` / `CardGrid` A2UI catalog component~~ — the
  registered components are exactly: `Card`, `KPICard`, `Chart`, `DataTable`,
  `Form`, `Infographic`, `Map`, `Report`, `Timeline`
  (`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/`)
- ~~a `Card.language` / `.code` / `.columns` property~~ — the six above are all
  that exist; a language hint goes in `badge`
- ~~a `CodeBlock` A2UI property for syntax highlighting~~ — none
- ~~`_lines()` accepting a `numbered=` kwarg~~ — the kwarg is `ordered`
- ~~`_descriptor()` validating the component name~~ — it does not; an unknown
  component name fails later, at composite lowering, with `CatalogValidationError`
- ~~I18nText handling anywhere in this adapter~~ — every converter assumes `str`.
  See the flattening rule below.

---

## Implementation Notes

### I18nText flattening (decision)

`ChainNode.label`, `StepItem.label`, `GridCard.title`, and the blocks' `title`
fields are `I18nText` (TASK-2263), so a bilingual payload reaches this adapter as
a `dict`. The A2UI envelope is single-language in v1 and `Card` properties are
typed `string`.

**Decision: flatten with a small local helper** — prefer the `"en"` key, else the
first value, else `""`. Add it beside `_as_dict` / `_clean` as a module-level
function:

```python
def _text(value: Any) -> Optional[str]:
    """Flatten an ``I18nText`` value to a single string for A2UI properties."""
```

Use it on every text field the four new converters read. Do **not** retrofit it
onto the 5 existing converters — that is out of scope and would change their
output for bilingual payloads mid-feature.

### Per-converter guidance

- **`_chain`** → `Card` with `title` = block title, `body` = node labels joined
  by an arrow separator (` → `). Deterministic: no `dict` iteration beyond the
  declared node order. Put `direction` in `subtitle` only if it is `"vertical"`
  (the non-default), so horizontal chains stay clean.
- **`_steps`** → `Card` with `body` = `_lines(...)` over
  `"{label} — {description}"` strings with `ordered=True`, reusing the existing
  helper rather than hand-numbering.
- **`_code`** → `Card` with `body` = the raw code (no fences, no escaping — A2UI
  lowering handles presentation), `badge` = `language`. Do **not** include
  `highlight_lines`; there is no `Card` property for it and inventing one breaks
  catalog validation.
- **`_card_grid`** → a **list** of `Card` descriptors, one per `GridCard`
  (`title`, `body`). Mirror `_progress`'s shape and the loop in `walk()`.
  `columns` is a layout hint with no A2UI equivalent — drop it.

### Key Constraints

- **Purity/determinism is a documented guarantee** of
  `infographic_response_to_envelope` ("the same response always yields an
  identical envelope"). No `Date.now()`, no randomness, no set iteration, no
  dict-ordering assumptions beyond insertion order.
- Blocks arrive as **dicts**, already normalised by `_as_dict()` in `walk()`.
  Use `block.get(...)`, never attribute access.
- `_clean()` already strips `None`; do not pre-filter or substitute `""` for
  absent optional properties.
- Only the six `Card` properties. Extra keys would surface as
  `CatalogValidationError` at lowering time.
- Insert the new branches **before** `else: _card_like(...)`, and do not alter
  the earlier branches' order — `walk()`'s title/divider/container/summary
  special cases above the dispatch chain must stay untouched.
- Match the module's `from __future__ import annotations` + lowercase-generics style.

### References in Codebase

- `adapters/infographic.py:287` `_progress` — the list-returning converter pattern
- `adapters/infographic.py:272` `_timeline` — the `_clean` + `_descriptor` idiom
- `adapters/infographic.py:299` `_card_like` — the Card-shaped branches
- `catalog/components/card.py` — the authoritative `Card` property list
- `packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py` —
  existing adapter test style

---

## Acceptance Criteria

- [ ] `walk()` has explicit branches for `chain`, `steps`, `code`, `card_grid`,
      all placed before the `_card_like()` fallback
- [ ] `_chain()` produces a `Card` whose body contains every node label
- [ ] `_steps()` produces a `Card` whose body is ordered and contains each
      step's label and description
- [ ] `_code()` produces a `Card` with `body` = the code and `badge` = the language
- [ ] `_code()` omits `badge` when `language` is absent (via `_clean`)
- [ ] `_card_grid()` produces one `Card` descriptor per grid card, in order
- [ ] Every descriptor uses only the six documented `Card` properties
- [ ] A bilingual title (`{"en": …, "es": …}`) flattens to the `"en"` string, not
      a stringified dict
- [ ] The same input twice yields identical output (determinism)
- [ ] `infographic_response_to_envelope()` succeeds on a payload containing all
      **19** block types and returns a valid `CreateSurface`
- [ ] The 5 existing converters and their outputs are unchanged (existing tests
      pass untouched)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py (extend)
import pytest

from parrot.outputs.a2ui.adapters.infographic import infographic_response_to_envelope


def _cards(envelope):
    """Collect every nested child descriptor from the Infographic component."""
    component = envelope.components[0] if hasattr(envelope, "components") else None
    # use whatever accessor the existing tests in this file already use
    ...


class TestNewBlockConverters:
    def test_a2ui_chain_to_card(self):
        env = infographic_response_to_envelope({
            "blocks": [{"type": "chain", "title": "Flow",
                        "nodes": [{"label": "A"}, {"label": "B"}]}],
        })
        body = _first_card_body(env)
        assert "A" in body and "B" in body

    def test_a2ui_steps_to_card(self):
        env = infographic_response_to_envelope({
            "blocks": [{"type": "steps",
                        "steps": [{"label": "One", "description": "do it"}]}],
        })
        body = _first_card_body(env)
        assert "One" in body and "do it" in body

    def test_a2ui_code_to_card(self):
        env = infographic_response_to_envelope({
            "blocks": [{"type": "code", "code": "print(1)", "language": "python"}],
        })
        props = _first_card_props(env)
        assert props["body"] == "print(1)"
        assert props["badge"] == "python"

    def test_a2ui_code_omits_badge_without_language(self):
        env = infographic_response_to_envelope({
            "blocks": [{"type": "code", "code": "x"}],
        })
        assert "badge" not in _first_card_props(env)

    def test_a2ui_card_grid_to_cards(self):
        env = infographic_response_to_envelope({
            "blocks": [{"type": "card_grid", "columns": 2, "cards": [
                {"title": "C1", "body": "b1"}, {"title": "C2", "body": "b2"},
            ]}],
        })
        titles = _card_titles(env)
        assert titles == ["C1", "C2"]

    def test_only_known_card_properties(self):
        env = infographic_response_to_envelope({
            "blocks": [{"type": "code", "code": "x", "language": "py",
                        "highlight_lines": [1]}],
        })
        allowed = {"title", "subtitle", "body", "image", "badge", "footer"}
        assert set(_first_card_props(env)) <= allowed

    def test_i18n_title_flattened(self):
        env = infographic_response_to_envelope({
            "blocks": [{"type": "code", "code": "x",
                        "title": {"en": "Title", "es": "Titulo"}}],
        })
        assert _first_card_props(env)["title"] == "Title"

    def test_deterministic(self):
        payload = {"blocks": [{"type": "chain", "nodes": [{"label": "A"}]}]}
        a = infographic_response_to_envelope(payload)
        b = infographic_response_to_envelope(payload)
        assert a.model_dump() == b.model_dump()


class TestAllBlocksEnvelope:
    def test_a2ui_envelope_new_blocks(self, all_blocks_payload):
        """All 19 block types lower without error."""
        env = infographic_response_to_envelope(all_blocks_payload)
        assert env is not None
```

> `_first_card_body` / `_first_card_props` / `_card_titles` are local helpers —
> implement them using whatever envelope-traversal helpers the existing 550-line
> test file already defines. Do not invent a new accessor if one is there.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2263 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Re-read `_card_like`, `_progress`, and `walk()`'s dispatch tail
   - Re-read `catalog/components/card.py` to confirm the property list
   - Read the existing test file first and reuse its traversal helpers
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists
4. **Update status** in `sdd/tasks/index/infographic-theme-catalog-a2ui.json` →
   `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2257-a2ui-adapter-new-blocks.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**I18n flattening**: locale-preference rule actually implemented

**Deviations from spec**: none | describe if any
