# TASK-2256: Document All 19 Block Types in INFOGRAPHIC_SYSTEM_PROMPT

**Feature**: FEAT-301 — Themed Component Catalog — HTML Renderer v2
**Spec**: `sdd/specs/infographic-theme-catalog-a2ui.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2263
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec (§3). `INFOGRAPHIC_SYSTEM_PROMPT` is the
instruction block handed to the LLM when it must emit an `InfographicResponse`.
It documents **12** block types. Three that have shipped for months
(`accordion`, `checklist`, `tab_view`) are undocumented, so the model never
emits them — a silent capability gap, not a bug. TASK-2263 adds four more.

Without this task the four new block types exist in the models and render in
HTML but are effectively unreachable through the LLM path, which is how the
infographic pipeline is normally driven.

This is a prompt-text task. No logic changes.

---

## Scope

- Add the 3 missing existing block types to the prompt's block list:
  `accordion`, `checklist`, `tab_view`.
- Add the 4 new block types: `chain`, `steps`, `code`, `card_grid`, each with
  its required and optional fields.
- Document the `I18nText` convention: any text field accepts either a plain
  string or a `{"en": "...", "es": "..."}` object.
- Document the top-level `document_meta` object (`version`, `status`, `author`,
  `changelog[]`).
- Document the micro-syntax markers `[[chip:…]]`, `[[m:METHOD]]`,
  `[[comp:Name]]` as available inside prose text fields.
- Add a `Rules:` entry noting that `code` block content is rendered verbatim and
  must not contain markdown fences.
- Write tests asserting prompt coverage.

**NOT in scope**:
- Model definitions → TASK-2263.
- Renderer work → TASK-2252 / 2253 / 2254.
- `extract_infographic_data()` — do not touch it.
- Rewriting or restructuring the existing 12 entries. **Additive edits only** —
  the existing wording (especially the `hero_card` anti-pattern warning) is
  there because LLMs got it wrong; leave it intact.
- Prompt-engineering experiments, few-shot examples, or reordering. Match the
  established terse one-line-per-block style.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py` | MODIFY | Extend `INFOGRAPHIC_SYSTEM_PROMPT` (lines 16-46) |
| `tests/test_infographic_html.py` | MODIFY | Prompt-coverage tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-19.

### Verified Imports

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py — full import block
from typing import Any, Tuple, Optional
import orjson
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode
from ...models.infographic import InfographicResponse
```

No new imports needed.

### Existing Signatures to Use

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py
# INFOGRAPHIC_SYSTEM_PROMPT, lines 16-46 — VERBATIM current content:

INFOGRAPHIC_SYSTEM_PROMPT = """INFOGRAPHIC STRUCTURED OUTPUT MODE - CRITICAL INSTRUCTIONS:

You MUST respond with a valid JSON object matching the InfographicResponse schema.
The response contains an ordered list of typed "blocks" that form the infographic.

Available block types:
- title: Main heading with subtitle, author, date
- hero_card: Key metric card with value, label, trend, icon
- summary: Rich text paragraph (supports markdown)
- chart: Data visualization spec with chart_type, labels, series
- bullet_list: Ordered/unordered list of items
- table: Tabular data with columns and rows
- image: Image reference with URL/base64 and alt text
- quote: Highlighted quote with attribution
- callout: Alert/info/warning/success box
- divider: Visual separator
- timeline: Chronological sequence of events
- progress: Completion/progress indicators

Rules:
- Every block MUST include a "type" field
- hero_card blocks REQUIRE flat "label" and "value" string fields at the top
  level. Do NOT nest them inside "callout", "card", "data" or "items".
  Example:
    {"type": "hero_card", "label": "Total Revenue", "value": "$1.2M",
     "icon": "money", "trend": "up", "trend_value": "+12.5%"}
- Use callout (not hero_card) for alerts/warnings/info boxes
- chart blocks: include labels array and series with name+values
- All text fields support markdown formatting
- Output ONLY valid JSON, no explanatory text before or after
"""

def extract_infographic_data(response: Any) -> dict:    # line 49 — DO NOT MODIFY
```

