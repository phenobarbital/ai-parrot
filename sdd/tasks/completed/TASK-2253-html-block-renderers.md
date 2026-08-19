# TASK-2253: HTML Renderers for chain / steps / code / card_grid

**Feature**: FEAT-301 — Themed Component Catalog — HTML Renderer v2
**Spec**: `sdd/specs/infographic-theme-catalog-a2ui.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2263, TASK-2251, TASK-2252
**Assigned-to**: unassigned

---

## Context

Implements the block-renderer half of **Module 3** (spec §3) — the visible
payoff of FEAT-301. TASK-2263 defined the four models; without this task they
validate but render as nothing (`_render_single_block` has no renderer for
them). This task wires them into `_BLOCK_MODEL_MAP` and `_block_renderers` and
writes the four `_render_*` methods plus their CSS.

It depends on TASK-2252 because every title/label field on the new blocks is
`I18nText` — those must go through `_render_i18n_span()`, not `escape()`.

---

## Scope

- Add the 4 new block models to the `infographic_html.py` import block
  (lines 30-60): `ChainBlock`, `ChainNode`, `StepsBlock`, `StepItem`,
  `CodeBlock`, `CardGridBlock`, `GridCard`.
- Add 4 entries to `_BLOCK_MODEL_MAP` (lines 69-85).
- Add 4 entries to `self._block_renderers` (lines 675-691).
- Implement `_render_chain(self, block: ChainBlock) -> str` — connected node
  sequence, honouring `direction` (`horizontal` | `vertical`).
- Implement `_render_steps(self, block: StepsBlock) -> str` — ordered stages,
  honouring `style` (`numbered` | `icon`).
- Implement `_render_code(self, block: CodeBlock) -> str` — `<pre><code>` with
  a `language-{lang}` class and `highlight_lines` marking.
- Implement `_render_card_grid(self, block: CardGridBlock) -> str` — CSS grid
  with `columns` columns.
- Add the CSS for these four blocks to `BASE_CSS`, using theme tokens
  (`var(--code-bg)`, `var(--code-text)`, `var(--surface-bg)`, etc.).
- Write unit + integration tests, including a full 19-block render.

**NOT in scope**:
- `_render_i18n_span` / `_expand_microsyntax` / `setLang` → TASK-2252 (consume them).
- Document chrome → TASK-2254.
- Migrating the ~21 pre-existing literal colors in `BASE_CSS` → TASK-2255.
  New rules added here must use `var()` from the start, but do not refactor
  existing rules.
- Real syntax highlighting. `CodePalette` gives token colors, but tokenizing
  source code is **out of scope** — emit the code verbatim in a themed
  `<pre>` and expose the palette as CSS variables so a future task (or a
  client-side highlighter) can use them. Do not add a highlighter dependency.
- The A2UI adapter → TASK-2257. The system prompt → TASK-2256.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` | MODIFY | Imports, `_BLOCK_MODEL_MAP`, `_block_renderers`, 4 `_render_*` methods, `BASE_CSS` rules |
| `tests/test_infographic_html.py` | MODIFY | Unit tests per renderer + all-19-blocks integration test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-19.

### Verified Imports

```python
# already present at packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
from markupsafe import escape             # line 17
from pydantic import ValidationError      # line 18
from ...models.infographic import (       # lines 30-60 — ADD the new models to THIS block
    BlockType, BulletListBlock, BulletListStyle, CalloutBlock, CalloutLevel,
    ChartBlock, ChartDataSeries, ChartType, ColumnDef, DividerBlock,
    HeroCardBlock, ImageBlock, InfographicResponse, ProgressBlock,
    QuoteBlock, SummaryBlock, TableBlock, TableStyle, TimelineBlock,
    TitleBlock, TrendDirection, ThemeConfig, theme_registry,
    AccordionBlock, AccordionItem, ChecklistBlock, ChecklistItem,
    TabViewBlock, TabPane,
)
```

Import the new models from `...models.infographic` (the relative path this file
already uses), **not** from `parrot.models` — and note that `AccordionBlock`
etc. are imported here precisely because `parrot.models.__init__` did not
re-export them.

### Existing Signatures to Use

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py

