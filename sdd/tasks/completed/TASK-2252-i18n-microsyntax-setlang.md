# TASK-2252: I18n Span Emitter, Micro-Syntax Expander & setLang() JS

**Feature**: FEAT-301 — Themed Component Catalog — HTML Renderer v2
**Spec**: `sdd/specs/infographic-theme-catalog-a2ui.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2263, TASK-2251
**Assigned-to**: unassigned

---

## Context

Implements the i18n + micro-syntax half of **Module 3** (spec §3). This task
comes *before* the four new block renderers (TASK-2253) on purpose: once
`I18nText` exists, every text field in the renderer can be a `str` **or** a
`{"en": ..., "es": ...}` dict, and the existing code path
`escape(block.title)` would stringify the dict into visible garbage like
`{&#39;en&#39;: &#39;Hello&#39;}`. The emitter built here is the helper that
TASK-2253 and TASK-2254 render every title through.

Two independent concerns, both text-level and both landing in
`infographic_html.py`:

1. **I18n**: turn an `I18nText` value into safe HTML — a bare escaped string
   for the `str` case, or one `<span lang="…">` per locale for the dict case,
   plus a `setLang()` JS switcher injected only when a bilingual value is
   actually present.
2. **Micro-syntax**: expand `[[chip:…]]`, `[[m:…]]`, `[[comp:…]]` markers into
   semantic inline fragments, applied **after** escaping so the expander only
   ever post-processes already-safe content (spec §7 "Escape policy").

---

## Scope

- Add `_render_i18n_span(self, text) -> str`: `I18nText` → safe HTML.
- Add `_i18n_plain(self, text) -> str`: `I18nText` → single plain string for
  attribute/`<title>` contexts where markup is illegal.
- Add `_expand_microsyntax(self, html: str) -> str` supporting:
  - `[[chip:Label]]` → `<span class="chip">Label</span>`
  - `[[m:GET]]` → `<span class="method-badge method-badge--get">GET</span>`
  - `[[comp:AgentCrew]]` → `<span class="component-ref">AgentCrew</span>`
- Add `_has_i18n(self, data) -> bool` to detect whether any bilingual value is
  present in the response (top-level and one level of nesting).
- Add `SETLANG_JS` module constant and inject it from `_build_interaction_js()`
  when `_has_i18n()` is true.
- Add the CSS for `.chip`, `.method-badge`, `.method-badge--*`,
  `.component-ref`, and `[lang]` visibility to `BASE_CSS`, using the v2 tokens
  `var(--soft-primary)` and `var(--badge-*)` from TASK-2251.
- Apply micro-syntax expansion to `SummaryBlock` content and the text fields of
  `TitleBlock` / `CalloutBlock` / `QuoteBlock`.
- Fix `render_to_html()`'s page-title extraction (line ~772,
  `page_title = str(escape(block.title))`) to go through `_i18n_plain()`.
- Write unit tests.

**NOT in scope**:
- The 4 new block renderers (`_render_chain` / `_steps` / `_code` /
  `_card_grid`) → TASK-2253.
- Document chrome (version bar, changelog, footer) → TASK-2254.
- Migrating the ~21 pre-existing literal colors in `BASE_CSS` → TASK-2255.
  This task *adds* new rules that use `var()` from the start; it does not
  refactor existing ones.
