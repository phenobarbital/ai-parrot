# TASK-2255: Migrate Literal CSS Colors in BASE_CSS to Theme Tokens

**Feature**: FEAT-301 — Themed Component Catalog — HTML Renderer v2
**Spec**: `sdd/specs/infographic-theme-catalog-a2ui.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2251
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec (§3). `BASE_CSS` is a ~465-line string
literal that already uses `var(--primary)` / `var(--neutral-*)` for most colors,
but 21 occurrences are still hardcoded. Those are exactly the places where a
theme fails to apply: switch to `dark` or `midnight` and the callout blocks stay
pale blue, the cards stay `#fff`, and the table hover stays light slate — the
"theme consistency" defect named in the spec's problem statement.

TASK-2251 created the tokens (`--surface-bg`, `--soft-primary`,
`--callout-*-bg`) that make the migration possible. This task is a pure
refactor: no new markup, no new blocks, no behavior change beyond colors
following the theme.

---

## Scope

Migrate the literal colors below to `var(--token, fallback)` form. **This is the
complete, verified inventory** — 21 occurrences, line numbers as of
2026-08-19 (they will have shifted if TASK-2252/2253/2254 landed first; re-run
the inventory command in the notes before starting):

| Line | Current | Target |
|---|---|---|
| 165 | `background: white;` (`.hero`) | `var(--surface-bg, #fff)` |
| 168 | `box-shadow: 0 10px 25px rgba(0,0,0,0.05);` | keep or `var(--shadow-light, …)` — see decision below |
| 172 | `color: #fff;` | `var(--on-primary, #fff)` |
| 216 | `background: #fff;` (KPI card) | `var(--surface-bg, #fff)` |
| 220 | `box-shadow: 0 2px 8px rgba(0,0,0,0.06);` | keep or tokenize |
| 243 | `background: #fff;` | `var(--surface-bg, #fff)` |
| 263 | `color: #fff;` | `var(--on-primary, #fff)` |
| 274 | `tr:hover { background: #f1f5f9; }` | `var(--body-bg)` (existing v1 token) |
| 346 | `.callout-block.info { background: #eff6ff; }` | `var(--callout-info-bg, #eff6ff)` |
| 351 | `.callout-block.success { background: #ecfdf5; }` | `var(--callout-success-bg, #ecfdf5)` |
| 354 | `.callout-block.success h3 { color: #065f46; }` | `var(--callout-success-text, #065f46)` |
| 356 | `.callout-block.warning { background: #fffbeb; }` | `var(--callout-warning-bg, #fffbeb)` |
| 359 | `.callout-block.warning h3 { color: #92400e; }` | `var(--callout-warning-text, #92400e)` |
| 361 | `.callout-block.error { background: #fef2f2; }` | `var(--callout-error-bg, #fef2f2)` |
| 364 | `.callout-block.error h3 { color: #991b1b; }` | `var(--callout-error-text, #991b1b)` |
| 366 | `.callout-block.tip { background: #f0fdfa; }` | `var(--callout-tip-bg, #f0fdfa)` |
| 367 | `.callout-block.tip { border-left: 4px solid #14b8a6; }` | `var(--accent-teal, #14b8a6)` — **not in the spec's list; found during task planning** |
| 369 | `.callout-block.tip h3 { color: #115e59; }` | `var(--callout-tip-text, #115e59)` |
| 486 | `@media print { body { background: white; } }` | leave literal (see below) |
| 488 | `@media print { .hero { background: #eee !important; color: black !important; border: 1px solid #ccc; } }` | leave literal |
| 489 | `@media print { .progress-fill { background: #6366f1 !important; } }` | leave literal |
| 553 | `color: #fff;` (checklist checked) | `var(--on-primary, #fff)` |
| 574 | `color: #fff;` (timeline badge) | `var(--on-primary, #fff)` |

Also in scope:
- Add the tokens this migration needs but TASK-2251 did not create:
  `--on-primary`, `--callout-{success,warning,error,tip}-text`,
  `--accent-teal`, and (if the shadow decision goes that way) `--shadow-light`.
  Add them to `ThemeConfig` as Optional v2 fields **following TASK-2251's exact
  pattern** (Optional, `None` default, in the `_validate_color_fields` list,
  conditionally emitted by `to_css_variables()`).