The 12 documented types are: `title`, `hero_card`, `summary`, `chart`,
`bullet_list`, `table`, `image`, `quote`, `callout`, `divider`, `timeline`,
`progress`. The 7 to add: `accordion`, `checklist`, `tab_view` (existing but
undocumented) + `chain`, `steps`, `code`, `card_grid` (new in TASK-2263).

```python
# from TASK-2263 — field names to document (re-read the models to confirm)
ChainBlock:     nodes[{label}], direction: "horizontal" | "vertical"
StepsBlock:     steps[{label, description}], style: "numbered" | "icon"
CodeBlock:      code, language, highlight_lines[int]
CardGridBlock:  cards[{title, body}], columns: 1-6
DocumentMeta:   version, status, author, changelog[{version, date, summary}]
# existing, undocumented:
AccordionBlock: items[{title, content_blocks[]}]
ChecklistBlock: items[{text, checked}], style
TabViewBlock:   tabs[{label, blocks[]}]
```

### Does NOT Exist

- ~~a separate prompt file or prompt-template directory~~ — the prompt is this
  one module-level string constant
- ~~a second copy of the block list anywhere~~ — verify with
  `grep -rn "Available block types" packages/` before assuming; only this one
  must change
- ~~a prompt-versioning or prompt-registry mechanism~~ — none; edit in place
- ~~`INFOGRAPHIC_SYSTEM_PROMPT` being consumed with `.format()`~~ — it is used as
  a plain string, but it **does contain literal `{` `}`** in the hero_card
  example. Do not introduce f-string interpolation or `.format()` on it.
- ~~existing tests asserting the exact prompt text~~ — confirm with
  `grep -rn "INFOGRAPHIC_SYSTEM_PROMPT" tests/ packages/*/tests/` and update any
  that appear

---

## Implementation Notes

### Style to match

One line per block, `- name: short description with field names`. Terse. The
existing entries are the template:

```
- accordion: Collapsible sections; items[] each with title and content_blocks[]
- checklist: Task list; items[] each with text and checked (bool)
- tab_view: Tabbed container; tabs[] each with label and blocks[]
- chain: Flow/chain diagram; nodes[] each with label; direction "horizontal"|"vertical"
- steps: Step-by-step guide; steps[] each with label and optional description;
  style "numbered"|"icon"
- code: Code snippet; code (verbatim string), optional language, highlight_lines[]
- card_grid: Grid of cards; cards[] each with title and body; columns 1-6
```

### New conventions to document

Add these as `Rules:` entries or a short section after the block list — keep it
compact, this prompt is prepended to every request and every token costs:

```
Bilingual text (optional):
- Any text field accepts a plain string OR an object of locale->text,
  e.g. {"en": "Overview", "es": "Resumen"}. Use the object form only when
  bilingual output is requested.

Document metadata (optional):
- Top-level "document_meta": {"version": "1.2", "status": "approved",
  "author": "Name", "changelog": [{"version": "1.2", "date": "2026-08-19",
  "summary": "What changed"}]}

Inline markers (optional, inside prose text fields):
- [[chip:Label]] renders a small pill; [[m:GET]] renders an HTTP method badge;
  [[comp:ClassName]] renders a component reference.
```

And one rule for code blocks:

```
- code blocks: put raw source in "code" with NO markdown fences (no ```)
```

### Key Constraints

- **Additive only.** Do not reword or reorder the existing 12 entries or the
  existing `Rules:`. The `hero_card` warning in particular is load-bearing.
- Keep the prompt's leading line and overall structure identical so any
  downstream string matching keeps working.
- Watch the literal braces — the prompt embeds JSON examples with `{` and `}`;
  it is a plain `"""..."""` string, not an f-string. Keep it that way.
- Do not add few-shot examples beyond the compact JSON snippets shown above.
  Prompt length is a runtime cost on every infographic request.

### References in Codebase

- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py:16-46` —
  the prompt itself