- Model changes → TASK-2263. Theme token changes → TASK-2251.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` | MODIFY | `_render_i18n_span`, `_i18n_plain`, `_expand_microsyntax`, `_has_i18n`, `SETLANG_JS`, new `BASE_CSS` rules, page-title fix |
| `tests/test_infographic_html.py` | MODIFY | i18n + micro-syntax tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-19.

### Verified Imports

```python
# already present at packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
import markdown_it                       # line 15
import orjson                            # line 16
from markupsafe import escape            # line 17
from pydantic import ValidationError      # line 18
from .base import BaseRenderer            # line 27
from . import register_renderer           # line 28
from ...models.outputs import OutputMode  # line 29
from ...models.infographic import (       # lines 30-60
    BlockType, BulletListBlock, BulletListStyle, CalloutBlock, CalloutLevel,
    ChartBlock, ChartDataSeries, ChartType, ColumnDef, DividerBlock,
    HeroCardBlock, ImageBlock, InfographicResponse, ProgressBlock,
    QuoteBlock, SummaryBlock, TableBlock, TableStyle, TimelineBlock,
    TitleBlock, TrendDirection, ThemeConfig, theme_registry,
    AccordionBlock, AccordionItem, ChecklistBlock, ChecklistItem,
    TabViewBlock, TabPane,
)
```

`escape` is `markupsafe.escape` and returns a `Markup` object, **not** a `str` —
existing code wraps it in `str(...)` where a plain string is required (see
line ~772 and `_render_title`). Keep that habit.

### Existing Signatures to Use

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py

BASE_CSS = """\                                      # line 153, closes ~line 617
TAB_JS = """                                         # line 624
ACCORDION_JS = """                                   # line 639

@register_renderer(OutputMode.INFOGRAPHIC)           # line 655
class InfographicHTMLRenderer(BaseRenderer):         # line 656
    self._md = markdown_it.MarkdownIt()              # line 669 — html=False (safe)
    self._tab_view_counter: int = 0                  # line 670
    self._theme_cfg: Optional[ThemeConfig] = None    # line 674
    self._block_renderers: Dict[str, Any] = {...}    # lines 675-691 (15 entries)

    def render_to_html(self, data, theme=None) -> str:            # line 724
        ...
        self._tab_view_counter = 0                                # reset per render
        theme_cfg = theme_registry.get(theme_name)                # falls back to "light"
        self._theme_cfg = theme_cfg
        blocks_html = self._render_blocks(data)
        page_title = "Infographic"
        for block in data.blocks:
            if getattr(block, "type", None) == "title":
                page_title = str(escape(block.title))             # ~line 772 — MUST become _i18n_plain
                break
        echarts_script = self._get_echarts_script() if has_charts else ""
        interaction_js = self._build_interaction_js(data)
        return self._assemble_document(
            page_title=page_title,
            theme_css=theme_cfg.to_css_variables(),
            blocks_html=blocks_html,
            echarts_script=echarts_script + interaction_js,       # NOTE: JS rides in on this param
        )

    def _assemble_document(self, page_title, theme_css, blocks_html, echarts_script="") -> str:  # line 794
        # emits <html lang="en"> … <style>{theme_css}\n{BASE_CSS}</style>{echarts_script}</head>

    def _render_blocks(self, data: InfographicResponse) -> str:   # line 823
    def _render_single_block(self, block, depth=0, max_depth=3) -> str:  # ~line 852
    def _build_interaction_js(self, data: InfographicResponse) -> str:   # line 905
        # scans data.blocks for tab_view / accordion (incl. accordions nested in
        # tab panes) and concatenates TAB_JS / ACCORDION_JS. Extend this method.
    def _render_title(self, block: TitleBlock) -> str:            # ~line 940
    def _render_summary(self, block: SummaryBlock) -> str:        # uses self._md.render(block.content) ~line 994
```

Existing renderer style — BEM-ish class names, list-of-parts assembly, every
user value through `escape()`:

```python
    def _render_checklist(self, block: ChecklistBlock) -> str:
        style_cls = ""
        if block.style and block.style != "default":
            style_cls = f" checklist--{escape(block.style)}"
        parts = [f'        <div class="checklist{style_cls}">']
        if block.title:
            parts.append(
                f'          <div class="checklist__title">{escape(block.title)}</div>'
            )
        ...
```

```python
# from TASK-2251 — the CSS variables this task's new rules consume
# --soft-primary, --badge-get, --badge-post, --badge-put, --badge-delete, --badge-patch
# Emitted by ThemeConfig.to_css_variables() ONLY when the theme sets them.
```

### Does NOT Exist