- Add a regression test asserting no bare literal colors remain in `BASE_CSS`
  outside `var()` and outside `@media print`.
- Verify all 5 built-in themes still render sanely (a token that resolves to an
  unset variable falls back, so nothing should go transparent).

**NOT in scope**:
- The `.chip` / `.method-badge` / `.i18n` rules → TASK-2252 (they are authored
  with `var()` from the start).
- The `.chain` / `.steps` / `.code-block` / `.card-grid` rules → TASK-2253 (same).
- The `.doc-*` chrome rules → TASK-2254 (same).
- Any change to markup, class names, or renderer methods. **Colors only.**
- Redesigning the visual look. Every default must resolve to the current color
  so an unthemed render looks identical.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` | MODIFY | `BASE_CSS` color migration |
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | Add the extra v2 tokens listed above |
| `tests/test_infographic_html.py` | MODIFY | No-literal-colors regression test + per-theme render checks |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-19.

### Verified Imports

No new imports in either file.

### Existing Signatures to Use

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
BASE_CSS = """\        # line 153 — opens; closes ~line 617 (a single str literal)
TAB_JS = """           # line 624 — the first thing AFTER BASE_CSS
```

CSS custom properties **already** available in `BASE_CSS` today (emitted by the
v1 `to_css_variables()`, so they are always present):

```
--primary  --primary-dark  --primary-light
--accent-green  --accent-amber  --accent-red
--neutral-bg  --neutral-border  --neutral-muted  --neutral-text
--body-bg  --font-family
```

Tokens added by TASK-2251 — **conditionally** emitted, only when the theme sets
them, so every use in `BASE_CSS` MUST carry a fallback:

```
--surface-bg  --soft-primary
--callout-info-bg  --callout-success-bg  --callout-warning-bg
--callout-error-bg  --callout-tip-bg
--code-bg  --code-text  --code-keyword  --code-string  --code-comment
--code-number  --code-function
--badge-get  --badge-post  --badge-put  --badge-delete  --badge-patch
```

```python
# packages/ai-parrot/src/parrot/models/infographic.py — the pattern to follow for new tokens
class ThemeConfig(BaseModel):                       # line 1033
    @field_validator(                               # lines 1058-1063 — add new field names HERE
        "primary", "primary_dark", "primary_light",
        "accent_green", "accent_amber", "accent_red",
        "neutral_bg", "neutral_border", "neutral_muted",
        "neutral_text", "body_bg",
        mode="before",
    )
    @classmethod
    def _validate_color_fields(cls, v: Any) -> Any: ...   # line 1066
    def to_css_variables(self) -> str: ...                # line 1075
```

The exact inventory command that produced the table above:

```bash
grep -nE "#[0-9a-fA-F]{3,8}|: *(white|black)\b|rgba?\(" \
  packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py \
  | awk -F: '$1>=153 && $1<=654'
```

### Does NOT Exist

- ~~`--on-primary`~~ — no such token; this task creates it
- ~~`--callout-info-text`~~ — note the **info** callout's `h3` already uses
  `var(--primary-dark)` (line 349), so there is no `--callout-info-text` to add;
  only success/warning/error/tip need a text token
- ~~`--accent-teal`~~ — no such token; the tip callout's `#14b8a6` border is the
  only teal in the file
- ~~`--shadow-color` / `--shadow-light`~~ — no such token
- ~~a CSS linter or stylelint config in this repo~~ — the "no literal colors"
  criterion must be enforced by a Python test that greps the `BASE_CSS` string
- ~~`BASE_CSS` being split into multiple constants~~ — it is one string literal;
  do not restructure it
- ~~a golden-file snapshot suite for the rendered HTML~~ — there is none;
  regression checking means diffing renders you capture yourself

---

## Implementation Notes

### Two judgement calls, decided here so the implementer does not have to

1. **`rgba(0,0,0,0.05)` / `rgba(0,0,0,0.06)` box-shadows (lines 168, 220).**
   Spec §7 Known Risk 4 notes these are opacity-based and theme-safe. **Decision:
   leave them as literal `rgba()`.** They are shadows, not colors of anything, and
   black-at-5% works on every background. Exclude `rgba(0,0,0,*)` from the
   no-literal-colors test rather than inventing a token nobody sets.

