---
type: Wiki Overview
title: 'TASK-1752: Adaptive Card renderer (templates + text fallback)'
id: doc:sdd-tasks-completed-task-1752-adaptive-card-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of FEAT-303 (spec §3). The renderer is the
relates_to:
- concept: mod:parrot.forms.renderers
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.cards
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.semantic
  rel: mentions
---

# TASK-1752: Adaptive Card renderer (templates + text fallback)

**Feature**: FEAT-303 — UX for Custom Engine Copilot Agents (Semantic UI Model → Adaptive Cards)
**Spec**: `sdd/specs/ux-custom-engine-copilot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1751
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of FEAT-303 (spec §3). The renderer is the
deterministic heart of the feature: pure functions from `SemanticUIResult` to
Adaptive Card **1.4** JSON (plain dicts), plus a total (never-raising)
plain-text fallback. Also owns the `messageBack` action payload construction
used for the interactive round-trip. Like `semantic.py`, this module must be
importable without `microsoft_agents.*` — cards are plain dicts; only
`agent.py` (TASK-1753) wraps them in SDK `Activity` objects.

---

## Scope

- Implement `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/cards.py`:
  - `class CardRenderError(Exception)` — raised when a result cannot be
    rendered within limits.
  - `render_card(result: SemanticUIResult, *, max_table_rows: int = 15, max_card_bytes: int = 25_000) -> dict`
    — dispatches on `result.payload.result_type` to one private template
    function per type:
    - **table**: header row + data rows via `ColumnSet`/`TextBlock`; truncate
      rows at `max_table_rows` and append a "showing N of M" `TextBlock` when
      truncated (M = `total_rows` if set, else `len(rows)`).
    - **metrics**: `FactSet` (or two-column `ColumnSet`) of label/value with
      optional delta text appended to the value.
    - **detail**: `FactSet` of labeled fields.
    - **status**: `Container` with level-styled `TextBlock` (map level →
      TextBlock `color`: success→Good, warning→Warning, error→Attention,
      info→Default) + message + optional details.
    - Empty table rows / empty metrics / empty fields → render the
      "no results" status-style card instead of an empty element.
    - Card skeleton: `{"type": "AdaptiveCard", "version": "1.4", "body": [...], "actions": [...]}`
      using ONLY: TextBlock, ColumnSet, Column, FactSet, Container,
      Action.Submit, Action.OpenUrl.
    - After building, serialize with `json.dumps` and raise `CardRenderError`
      if the byte length exceeds `max_card_bytes`.
  - `render_text(result: SemanticUIResult) -> str` — total plain/markdown
    fallback for ALL four payload types; must never raise (defensive
    formatting, tolerate empty payloads).
  - `build_card_attachment(card: dict) -> dict` — returns
    `{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}`.
  - Action building: `UIAction` with `prompt_template` →
    `{"type": "Action.Submit", "title": ..., "data": {"msteams": {"type": "messageBack", "text": <prompt_template.format(**params)>, "displayText": <title>}, "feat303_prompt": <filled prompt>}}`;
    `UIAction` with `url` → `{"type": "Action.OpenUrl", "title": ..., "url": ...}`.
    The duplicated `feat303_prompt` key is what the invoke shim (TASK-1754)
    reads when a surface delivers the click as an `adaptiveCard/action` invoke
    instead of a messageBack message.
- Write unit tests in
  `packages/ai-parrot-integrations/tests/unit/test_msagent_card_render.py`.

**NOT in scope**: sending activities / `Activity` construction (TASK-1753),
invoke handling (TASK-1754), config knobs on `MSAgentSDKConfig` (TASK-1753),
lazy exports (TASK-1753).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/cards.py` | CREATE | Renderer: templates, fallback, attachment, actions |
| `packages/ai-parrot-integrations/tests/unit/test_msagent_card_render.py` | CREATE | Unit tests per result type + limits + actions |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.
> Do NOT invent, guess, or assume anything not listed here. Verified 2026-07-14
> against `dev` @ 16b30ee1a.

### Verified Imports
```python
from __future__ import annotations
import json
from typing import Any

# From TASK-1751 (dependency — verify it is completed and merged in this worktree):
from parrot.integrations.msagentsdk.semantic import (
    SemanticUIResult, UIAction, TablePayload, MetricsPayload,
    DetailPayload, StatusPayload,
)
# NO microsoft_agents imports in this module. NO navconfig imports.
```

### Existing Signatures to Use
```python
# Attachment envelope shape to reproduce (verified at
# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py:729-732):
adaptive_card_attachment = {
    "contentType": "application/vnd.microsoft.card.adaptive",
    "content": adaptive_card,
}

# Existing card skeleton in the codebase pins version "1.4"
# (agent.py:708-711):
adaptive_card = {"type": "AdaptiveCard", "version": "1.4", "body": [...], "actions": [...]}

# SemanticUIResult (from TASK-1751):
#   .title: str | .summary: Optional[str]
#   .payload: TablePayload | MetricsPayload | DetailPayload | StatusPayload
#       (discriminated on .result_type)
#   .actions: list[UIAction]
# UIAction: .title / .prompt_template / .params / .url (XOR validated)
```

### Does NOT Exist
- ~~`parrot/integrations/msagentsdk/cards.py`~~ — YOU are creating it.
- ~~A Python `adaptivecards` or `adaptivecards-templating` package~~ — NOT a
  dependency and must not become one; build card JSON as plain dicts.
- ~~`parrot.forms.renderers.AdaptiveCardRenderer` as a base class~~ — exists
  (`packages/ai-parrot/src/parrot/forms/renderers/adaptive_card.py:69`) but is
  form-dialog-specific; do NOT import or extend it here.