- ~~`InfographicHTMLRenderer._render_i18n_span()`~~ — create it
- ~~`InfographicHTMLRenderer._i18n_plain()`~~ — create it
- ~~`InfographicHTMLRenderer._expand_microsyntax()`~~ — create it
- ~~`InfographicHTMLRenderer._has_i18n()`~~ — create it
- ~~`SETLANG_JS`~~ — module constant does not exist; `TAB_JS` (624) and
  `ACCORDION_JS` (639) are the only JS constants
- ~~a `.chip` / `.method-badge` / `.component-ref` CSS class in `BASE_CSS`~~ — none exist
- ~~any existing `[[...]]` marker handling~~ — no micro-syntax support anywhere
  in the renderer today
- ~~`self._md` having `html=True`~~ — it is `markdown_it.MarkdownIt()` with
  `html=False`, so raw HTML in markdown source is escaped, not passed through.
  Micro-syntax expansion must therefore run **after** `self._md.render(...)`.
- ~~a `lang` switcher or any `[lang]` CSS rule~~ — the document is hardcoded
  `<html lang="en">` in `_assemble_document` (line ~803)
- ~~`InfographicResponse.default_locale` or a locale parameter on
  `render_to_html()`~~ — no such field/arg; the default visible locale is a
  client-side concern, decided by the CSS/JS this task adds

---

## Implementation Notes

### `_render_i18n_span()`

```python
def _render_i18n_span(self, text: Any) -> str:
    """Render an ``I18nText`` value as escaped, locale-aware HTML.

    Args:
        text: A plain ``str``, or a ``{locale: text}`` mapping.

    Returns:
        The escaped string for the ``str`` case, or one
        ``<span lang="xx" class="i18n">…</span>`` per locale, in insertion
        order, for the mapping case. ``None`` yields an empty string.
    """
```

- `str` in → `str(escape(text))` out. **No wrapper span** — this keeps every
  existing single-language render byte-identical, which is what the spec's
  "existing payloads render identically" criterion needs.
- `dict` in → one span per key, ordered as the dict is ordered (Python 3.7+
  preserves insertion order, so `{"en": ..., "es": ...}` stays EN-first).
- Escape the locale key too — it lands in an attribute.
- Mark the first locale with an extra class (e.g. `i18n--default`) so the CSS
  can show it before any JS runs.

### `_i18n_plain()`

For `<title>` and attribute contexts where a span is illegal. `str` → escaped
string; `dict` → the first value (or the `"en"` value if present), escaped.

### `_expand_microsyntax()`

Runs on **already-escaped** HTML, so the markers survive escaping unchanged
(`[`, `]`, `:` are not escaped by `markupsafe`). Use one compiled
module-level regex per marker, and validate the captured payload:

```python
_MICRO_CHIP_RE = re.compile(r"\[\[chip:([^\]\[]{1,64})\]\]")
_MICRO_METHOD_RE = re.compile(r"\[\[m:(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\]\]", re.I)
_MICRO_COMP_RE = re.compile(r"\[\[comp:([\w.\-]{1,64})\]\]")
```

- The captured group is already escaped — do **not** escape it again (double
  escaping turns `&amp;` into `&amp;amp;`).
- Unknown/malformed markers are left verbatim rather than stripped, so a
  typo is visible instead of silently swallowing content.
- Only these three markers; do not invent more.
- For `[[m:get]]`, normalise the class to lowercase (`method-badge--get`) and
  the visible label to uppercase (`GET`).

### `SETLANG_JS`

Follow `TAB_JS` / `ACCORDION_JS` (lines 624, 639): a `"""<script>…</script>"""`
string, no external dependencies, no framework. `setLang(code)` should hide
every `.i18n[lang]` whose `lang` differs from `code` and show the matching
ones. Inject it from `_build_interaction_js()` — extend the existing
`has_tabs` / `has_accordion` scan with a `_has_i18n(data)` check; keep the
concatenation order stable (`TAB_JS`, `ACCORDION_JS`, then `SETLANG_JS`) so
existing golden output for tab/accordion documents does not move.

### New `BASE_CSS` rules

Append near the end of `BASE_CSS` (before the `@media print` block at ~line 484
so print overrides still win). Use `var()` with a literal fallback so a v1
theme that sets no v2 tokens still renders sanely:

```css
.chip { background: var(--soft-primary, rgba(99,102,241,0.12)); ... }
.method-badge--get { background: var(--badge-get, #10b981); }
.i18n { display: none; }
.i18n--default { display: inline; }
```

Note the fallback literals live **inside** `var(…, fallback)`, which is the
form TASK-2255's "no literal colors outside `var()`" check accepts — do not
write bare literals.

### Key Constraints

- **Backward compatibility**: a response with no bilingual values and no
  `[[…]]` markers must render byte-identically to today. Guard the JS injection
  behind `_has_i18n()` and keep `_render_i18n_span()` span-free for `str`.
- Escape-then-expand ordering is mandatory (spec §7). Never expand before escape.
- Do not touch the 15 existing `_block_renderers` entries or their signatures;
  only route their text through the new helpers.
- Google-style docstrings; `self.logger` (or the module `logger` used at line
  ~757) for warnings — no `print`.

### References in Codebase

- `infographic_html.py:624` (`TAB_JS`) and `:639` (`ACCORDION_JS`) — JS constant style
- `infographic_html.py:905` (`_build_interaction_js`) — conditional-injection pattern to extend
- `infographic_html.py` `_render_checklist` — renderer/escape style
- `tests/test_infographic_html.py` — existing renderer test style (842 lines)

---

## Acceptance Criteria

- [ ] `_render_i18n_span("Hello")` returns `"Hello"` with no span wrapper
- [ ] `_render_i18n_span({"en": "Hello", "es": "Hola"})` emits two
      `<span lang="…">` elements, EN first, both escaped
- [ ] `_render_i18n_span(None)` returns `""`
- [ ] `_render_i18n_span({"en": "<script>"})` escapes the payload
- [ ] `_i18n_plain({"en": "Hello", "es": "Hola"})` returns `"Hello"` with no markup
- [ ] `[[chip:Active]]` expands to a `.chip` span
- [ ] `[[m:GET]]` expands to `.method-badge--get` with visible text `GET`;
      `[[m:get]]` produces the same class
- [ ] `[[comp:AgentCrew]]` expands to a `.component-ref` span
- [ ] A malformed marker (`[[chip:]]`, `[[bogus:x]]`) is left verbatim
- [ ] Micro-syntax does not double-escape: `[[chip:A &amp; B]]` renders
      `A &amp; B` (one level of escaping)
- [ ] `setLang()` JS is present in the output when a bilingual value exists,
      and absent when none does
- [ ] `render_to_html()` `<title>` is a plain string even when the title block
      carries a bilingual title
- [ ] `.chip` / `.method-badge` / `.component-ref` / `.i18n` rules present in
      `BASE_CSS`, all colors via `var(--token, fallback)`
- [ ] An existing single-language payload renders byte-identically to
      pre-change output (regression)
- [ ] Tests pass: `pytest tests/test_infographic_html.py -v`
- [ ] Tests pass: `pytest tests/test_infographic_multi_tab.py tests/test_infographic_autodetect.py -v`
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


class TestI18nEmitter:
    def test_plain_str_has_no_span(self, renderer):
        assert renderer._render_i18n_span("Hello") == "Hello"

    def test_dict_emits_dual_spans(self, renderer):
        html = renderer._render_i18n_span({"en": "Hello", "es": "Hola"})
        assert html.index('lang="en"') < html.index('lang="es"')
        assert "Hello" in html and "Hola" in html

    def test_none_is_empty(self, renderer):
        assert renderer._render_i18n_span(None) == ""

    def test_dict_values_escaped(self, renderer):
        html = renderer._render_i18n_span({"en": "<script>x</script>"})
        assert "<script>" not in html

    def test_i18n_plain_prefers_en(self, renderer):
        assert renderer._i18n_plain({"es": "Hola", "en": "Hello"}) == "Hello"


