# TASK-2251: ThemeConfig v2 Tokens & Petrol Theme

**Feature**: FEAT-301 — Themed Component Catalog — HTML Renderer v2
**Spec**: `sdd/specs/infographic-theme-catalog-a2ui.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec (§3). `ThemeConfig` today carries 11 color
tokens + a font stack, all of which `to_css_variables()` emits as CSS custom
properties. The HTML renderer's `BASE_CSS` hardcodes ~21 further colors that
have no token behind them (callout backgrounds, card surfaces, table hover,
code block colors), which is why TASK-2255 cannot migrate them yet — the
tokens must exist first.

This task adds those tokens, a `derive_soft()` helper for tinted backgrounds,
and registers `petrol` as the 5th built-in theme.

Every new field is `Optional` with a `None` default, and `to_css_variables()`
emits a v2 token **only when it is set** — that is what keeps the 4 existing
themes and any user-registered `ThemeConfig` valid and byte-identical.

---

## Scope

- Add `CodePalette` sub-model (7 fields) and `MethodBadgePalette` sub-model
  (5 fields), both declared **before** `ThemeConfig`.
- Add these Optional v2 fields to `ThemeConfig`:
  `code_palette`, `method_badge_palette`, `surface_bg`, `soft_primary`,
  `callout_info_bg`, `callout_success_bg`, `callout_warning_bg`,
  `callout_error_bg`, `callout_tip_bg`.
- Add the new **scalar color** fields to the existing
  `@field_validator(..., mode="before")` list on `ThemeConfig` (line 1058-1063)
  so they get `_CSS_COLOR_RE` validation. The two palette sub-models validate
  their own fields.
- Add module-level `derive_soft(hex_color: str, alpha: float = 0.12) -> str`.
- Extend `to_css_variables()` to emit the v2 tokens conditionally.
- Register the `petrol` theme after `midnight`.
- Write unit tests.

**NOT in scope**:
- Touching `BASE_CSS` → TASK-2255. Any other change under
  `ai-parrot-visualizations` → TASK-2252 / 2253 / 2254 / 2256.
- The 4 new block models / `I18nText` / `DocumentMeta` → TASK-2263.
- Rendering anything — this task only produces tokens and CSS variables.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | `CodePalette`, `MethodBadgePalette`, v2 fields, validator list, `derive_soft()`, `to_css_variables()`, `petrol` registration |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | Export `CodePalette`, `MethodBadgePalette`, `derive_soft` |
| `tests/test_infographic_html.py` | MODIFY | Add theme-v2 + petrol tests (this is where the existing theme tests live) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-19.

### Verified Imports

```python
# already present at packages/ai-parrot/src/parrot/models/infographic.py
import re                                                                              # (used by _CSS_COLOR_RE)
from typing import List, Optional, Any, Annotated, ClassVar, Dict, Literal, Tuple, Union  # line 25
from pydantic import BaseModel, Discriminator, Field, field_validator, model_validator     # line 39
```

No new imports needed.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/infographic.py

_CSS_COLOR_RE = re.compile(          # lines 46-50 — VERBATIM, do not modify
    r'^(#[0-9a-fA-F]{3,8}|rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+(?:\s*,\s*[\d.]+)?\s*\)'
    r'|hsla?\(\s*[\d.]+\s*,\s*[\d.%]+\s*,\s*[\d.%]+(?:\s*,\s*[\d.]+)?\s*\)'
    r'|[a-zA-Z][-a-zA-Z]*|var\(--[-\w]+\))$'
)
# NOTE: this regex ACCEPTS rgba(...) — so derive_soft()'s output is a valid
# value for any validated color field. It also accepts bare named colors and
# var(--x) references.

class ThemeConfig(BaseModel):                              # line 1033
    name: str = Field(..., description="Theme identifier")            # line 1040
    primary: str = Field("#6366f1", ...)                              # line 1041
    primary_dark: str = Field("#4f46e5", ...)                          # line 1042
    primary_light: str = Field("#818cf8", ...)                         # line 1043
    accent_green: str = Field("#10b981", ...)                          # line 1044
    accent_amber: str = Field("#f59e0b", ...)                          # line 1045
    accent_red: str = Field("#ef4444", ...)                            # line 1046
    neutral_bg: str = Field("#f8fafc", ...)                            # line 1047
    neutral_border: str = Field("#e2e8f0", ...)                        # line 1048
    neutral_muted: str = Field("#64748b", ...)                         # line 1049
    neutral_text: str = Field("#0f172a", ...)                          # line 1050
    body_bg: str = Field("#f1f5f9", ...)                               # line 1051
    font_family: str = Field('-apple-system, BlinkMacSystemFont, ...') # lines 1052-1055

    @field_validator(                                                  # lines 1058-1063
        "primary", "primary_dark", "primary_light",
        "accent_green", "accent_amber", "accent_red",
        "neutral_bg", "neutral_border", "neutral_muted",
        "neutral_text", "body_bg",
        mode="before",
    )
    @classmethod
    def _validate_color_fields(cls, v: Any) -> Any:                    # line 1066
        """Validate CSS color values — raises ValueError on invalid input."""
        if v is not None and not _CSS_COLOR_RE.match(str(v).strip()):
            raise ValueError(f"Invalid CSS color value: {v!r}. ...")
        return v

    def to_css_variables(self) -> str:                                 # line 1075
        props = [
            f"    --primary: {self.primary};",
            f"    --primary-dark: {self.primary_dark};",
            f"    --primary-light: {self.primary_light};",
            f"    --accent-green: {self.accent_green};",
            f"    --accent-amber: {self.accent_amber};",
            f"    --accent-red: {self.accent_red};",
            f"    --neutral-bg: {self.neutral_bg};",
            f"    --neutral-border: {self.neutral_border};",
            f"    --neutral-muted: {self.neutral_muted};",
            f"    --neutral-text: {self.neutral_text};",
            f"    --body-bg: {self.body_bg};",
            f"    --font-family: {self.font_family};",
        ]
        return ":root {\n" + "\n".join(props) + "\n}"

class ThemeRegistry:                                       # line 1098
    _themes: Dict[str, ThemeConfig]                        # line 1106
    def register(self, theme: ThemeConfig) -> None:        # line 1108
    def get(self, name: str) -> ThemeConfig:               # line 1116
    def list_themes(self) -> List[str]:                    # line 1135
    def list_themes_detailed(self) -> List[Dict]:          # line 1143 — returns dicts of
                                                           #   name/primary/neutral_bg/body_bg

theme_registry = ThemeRegistry()                           # line 1162
# built-ins: light (1166), dark (1181), corporate (1196), midnight (1211)
# register petrol AFTER the midnight block (ends ~line 1232)
```