- ~~`Activity` / `TurnContext` usage in cards.py~~ — SDK objects are
  TASK-1753's concern; this module returns dicts and strings only.
- ~~AC elements beyond the allowed set~~ — no Table element (AC 1.5+), no
  Action.Execute, no Icon, no Carousel; the spec pins the 1.4
  common-denominator set.

---

## Implementation Notes

### Pattern to Follow
```python
# Dispatch (deterministic, no LLM):
_RENDERERS = {
    "table": _render_table,
    "metrics": _render_metrics,
    "detail": _render_detail,
    "status": _render_status,
}

def render_card(result, *, max_table_rows=15, max_card_bytes=25_000):
    renderer = _RENDERERS.get(result.payload.result_type)
    if renderer is None:  # forward-compat guard
        raise CardRenderError(f"unknown result_type {result.payload.result_type!r}")
    card = renderer(result, max_table_rows=max_table_rows)
    if len(json.dumps(card).encode("utf-8")) > max_card_bytes:
        raise CardRenderError("card exceeds max_card_bytes")
    return card
```

### Key Constraints
- Pure/sync functions — no I/O, no logging, no async (spec §7 Patterns).
- `render_text()` is the LAST line of defense: it must handle every payload
  shape (including empty lists and None fields) and never raise.
- Missing `params` keys in `prompt_template.format(**params)` must not crash
  action building — fill defensively (e.g. `str.format_map` with a dict
  subclass returning `{key}` for missing keys) so a bad template degrades to
  literal braces rather than an exception.
- The "showing N of M" note must appear ONLY when rows were actually
  truncated.
- Escape/wrap user text via TextBlock `"wrap": True` (pattern:
  agent.py:713-719); card JSON must not embed raw newlines in FactSet titles.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py:680-741`
  — `_emit_adaptive_card()`: the existing card + attachment construction this
  module generalizes.
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py:51`
  — `TeamsCardRenderer`: style reference for building card dicts in tests.

---

## Acceptance Criteria

- [ ] All four result types render valid AC 1.4 dicts using only the allowed
  element set (asserted in tests by walking the card body `type` values)
- [ ] Truncation, size guard, empty-payload, and action-payload behaviors per scope
- [ ] `render_text()` never raises for any constructible `SemanticUIResult`
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/unit/test_msagent_card_render.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/cards.py`
- [ ] `cards.py` contains no `microsoft_agents` or `navconfig` imports

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/unit/test_msagent_card_render.py
import json
import pytest

from parrot.integrations.msagentsdk.cards import (
    CardRenderError, build_card_attachment, render_card, render_text,
)
from parrot.integrations.msagentsdk.semantic import (...)

ALLOWED_ELEMENTS = {"TextBlock", "ColumnSet", "Column", "FactSet", "Container"}
ALLOWED_ACTIONS = {"Action.Submit", "Action.OpenUrl"}


def _walk_types(node):  # yields every "type" value in the card tree
    ...


class TestRenderCard:
    def test_render_table_card(self, table_result): ...
    def test_render_metrics_card(self): ...
    def test_render_detail_card(self): ...
    def test_render_status_card_levels(self): ...          # all four levels
    def test_only_allowed_elements(self, table_result):
        card = render_card(table_result)
        assert set(_walk_types(card)) <= ALLOWED_ELEMENTS | ALLOWED_ACTIONS | {"AdaptiveCard"}
        assert card["version"] == "1.4"

    def test_table_truncation(self):                       # 20 rows, cap 15
        ...  # exactly 15 rendered + "showing 15 of 20" TextBlock present

    def test_no_truncation_note_when_under_cap(self): ...

    def test_card_size_guard(self):
        with pytest.raises(CardRenderError):
            render_card(huge_table_result, max_card_bytes=500)

    def test_empty_table_renders_no_results(self): ...


class TestActions:
    def test_prompt_action_messageback_payload(self):
        # Action.Submit with data.msteams.type == "messageBack",
        # data.msteams.text == filled prompt, data.feat303_prompt == same
        ...

    def test_url_action_openurl(self): ...

    def test_missing_param_does_not_raise(self): ...


class TestRenderText:
    @pytest.mark.parametrize("result", [...])  # all four types + empties
    def test_render_text_total(self, result):
        assert isinstance(render_text(result), str)


def test_build_card_attachment():
    att = build_card_attachment({"type": "AdaptiveCard"})
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1751 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `semantic.py` exists with the listed names (TASK-1751 output)
   - Confirm the attachment shape at `agent.py:729-732` is unchanged
4. **Update status** in `sdd/tasks/index/ux-custom-engine-copilot.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1752-adaptive-card-renderer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Implemented `render_card()` dispatching on `result_type` to
private per-type template functions (table/metrics/detail/status), all
using only TextBlock/ColumnSet/Column/FactSet/Container elements plus
Action.Submit/Action.OpenUrl. Table truncation with "showing N of M" note,
size guard via `CardRenderError`, empty-payload "no results" Container for
table/metrics/detail, `render_text()` total fallback wrapped in a
try/except so it can never raise, `build_card_attachment()`, and
`_build_action()` producing the `messageBack` + duplicated
`feat303_prompt` payload shape specified for the invoke shim. Missing
`prompt_template` params degrade to literal `{key}` via a
`_DefaultFormatDict`. 17/17 unit tests pass; ruff clean; zero
`microsoft_agents`/`navconfig` imports confirmed via grep.

**Deviations from spec**: none