class TestMicroSyntax:
    def test_chip(self, renderer):
        assert 'class="chip"' in renderer._expand_microsyntax("[[chip:Active]]")

    def test_method_badge_case_insensitive(self, renderer):
        for marker in ("[[m:GET]]", "[[m:get]]"):
            out = renderer._expand_microsyntax(marker)
            assert "method-badge--get" in out
            assert ">GET<" in out

    def test_component_ref(self, renderer):
        out = renderer._expand_microsyntax("[[comp:AgentCrew]]")
        assert 'class="component-ref"' in out and "AgentCrew" in out

    def test_malformed_left_verbatim(self, renderer):
        for marker in ("[[chip:]]", "[[bogus:x]]"):
            assert marker in renderer._expand_microsyntax(marker)

    def test_no_double_escaping(self, renderer):
        out = renderer._expand_microsyntax("[[chip:A &amp; B]]")
        assert "&amp;amp;" not in out


class TestSetLangInjection:
    def test_js_present_when_bilingual(self, renderer):
        html = renderer.render_to_html({
            "blocks": [{"type": "title", "title": {"en": "Hi", "es": "Hola"}}],
        })
        assert "setLang" in html
        assert "<title>Hi</title>" in html

    def test_js_absent_when_monolingual(self, renderer):
        html = renderer.render_to_html({
            "blocks": [{"type": "title", "title": "Hi"}],
        })
        assert "setLang" not in html
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2263 and TASK-2251 must be in
   `sdd/tasks/completed/`. You need `I18nText` (2250) and the
   `--soft-primary` / `--badge-*` tokens (2251).
3. **Verify the Codebase Contract** — before writing ANY code:
   - Re-grep the line numbers; this file is ~1600 lines and every task in this
     feature edits it, so offsets drift
   - Confirm `escape`, `TAB_JS`, `ACCORDION_JS`, `_build_interaction_js` still
     look as listed
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists
4. **Capture a byte-for-byte baseline first**: render a monolingual fixture
   before your changes and diff after — the regression criterion depends on it
5. **Update status** in `sdd/tasks/index/infographic-theme-catalog-a2ui.json` →
   `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2252-i18n-microsyntax-setlang.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-19
**Notes**: Added `_render_i18n_span`, `_i18n_plain`, `_expand_microsyntax`,
`_has_i18n` to `InfographicHTMLRenderer`, plus module-level `SETLANG_JS`
and the `_MICRO_CHIP_RE`/`_MICRO_METHOD_RE`/`_MICRO_COMP_RE` regexes.
`_build_interaction_js()` now injects `SETLANG_JS` when `_has_i18n(data)`
is true (after `TAB_JS`/`ACCORDION_JS`, preserving existing concatenation
order). Fixed `render_to_html()`'s page-title extraction to go through
`_i18n_plain()`. Added `.chip`/`.method-badge*`/`.component-ref`/`.i18n`
CSS rules to `BASE_CSS`, all colors via `var(--token, fallback)`. Wired
micro-syntax expansion into `_render_title`, `_render_summary`,
`_render_quote`, `_render_callout`. Added the full i18n/micro-syntax test
suite to `tests/test_infographic_html.py` (100 tests total, all
passing). `ruff check --select F` clean (pre-existing F541/F401 findings
unchanged, verified against the pre-task baseline). `tests/
test_infographic_multi_tab.py` passes; `tests/test_infographic_autodetect.py`
has one PRE-EXISTING unrelated failure (`test_all_templates_listed`
expects 7 templates, finds 9 — caused by templates added by other,
unrelated features already merged to `dev`; verified unrelated to this
task's files and unaffected by these changes).

**Deviations from spec**: `TitleBlock.title` remains `str` (TASK-2263
scope, per its explicit Files-to-Modify list which excludes this task
from touching `models/infographic.py`). The task's own test spec
(`test_js_present_when_bilingual`) used a `"title"`-type block with a
dict `title`, which cannot validate against the current model. Adapted
that test to use `CodeBlock.title` (a model surface that genuinely
supports `I18nText` since TASK-2263) to exercise `_has_i18n()` +
`setLang()` injection end-to-end, while keeping `render_to_html()`'s
page-title fix (`_i18n_plain()`) forward-compatible and
backward-compatible for the current `str`-only `TitleBlock.title`.