Registration pattern, verbatim from the `midnight` block:

```python
theme_registry.register(ThemeConfig(
    name="midnight",
    primary="#60a5fa",        # blue-400 — links, KPIs, accents
    ...
    body_bg="#0f172a",        # slate-900 — page background
    font_family=(
        '-apple-system, BlinkMacSystemFont, "Segoe UI", '
        'sans-serif'
    ),
))
```

### Does NOT Exist

- ~~`ThemeConfig.code_palette` / `.method_badge_palette`~~ — create them
- ~~`ThemeConfig.surface_bg` / `.soft_primary`~~ — create them
- ~~`ThemeConfig.callout_info_bg` / `_success_` / `_warning_` / `_error_` / `_tip_bg`~~ — create them
- ~~`parrot.models.infographic.CodePalette` / `MethodBadgePalette`~~ — create them
- ~~`parrot.models.infographic.derive_soft()`~~ — create it
- ~~`theme_registry.get("petrol")`~~ — raises today; register it
- ~~`ThemeConfig.to_css_variables()` emitting `--code-bg` / `--surface-bg` / `--callout-*-bg`~~ —
  emits only the 12 v1 properties listed above
- ~~a `--shadow-color` or `--shadow-light` token~~ — does not exist; TASK-2255
  decides whether to add one, not this task