- `packages/ai-parrot/src/parrot/models/infographic.py` — the authoritative field
  names; document what the models actually declare, not what this task summarises

---

## Acceptance Criteria

- [ ] The prompt names all 19 block types
- [ ] `accordion`, `checklist`, `tab_view` documented with their item fields
- [ ] `chain`, `steps`, `code`, `card_grid` documented with their fields and
      enum choices
- [ ] The `I18nText` locale-object convention is documented
- [ ] Top-level `document_meta` is documented, including `changelog[]`
- [ ] The three micro-syntax markers are documented
- [ ] A rule forbids markdown fences inside `code` block content
- [ ] The original 12 entries and the existing `Rules:` block are unchanged
      (diff shows additions only)
- [ ] The prompt is still a plain (non-f) string and still contains the
      `hero_card` example with literal braces
- [ ] `INFOGRAPHIC_SYSTEM_PROMPT` still imports cleanly:
      `from parrot.outputs.formats.infographic import INFOGRAPHIC_SYSTEM_PROMPT`
- [ ] Tests pass: `pytest tests/test_infographic_html.py tests/test_infographic_autodetect.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py`

---

## Test Specification

```python
# tests/test_infographic_html.py (extend)
from parrot.models.infographic import BlockType
from parrot.outputs.formats.infographic import INFOGRAPHIC_SYSTEM_PROMPT


class TestSystemPrompt:
    def test_system_prompt_19_blocks(self):
        """Every BlockType value is named in the prompt."""
        missing = [
            bt.value for bt in BlockType
            if bt.value not in INFOGRAPHIC_SYSTEM_PROMPT
        ]
        assert missing == [], f"undocumented block types: {missing}"

    def test_previously_missing_blocks_documented(self):
        for name in ("accordion", "checklist", "tab_view"):
            assert f"- {name}:" in INFOGRAPHIC_SYSTEM_PROMPT

    def test_new_blocks_documented(self):
        for name in ("chain", "steps", "code", "card_grid"):
            assert f"- {name}:" in INFOGRAPHIC_SYSTEM_PROMPT

    def test_system_prompt_i18n(self):
        assert '"es"' in INFOGRAPHIC_SYSTEM_PROMPT
        assert '"en"' in INFOGRAPHIC_SYSTEM_PROMPT

    def test_system_prompt_document_meta(self):
        assert "document_meta" in INFOGRAPHIC_SYSTEM_PROMPT
        assert "changelog" in INFOGRAPHIC_SYSTEM_PROMPT

    def test_system_prompt_microsyntax(self):
        for marker in ("[[chip:", "[[m:", "[[comp:"):
            assert marker in INFOGRAPHIC_SYSTEM_PROMPT

    def test_existing_hero_card_guidance_preserved(self):
        assert 'REQUIRE flat "label" and "value"' in INFOGRAPHIC_SYSTEM_PROMPT
        assert '{"type": "hero_card", "label": "Total Revenue"' in INFOGRAPHIC_SYSTEM_PROMPT

    def test_prompt_ends_with_json_only_rule(self):
        assert "Output ONLY valid JSON" in INFOGRAPHIC_SYSTEM_PROMPT
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2263 must be in `sdd/tasks/completed/`; the
   prompt must document the field names the models actually declare
3. **Verify the Codebase Contract** — before writing ANY text:
   - Re-read the 4 new models and the 3 undocumented ones; document their real
     fields, not this task's summary of them
   - `grep -rn "Available block types" packages/` to confirm there is only one
     copy of the block list
   - `grep -rn "INFOGRAPHIC_SYSTEM_PROMPT" tests/ packages/*/tests/` to find any
     test that pins the prompt text
4. **Update status** in `sdd/tasks/index/infographic-theme-catalog-a2ui.json` →
   `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met — including that `git diff` on the
   prompt shows **only additions**
7. **Move this file** to `sdd/tasks/completed/TASK-2256-system-prompt-19-blocks.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**Prompt token delta**: approximate added length

**Deviations from spec**: none | describe if any