_BLOCK_MODEL_MAP: Dict[str, Any] = {       # lines 69-85 — 15 entries; add 4
    "title": TitleBlock,
    "hero_card": HeroCardBlock,
    "summary": SummaryBlock,
    "chart": ChartBlock,
    "bullet_list": BulletListBlock,
    "table": TableBlock,
    "image": ImageBlock,
    "quote": QuoteBlock,
    "callout": CalloutBlock,
    "divider": DividerBlock,
    "timeline": TimelineBlock,
    "progress": ProgressBlock,
    "checklist": ChecklistBlock,
    "accordion": AccordionBlock,
    "tab_view": TabViewBlock,
}

BASE_CSS = """\                            # line 153, closes ~line 617
class InfographicHTMLRenderer(BaseRenderer):   # line 656
    self._block_renderers: Dict[str, Any] = {  # lines 675-691 — 15 entries; add 4
        "title": self._render_title,
        ...
        "tab_view": self._render_tab_view,
    }

    def _render_blocks(self, data: InfographicResponse) -> str:  # line 823
        # groups consecutive hero_card blocks into a .kpi-grid, otherwise
        # delegates to _render_single_block(block, depth=0)
    def _render_single_block(self, block, depth=0, max_depth=3) -> str:  # ~line 852
        # Nested blocks inside a TabPane / AccordionItem arrive as raw DICTS
        # (those containers type children as List[Any]); this method coerces
        # them through _BLOCK_MODEL_MAP — which is why the 4 new entries are
        # required for the new blocks to work when nested.
```

Renderer style to copy verbatim (BEM-ish classes, parts list, escape everything):

```python
    def _render_checklist(self, block: ChecklistBlock) -> str:
        """Render ChecklistBlock as a visual checkbox list.

        Args:
            block: ChecklistBlock with items and optional style/title.

        Returns:
            HTML string with checkbox visuals and optional descriptions.
        """
        style_cls = ""
        if block.style and block.style != "default":
            style_cls = f" checklist--{escape(block.style)}"
        parts = [f'        <div class="checklist{style_cls}">']
        if block.title:
            parts.append(
                f'          <div class="checklist__title">{escape(block.title)}</div>'
            )
        parts.append('          <div class="checklist__items">')
        for item in block.items:
            checked_cls = " checklist__item--checked" if item.checked else ""
            check_mark = "&#10003;" if item.checked else ""
            ...
```

```python
# from TASK-2252 — use these instead of escape() for any I18nText field
def _render_i18n_span(self, text: Any) -> str: ...   # I18nText -> safe HTML
def _i18n_plain(self, text: Any) -> str: ...         # I18nText -> plain string
def _expand_microsyntax(self, html: str) -> str: ... # [[chip:]] / [[m:]] / [[comp:]]
```

```python
# from TASK-2263 — the model fields these renderers read
ChainBlock:     type, title: Optional[I18nText], nodes: List[ChainNode],
                direction: Literal["horizontal", "vertical"] = "horizontal"
StepsBlock:     type, title, steps: List[StepItem],
                style: Literal["numbered", "icon"] = "numbered"
CodeBlock:      type, title, code: str, language: Optional[str],
                highlight_lines: Optional[List[int]]
CardGridBlock:  type, title, cards: List[GridCard], columns: int (ge=1, le=6)
```

```python
# from TASK-2251 — CSS variables available (only when the theme sets them)
# --code-bg, --code-text, --code-keyword, --code-string, --code-comment,
# --code-number, --code-function, --surface-bg, --soft-primary
```

### Does NOT Exist

- ~~`InfographicHTMLRenderer._render_chain()` / `._render_steps()` /
  `._render_code()` / `._render_card_grid()`~~ — create all four
- ~~`_BLOCK_MODEL_MAP["chain"]` / `["steps"]` / `["code"]` / `["card_grid"]`~~ — add them
- ~~`self._block_renderers["chain"]` (etc.)~~ — add them
- ~~any `.chain` / `.steps` / `.code-block` / `.card-grid` CSS in `BASE_CSS`~~ — none exist
- ~~a syntax highlighter (pygments, highlight.js) anywhere in this package~~ —
  not a dependency, do not add one
- ~~`self._md` rendering raw HTML~~ — `markdown_it.MarkdownIt()` at line 669 has
  `html=False`
- ~~a `_render_code_lines()` or line-numbering helper~~ — does not exist
- ~~`GridCard.image` / `.badge` / `.footer`~~ — only whatever TASK-2263 actually
  defined; re-read the model before rendering fields

---

## Implementation Notes

### Method shape

All four follow the established signature and return a single HTML string with
the file's existing 8-space base indentation:

```python
    def _render_code(self, block: CodeBlock) -> str:
        """Render CodeBlock as a themed <pre><code> snippet.

        Args:
            block: CodeBlock with code, optional language and highlight_lines.

        Returns:
            HTML string with a ``language-{lang}`` class and highlighted lines.
        """
```

### Per-block guidance

- **chain**: `.chain` wrapper + `.chain--vertical` modifier; one
  `.chain__node` per node with a `.chain__connector` between (not after the
  last). Use a CSS pseudo-element or a dedicated span for the arrow — do not
  emit a trailing connector.
- **steps**: `.steps` + `.steps--icon` modifier; each `.steps__item` carries a
  `.steps__marker` (the 1-based index for `numbered`, an icon glyph for `icon`)
  and a `.steps__body` with label + optional description.
- **code**: `<pre class="code-block"><code class="language-{lang}">`. Escape the
  code body — it is the highest-risk injection surface in this feature. Render
  `highlight_lines` by splitting on `\n` and wrapping the marked 1-based lines
  in `<span class="code-block__line--highlight">`; ignore out-of-range numbers
  rather than raising. Do **not** run micro-syntax expansion on code content —
  a literal `[[chip:x]]` in a snippet must stay literal.
- **card_grid**: `.card-grid` with
  `style="grid-template-columns: repeat({columns}, minmax(0, 1fr))"`. `columns`
  is already constrained `ge=1, le=6` by the model, but clamp defensively since
  raw dicts reach `_render_single_block` too.

### Key Constraints

- **`I18nText` fields must go through `_render_i18n_span()`** (TASK-2252), never
  `escape()` — `escape({"en": ...})` renders a stringified dict.
- Escape every user value. `block.language` lands in a class attribute — allow
  only `[\w+#.-]` and drop anything else rather than escaping it into the class.
- Micro-syntax expansion applies to prose (`StepItem.description`,
  `GridCard.body`) but **never** to `CodeBlock.code`.
- All new CSS colors via `var(--token, fallback)`; TASK-2255 will assert no bare
  literals outside `var()`.
- Registering in `_BLOCK_MODEL_MAP` is not optional — it is what makes the new
  blocks work when nested inside a `TabPane`/`AccordionItem`, where children
  arrive as raw dicts.
- Google-style docstrings on all four methods.

### References in Codebase

- `infographic_html.py` `_render_checklist` / `_render_timeline` /
  `_render_progress` — the closest structural analogues (list-of-items blocks)
- `infographic_html.py:823` `_render_blocks`, `~852` `_render_single_block` —
  the dispatch path
- `tests/test_infographic_html.py` — existing renderer test style

---

## Acceptance Criteria

- [ ] `_render_chain()` emits `.chain` markup; `direction="vertical"` adds the
      vertical modifier class; N nodes produce N-1 connectors
- [ ] `_render_steps()` emits `.steps` markup; `numbered` style shows 1-based
      indices; `style="icon"` adds the icon modifier class
- [ ] `_render_code()` emits `<pre>` + `<code class="language-python">`, escapes
      the body, and marks the lines listed in `highlight_lines`
- [ ] `_render_code()` ignores out-of-range `highlight_lines` without raising
- [ ] `_render_code()` leaves a literal `[[chip:x]]` inside the code unexpanded
- [ ] `_render_card_grid()` emits a grid with the requested column count
- [ ] Bilingual titles on all four blocks render via `_render_i18n_span()`
      (two `<span lang="…">`, not a stringified dict)
- [ ] A malicious payload (`code="<script>alert(1)</script>"`,
      `language='py" onload="x'`) produces no executable markup and no
      attribute break-out
- [ ] All 4 types present in `_BLOCK_MODEL_MAP` and `_block_renderers`
- [ ] The new blocks render correctly when nested inside a `tab_view` pane
      (raw-dict path through `_BLOCK_MODEL_MAP`)
- [ ] `render_to_html()` succeeds on a payload containing **all 19** block types
- [ ] `render_to_html(..., theme="petrol")` succeeds and emits the `--code-bg` token
- [ ] Existing 15-block payloads render identically to pre-change output
- [ ] Tests pass: `pytest tests/test_infographic_html.py tests/test_infographic_multi_tab.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py`

---

## Test Specification

```python
# tests/test_infographic_html.py (extend)
import pytest

from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


@pytest.fixture
def renderer():
    return InfographicHTMLRenderer()


@pytest.fixture
def all_blocks_payload():
    """InfographicResponse dict with all 19 block types (spec §4)."""
    return {
        "theme": "petrol",
        "blocks": [
            {"type": "title", "title": "Test Infographic"},
            {"type": "hero_card", "label": "Metric", "value": "42"},
            {"type": "summary", "content": "Summary text"},
            {"type": "chart", "chart_type": "bar", "labels": ["A"],
             "series": [{"name": "s", "values": [1]}]},
            {"type": "bullet_list", "items": ["item 1"]},
            {"type": "table", "columns": ["A"], "rows": [["1"]]},
            {"type": "image", "url": "data:image/png;base64,AA==", "alt": "img"},
            {"type": "quote", "text": "Quote", "author": "Author"},
            {"type": "callout", "level": "info", "content": "Info"},
            {"type": "divider"},
            {"type": "timeline", "events": [{"date": "2026-01-01", "title": "Event"}]},
            {"type": "progress", "items": [{"label": "Task", "value": "80%"}]},
            {"type": "accordion", "items": [{"title": "Section", "content_blocks": []}]},
            {"type": "checklist", "items": [{"text": "Done", "checked": True}]},
            {"type": "tab_view", "tabs": [{"label": "Tab1", "blocks": []}]},
            {"type": "chain", "nodes": [{"label": "A"}, {"label": "B"}]},
            {"type": "steps", "steps": [{"label": "Step 1", "description": "Do thing"}]},
            {"type": "code", "code": "print('hello')", "language": "python"},
            {"type": "card_grid", "cards": [{"title": "Card 1", "body": "Content"}],
             "columns": 2},
        ],
    }


class TestNewBlockRenderers:
    def test_render_chain_block(self, renderer):
        html = renderer._render_chain(_chain(nodes=[{"label": "A"}, {"label": "B"}]))
        assert 'class="chain' in html
        assert html.count("chain__node") == 2
        assert html.count("chain__connector") == 1

    def test_render_chain_vertical(self, renderer):
        html = renderer._render_chain(_chain(nodes=[{"label": "A"}], direction="vertical"))
        assert "chain--vertical" in html

    def test_render_steps_numbered(self, renderer):
        html = renderer._render_steps(_steps(steps=[{"label": "One"}, {"label": "Two"}]))
        assert ">1<" in html and ">2<" in html

    def test_render_code_block(self, renderer):
        html = renderer._render_code(_code(code="print('x')", language="python"))
        assert 'class="language-python"' in html
        assert "<pre" in html

    def test_render_code_escapes_body(self, renderer):
        html = renderer._render_code(_code(code="<script>alert(1)</script>"))
        assert "<script>" not in html

    def test_render_code_language_attribute_is_sanitised(self, renderer):
        html = renderer._render_code(_code(code="x", language='py" onload="boom'))
        assert "onload" not in html

    def test_render_code_ignores_out_of_range_highlights(self, renderer):
        html = renderer._render_code(_code(code="a\nb", highlight_lines=[1, 99]))
        assert html  # no exception

    def test_render_code_does_not_expand_microsyntax(self, renderer):
        html = renderer._render_code(_code(code="[[chip:x]]"))
        assert "[[chip:x]]" in html

    def test_render_card_grid_columns(self, renderer):
        html = renderer._render_card_grid(
            _card_grid(cards=[{"title": "C"}], columns=4)
        )
        assert "repeat(4" in html

    def test_bilingual_title_uses_i18n_span(self, renderer):
        html = renderer._render_code(_code(code="x", title={"en": "T", "es": "T-es"}))
        assert 'lang="en"' in html and 'lang="es"' in html


class TestAllBlocksIntegration:
    def test_render_all_19_block_types(self, renderer, all_blocks_payload):
        html = renderer.render_to_html(all_blocks_payload)
        assert html.startswith("<!DOCTYPE html>")
        for marker in ("chain", "steps", "code-block", "card-grid"):
            assert marker in html

    def test_render_petrol_theme(self, renderer, all_blocks_payload):
        html = renderer.render_to_html(all_blocks_payload, theme="petrol")
        assert "--code-bg" in html

    def test_new_block_nested_in_tab_pane(self, renderer):
        html = renderer.render_to_html({
            "blocks": [{
                "type": "tab_view",
                "tabs": [{"label": "T", "blocks": [
                    {"type": "code", "code": "x", "language": "python"},
                ]}],
            }],
        })
        assert "language-python" in html
```

> `_chain` / `_steps` / `_code` / `_card_grid` above are local helpers that
> build the corresponding model instance — define them with the real model
> constructors from `parrot.models.infographic` once TASK-2263 has landed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2263, TASK-2251, TASK-2252 must all be in
   `sdd/tasks/completed/`. You need the models, the theme tokens, and the
   i18n/micro-syntax helpers.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Re-read the 4 new models in `parrot/models/infographic.py` and render the
     fields they actually have — do NOT render fields from this task's summary
     if TASK-2263 named them differently
   - Re-grep line numbers; earlier tasks in this feature have already moved them
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists
4. **Update status** in `sdd/tasks/index/infographic-theme-catalog-a2ui.json` →
   `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2253-html-block-renderers.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-19
**Notes**: Added the 7 new model imports (`ChainBlock`, `ChainNode`,
`StepsBlock`, `StepItem`, `CodeBlock`, `CardGridBlock`, `GridCard`) to the
`...models.infographic` import block, 4 entries to `_BLOCK_MODEL_MAP`, and
4 entries to `self._block_renderers`. Implemented `_render_chain()`
(`.chain__node` + `.chain__connector` between nodes, `direction`-aware),
`_render_steps()` (`.steps__marker` numbered/icon), `_render_code()`
(`<pre class="code-block"><code class="language-{lang}">`, escaped body,
`highlight_lines` marking, out-of-range highlights ignored, micro-syntax
never expanded on code), `_render_card_grid()` (`.card-grid` with
`repeat({columns}, minmax(0, 1fr))`, defensively clamped 1-6). All four
titles/labels/descriptions route through `_render_i18n_span()` /
`_expand_microsyntax()` from TASK-2252, never raw `escape()`. Added CSS
for all four blocks to `BASE_CSS` using `var(--code-bg)`, `var(--surface-bg)`,
`var(--soft-primary)`, etc. Added unit tests for all four renderers
(bilingual titles, XSS payloads, out-of-range highlights, microsyntax
non-expansion in code, malicious `language` attribute) plus an
all-19-block-types integration fixture, petrol-theme render, nested-in-tab
rendering, and an existing-15-block regression test (117 tests in
`tests/test_infographic_html.py`, all passing; 43 in
`tests/test_infographic_multi_tab.py`, all passing).

`ruff check --select F`: F541 count unchanged (3, pre-existing in
`_render_accordion`, not touched by this task). F401 grew from 9 to 12 —
the 3 new "unused" imports (`ChainNode`, `StepItem`, `GridCard`) follow
the exact same pre-existing pattern as `AccordionItem`/`ChecklistItem`/
`TabPane` (support models imported for module contract clarity even
though only accessed via attribute, never as a bare name) and were
explicitly required by this task's Scope/Codebase Contract.

**Deviations from spec**: `<code>` carries only the bare
`language-{lang}` class (no combined `code-block__code` class), and the
outer wrapper uses `.code-block-wrapper` while `<pre>` itself carries
`.code-block` — this exact split was needed to satisfy the acceptance
criterion's literal `'class="language-python"'` string match. The
`language` sanitizer was changed from a character-stripping `re.sub` to a
whole-string `re.fullmatch` gate (invalid language hints are dropped
entirely rather than partially sanitized) after discovering that
character-stripping could leave attribute-breakout substrings like
`onload` intact inside an otherwise word-only remnant.