- ~~`parrot.helpers.infographics` needing changes~~ — it is a pure pass-through
  façade over `theme_registry` (`list_themes` / `get_theme` / `register_theme`);
  a 5th theme flows through with zero changes
- ~~a canonical FieldSync petrol palette in the repo~~ — no hex values for
  `petrol` are recorded in the spec, the proposal, or `sdd/state/FEAT-301/`.
  Use the palette pinned below.

---

## Implementation Notes

### The petrol palette (decision required — see below)

The spec calls for a `petrol` theme "matching the FieldSync design system", but
**no FieldSync hex values exist anywhere in the repo**. Rather than let the
implementing agent invent colors ad hoc, use this palette — a dark
teal/petrol-blue set built to the same structure as `midnight`:

```python
theme_registry.register(ThemeConfig(
    name="petrol",
    primary="#0e7490",        # cyan-700 — links, KPIs, accents
    primary_dark="#155e75",   # cyan-800 — hover states, borders
    primary_light="#22d3ee",  # cyan-400 — subtle highlights
    accent_green="#0d9488",   # teal-600 — success, in-progress
    accent_amber="#d97706",   # amber-600 — warnings, notices
    accent_red="#b91c1c",     # red-700 — errors, blockers
    neutral_bg="#ffffff",     # card / section surface
    neutral_border="#cbd5e1",  # slate-300 — borders, dividers
    neutral_muted="#475569",  # slate-600 — labels, secondary text
    neutral_text="#0f172a",   # slate-900 — primary text
    body_bg="#ecfeff",        # cyan-50 — page background
    surface_bg="#ffffff",
    soft_primary=derive_soft("#0e7490", 0.10),
    code_palette=CodePalette(),          # editor-dark defaults are intentional
    method_badge_palette=MethodBadgePalette(),
))
```

> **If a canonical FieldSync palette exists outside this repo, swap these hex
> values before implementing and note the substitution in the Completion Note.**
> Everything else in this task is independent of the exact values.

### `derive_soft()`

```python
def derive_soft(hex_color: str, alpha: float = 0.12) -> str:
    """Derive a soft/tinted background from a hex color.

    Used for pill backgrounds, chip tints, and callout backgrounds where a
    low-opacity wash of an accent color is wanted over the page background.

    Args:
        hex_color: A 3-, 6-, or 8-digit hex color (``#rgb`` / ``#rrggbb``).
        alpha: Opacity of the returned color, 0.0-1.0.

    Returns:
        An ``rgba(r, g, b, a)`` string — accepted by ``_CSS_COLOR_RE``.

    Raises:
        ValueError: If ``hex_color`` is not a parseable hex color or ``alpha``
            is outside 0.0-1.0.
    """
```

Expand 3-digit shorthand (`#abc` → `#aabbcc`), ignore a trailing alpha pair on
8-digit input, and emit no spaces beyond `rgba(r, g, b, a)` so the output stays
matchable by `_CSS_COLOR_RE`.

### `to_css_variables()` — conditional v2 emission

Append to the existing `props` list, guarding each token:

```python
if self.surface_bg is not None:
    props.append(f"    --surface-bg: {self.surface_bg};")
if self.soft_primary is not None:
    props.append(f"    --soft-primary: {self.soft_primary};")
for level in ("info", "success", "warning", "error", "tip"):
    value = getattr(self, f"callout_{level}_bg")
    if value is not None:
        props.append(f"    --callout-{level}-bg: {value};")
if self.code_palette is not None:
    props.append(f"    --code-bg: {self.code_palette.background};")
    props.append(f"    --code-text: {self.code_palette.text};")
    ...  # --code-keyword, --code-string, --code-comment, --code-number, --code-function
if self.method_badge_palette is not None:
    props.append(f"    --badge-get: {self.method_badge_palette.get};")
    ...  # --badge-post, --badge-put, --badge-delete, --badge-patch
```