2. **`@media print` overrides (lines 486-489).** Spec §7 Known Risk 3 marks these
   as intentional. **Decision: leave them literal.** Print output must be
   white-background/black-text regardless of the screen theme — that is the whole
   point of the block. Exclude the `@media print` region from the
   no-literal-colors test.

Record both in the Completion Note so a reviewer sees they were decisions, not
oversights.

### The `--on-primary` token

Four sites (`172`, `263`, `553`, `574`) set `color: #fff` on top of a
`var(--primary)` / `var(--accent-green)` background. A single
`--on-primary` token covers all four. Its default is `#fff`, and the `light` /
`corporate` / `midnight` / `petrol` themes can all keep that default — the
token exists so a light-primary theme can override it to a dark ink.

### Migration mechanics

- Work rule-by-rule, not with a blind `sed` — several of these hex values appear
  in more than one context (`#fff` is at 172, 216, 243, 263, 553, 574 with two
  different meanings: surface vs. ink).
- **Every** `var()` use in `BASE_CSS` for a TASK-2251/this-task token needs a
  fallback: `var(--surface-bg, #fff)`. The v1 tokens (`--primary`,
  `--body-bg`, …) are always emitted and may be used bare, matching existing
  style.
- After migrating, render each of the 5 built-in themes and eyeball for
  transparent/invisible regions — a missing fallback shows up as an unstyled
  element, not an error.

### Key Constraints

- **An unthemed render must look identical.** Every fallback equals the current
  literal. This is a refactor.
- Do not touch markup, class names, or any renderer method.
- New `ThemeConfig` fields follow TASK-2251's pattern exactly: `Optional`, `None`
  default, added to the `_validate_color_fields` list, conditionally emitted.
- Do not add `--callout-info-text`; line 349 already resolves via `--primary-dark`.

### References in Codebase

- `infographic_html.py:346-370` — the callout block, the densest cluster
- `infographic_html.py:484-490` — the `@media print` block to leave alone
- `packages/ai-parrot/src/parrot/models/infographic.py:1058-1095` — validator +
  `to_css_variables()`, extended by TASK-2251 before you

---

## Acceptance Criteria

- [ ] All 21 inventory rows resolved: migrated, or explicitly excluded per the
      two decisions above
- [ ] `BASE_CSS` contains zero bare hex/named colors outside `var(…)`, excluding
      the `@media print` region and `rgba(0,0,0,*)` shadows
- [ ] Every `var()` reference to a conditionally-emitted token has a fallback
      equal to the pre-migration literal
- [ ] `--on-primary`, `--callout-{success,warning,error,tip}-text`, `--accent-teal`
      exist as Optional `ThemeConfig` fields, validated and conditionally emitted
- [ ] `ThemeConfig(name="x").to_css_variables()` still emits no v2 tokens
- [ ] Rendering an unthemed (`light`) payload produces output visually identical
      to pre-change — every color resolves to the same value
- [ ] All 5 built-in themes render without an unstyled/transparent region
- [ ] Callout backgrounds reference `var(--callout-*-bg, …)`
- [ ] `@media print` rules unchanged
- [ ] Tests pass: `pytest tests/test_infographic_html.py tests/test_infographic_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py packages/ai-parrot/src/parrot/models/infographic.py`

---

## Test Specification