CSS variable names are the contract TASK-2252 / 2253 / 2254 / 2255 render against — use
exactly `--surface-bg`, `--soft-primary`, `--callout-{level}-bg`,
`--code-bg`, `--code-text`, `--code-keyword`, `--code-string`,
`--code-comment`, `--code-number`, `--code-function`, `--badge-{method}`.

### Key Constraints

- **Every v2 field is `Optional[...] = None`.** A `ThemeConfig(name="x")` must
  still construct, and `to_css_variables()` on a v1-only theme must emit
  exactly the 12 v1 properties — no empty `--surface-bg: ;` lines.
- Sub-model defaults come from spec §2 ("New Public Interfaces"): `CodePalette`
  keyword `#c678dd`, string `#98c379`, comment `#5c6370`, number `#d19a66`,
  function `#61afef`, background `#282c34`, text `#abb2bf`;
  `MethodBadgePalette` get `#10b981`, post `#6366f1`, put `#f59e0b`,
  delete `#ef4444`, patch `#8b5cf6`.
- Add the same `_CSS_COLOR_RE` validation to the sub-models' fields — copy the
  `_validate_color_fields` shape rather than importing it across classes.
- Existing tests use `issubset` for theme names
  (`tests/test_infographic_html.py:224`, `packages/ai-parrot/tests/helpers/test_infographics_helpers.py:88`),
  so a 5th theme will not break them. Do **not** add a strict
  `len(list_themes()) == 5` assertion to those files — assert it in your new
  test instead, and be aware user code can register more themes at runtime.

### References in Codebase

- `packages/ai-parrot/src/parrot/models/infographic.py:1211` — `midnight` theme,
  the registration pattern to copy (including the inline color comments)
- `packages/ai-parrot/src/parrot/models/infographic.py:1066` — the validator to extend
- `packages/ai-parrot/src/parrot/helpers/infographics.py` — the façade that
  surfaces themes to SDK consumers (no changes needed; verify it still works)

---

## Acceptance Criteria

- [ ] `ThemeConfig(name="x")` still constructs with no v2 fields (backward compat)
- [ ] `ThemeConfig(name="x").to_css_variables()` emits exactly the 12 v1
      properties and no v2 tokens
- [ ] A `ThemeConfig` with `code_palette` + `surface_bg` + callout tokens emits
      the corresponding `--code-*` / `--surface-bg` / `--callout-*-bg` variables
- [ ] `derive_soft("#6366f1", 0.12)` returns a valid `rgba(...)` string that
      `_CSS_COLOR_RE` matches
- [ ] `derive_soft` raises `ValueError` on `"not-a-color"` and on `alpha=1.5`
- [ ] `theme_registry.get("petrol")` returns a `ThemeConfig` with `name == "petrol"`
- [ ] `"petrol"` appears in `theme_registry.list_themes()` and in
      `list_themes_detailed()`
- [ ] All 5 built-in themes produce a `to_css_variables()` string starting with
      `:root {` and ending with `}`
- [ ] Assigning an invalid color to any new scalar field raises `ValidationError`
- [ ] Imports work: `from parrot.models import CodePalette, MethodBadgePalette, derive_soft`
- [ ] Tests pass: `pytest tests/test_infographic_html.py -v`
- [ ] Façade tests still pass: `pytest packages/ai-parrot/tests/helpers/test_infographics_helpers.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/infographic.py`

---

## Test Specification

```python
# tests/test_infographic_html.py (extend the existing theme test class)
import pytest
from pydantic import ValidationError

from parrot.models.infographic import (
    CodePalette, MethodBadgePalette, ThemeConfig, derive_soft, theme_registry,
)


def test_theme_config_v2_backward_compat():
    theme = ThemeConfig(name="v1only")
    css = theme.to_css_variables()
    assert "--surface-bg" not in css
    assert "--code-bg" not in css
    assert css.count("--") == 12


def test_theme_config_v2_fields():
    theme = ThemeConfig(
        name="v2", surface_bg="#ffffff", soft_primary="rgba(99, 102, 241, 0.12)",
        callout_info_bg="#eff6ff", code_palette=CodePalette(),
        method_badge_palette=MethodBadgePalette(),
    )
    css = theme.to_css_variables()
    assert "--surface-bg: #ffffff;" in css
    assert "--callout-info-bg: #eff6ff;" in css
    assert "--code-bg: #282c34;" in css
    assert "--badge-get: #10b981;" in css


def test_derive_soft():
    value = derive_soft("#6366f1", 0.12)
    assert value == "rgba(99, 102, 241, 0.12)"
    from parrot.models.infographic import _CSS_COLOR_RE
    assert _CSS_COLOR_RE.match(value)


def test_derive_soft_shorthand_and_errors():
    assert derive_soft("#abc", 0.5).startswith("rgba(170, 187, 204")
    with pytest.raises(ValueError):
        derive_soft("not-a-color")
    with pytest.raises(ValueError):
        derive_soft("#6366f1", 1.5)


def test_petrol_theme_registered():
    theme = theme_registry.get("petrol")
    assert theme.name == "petrol"
    assert theme.code_palette is not None


def test_petrol_in_theme_listings():
    assert "petrol" in theme_registry.list_themes()
    assert "petrol" in [t["name"] for t in theme_registry.list_themes_detailed()]


def test_all_builtin_themes_emit_css():
    for name in ("light", "dark", "corporate", "midnight", "petrol"):
        css = theme_registry.get(name).to_css_variables()
        assert css.startswith(":root {") and css.endswith("}")


def test_invalid_v2_color_rejected():
    with pytest.raises(ValidationError):
        ThemeConfig(name="bad", surface_bg="#not-a-hex-!!")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none; this task can start immediately. It touches
   the same file as TASK-2263 but a different region (~line 1033+ vs ~line 71-935);
   if TASK-2263 landed first, re-grep line numbers before editing.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `_CSS_COLOR_RE`, `ThemeConfig`, the validator list, and
     `to_css_variables()` still look as listed
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists
4. **Resolve the petrol palette** — use the pinned values above unless a
   canonical FieldSync palette is supplied; record what you used.
5. **Update status** in `sdd/tasks/index/infographic-theme-catalog-a2ui.json` →
   `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2251-themeconfig-v2-petrol-theme.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-19
**Notes**: Added `CodePalette` and `MethodBadgePalette` sub-models (with
`_CSS_COLOR_RE`-backed validators) before `ThemeConfig`. Added the 9 v2
`Optional` fields (`code_palette`, `method_badge_palette`, `surface_bg`,
`soft_primary`, `callout_{info,success,warning,error,tip}_bg`) to
`ThemeConfig`, extended the scalar-color `_validate_color_fields`
validator list, added module-level `derive_soft()`, and extended
`to_css_variables()` to emit v2 tokens conditionally (verified a v1-only
theme emits exactly 12 properties). Registered `petrol` as the 5th
built-in theme after `midnight`. Exported `CodePalette`,
`MethodBadgePalette`, `derive_soft` from `parrot/models/__init__.py`
(both the import block and `__all__`). Added the full v2/petrol test
suite to `tests/test_infographic_html.py` (86 tests total, all passing).
Façade tests (`packages/ai-parrot/tests/helpers/test_infographics_helpers.py`,
16 tests) still pass unchanged. `ruff check --select F` clean on all 3
touched files.
**Petrol palette used**: pinned default (cyan/teal petrol-blue palette
from the task's Implementation Notes) — no canonical FieldSync hex
values were found in the repo.

**Deviations from spec**: none