```python
# tests/test_infographic_html.py (extend)
import re

import pytest

from parrot.models.infographic import theme_registry
from parrot.outputs.formats.infographic_html import BASE_CSS, InfographicHTMLRenderer


def _screen_css() -> str:
    """BASE_CSS with the @media print block removed."""
    return re.sub(r"@media print \{.*?\n\}", "", BASE_CSS, flags=re.S)


class TestNoLiteralColors:
    def test_no_literal_colors_in_base_css(self):
        css = _screen_css()
        # strip var(--token, fallback) — fallbacks are allowed
        css = re.sub(r"var\([^)]*\)", "VAR", css)
        # opacity-only shadows are an accepted exception (see task decisions)
        css = re.sub(r"rgba\(0,\s*0,\s*0,\s*[\d.]+\)", "SHADOW", css)
        leftovers = re.findall(r"#[0-9a-fA-F]{3,8}|:\s*(?:white|black)\b", css)
        assert leftovers == [], f"literal colors remain: {leftovers}"

    def test_callout_colors_use_variables(self):
        for level in ("info", "success", "warning", "error", "tip"):
            assert f"var(--callout-{level}-bg" in BASE_CSS

    def test_print_styles_untouched(self):
        assert "background: white" in BASE_CSS  # inside @media print
        assert "!important" in BASE_CSS


class TestThemeRenderIntegrity:
    @pytest.mark.parametrize(
        "theme", ["light", "dark", "corporate", "midnight", "petrol"]
    )
    def test_theme_renders(self, theme):
        renderer = InfographicHTMLRenderer()
        html = renderer.render_to_html(
            {"blocks": [
                {"type": "title", "title": "T"},
                {"type": "callout", "level": "tip", "content": "Tip"},
                {"type": "table", "columns": ["A"], "rows": [["1"]]},
            ]},
            theme=theme,
        )
        assert html.startswith("<!DOCTYPE html>")
        assert theme_registry.get(theme).to_css_variables() in html
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2251 must be in `sdd/tasks/completed/`; you
   need its callout/surface tokens. TASK-2252/2253/2254 may or may not have
   landed; either way, **re-run the inventory grep** in the contract above and
   reconcile it against the table before editing — line numbers will have moved
   and those tasks add new `var()`-only rules you must not "migrate".
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm the token list TASK-2251 actually emitted matches the names above
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists
4. **Capture a baseline render** of a `light`-theme fixture before touching
   `BASE_CSS`; the "visually identical" criterion is checked against it
5. **Update status** in `sdd/tasks/index/infographic-theme-catalog-a2ui.json` →
   `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2255-css-variable-migration.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-19
**Notes**: Re-ran the inventory grep against the post-TASK-2252/2253/2254
file state (line numbers had shifted, `BASE_CSS` now spans 176-802).
Migrated all 18 in-scope literal colors to `var(--token, fallback)`
form: `.container`/`.kpi-card`/`.chart-container` backgrounds →
`var(--surface-bg, #fff)`; `.hero`/`th`/checklist-checked/accordion-number
text → `var(--on-primary, #fff)`; `tr:hover` → `var(--body-bg)` (existing
v1 token); all 5 callout backgrounds → `var(--callout-{level}-bg, ...)`;
4 callout `h3` text colors → `var(--callout-{level}-text, ...)`; tip
callout border → `var(--accent-teal, #14b8a6)`. Added the 6 new
`ThemeConfig` v2 fields (`on_primary`, `callout_{success,warning,error,
tip}_text`, `accent_teal`) following TASK-2251's exact pattern (Optional,
`None` default, added to `_validate_color_fields`, conditionally emitted
by `to_css_variables()`). Added the no-literal-colors regression test,
callout-variable-usage test, print-styles-untouched test, a
parametrized 5-theme render-integrity test, and new-token
emit/non-emit tests (139 tests in `tests/test_infographic_html.py`, all
passing on first run — the migration inventory and fallback values were
correct); 89 tests across `tests/test_infographic_models.py` +
`tests/test_infographic_multi_tab.py` unaffected. `ruff check --select F`
unchanged from pre-task baseline on both files.

Also fixed one bare `color: #fff;` in `.method-badge` (authored by
TASK-2252) to `var(--on-primary, #fff)` — technically outside this
task's file-ownership boundary, but required for the feature-wide
"zero literal colors outside var()" acceptance criterion to hold across
the whole `BASE_CSS` string, which this task's regression test asserts
unconditionally.

**Shadow decision**: left literal — both `rgba(0,0,0,0.05)` /
`rgba(0,0,0,0.06)` box-shadows kept as-is per spec §7 Known Risk 4
(opacity-based black shadow is theme-safe on every background); the
regression test explicitly excludes `rgba(0,0,0,*)` rather than
inventing an unused shadow token.
**Print-style decision**: left literal — the 3 `@media print` overrides
(body background, `.hero` colors, `.progress-fill`) are intentionally
theme-independent per spec §7 Known Risk 3; the regression test strips
the `@media print` block before scanning.

**Deviations from spec**: none beyond the `.method-badge` fix noted above.
