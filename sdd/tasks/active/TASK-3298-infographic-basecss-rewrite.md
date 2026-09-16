# TASK-3298: Rewrite `BASE_CSS` assertions against `DesignSystem.stylesheet`

**Feature**: FEAT-562 — CI Test-Failure Root-Cause Remediation
**Spec**: `sdd/specs/ci-test-failures-root-cause-remediation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements Module 6. `BASE_CSS` was removed from
`parrot.outputs.formats.infographic_html` by FEAT-493/TASK-2712 and replaced by
the composed `DesignSystem.stylesheet(theme, layout, *, paged)`; the `"report"`
layout reproduces the old look. `tests/test_infographic_html.py` still imports
and asserts against the removed `BASE_CSS` symbol (line 54), so the module
fails to collect (`ImportError: cannot import name 'BASE_CSS'`). This task
translates those assertions to the new composer, preserving each assertion's
*intent* — it is a real rewrite, not a symbol rename, because different old
`BASE_CSS` fragments now live across `_BASE_CSS` / `_COMPONENTS_CSS` /
`_EDITORIAL_CSS` / the `report` layout sheet.

This is the spec's highest-judgment module: a mistranslated assertion would
silently stop testing what it used to test — exactly the failure mode the user
warned against — so every translated assertion must still verify the same
design property, and any genuinely-dropped rule is a documented, deliberate
removal in the Completion Note (never a silent deletion).

---

## Scope

- Replace the `BASE_CSS` import with the `DesignSystem` composer + `theme_registry`.
- Translate every `BASE_CSS` reference (line 54 import; the `_screen_css()`
  helper at 323-324; the callout/print assertions at 338-343; and every other
  reference through at least line 1325) to build the equivalent CSS via
  `DesignSystem.stylesheet(theme_registry.get("light"), layout="report",
  paged=False)` (or the `paged` value the specific historical check requires).
- Preserve each assertion's design intent (no literal colors, callout CSS
  variables present, `@media print` rules intact, `.doc-bar`/`.doc-footer`
  fallbacks, etc.).

**NOT in scope**: any change to production CSS or `DesignSystem`; other test
files. If a translated assertion reveals a genuine regression in the composed
sheet, record it as an evidenced finding — do NOT weaken the assertion to pass.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_infographic_html.py` | MODIFY | Swap `BASE_CSS` import + rewrite ~15 assertions against `DesignSystem.stylesheet` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.formats.assets.design_system import DesignSystem  # verified: packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py:91
from parrot.models.infographic import theme_registry  # verified: design_system/__init__.py:24 (the same import DesignSystem itself uses)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer  # STILL EXISTS — keep it (only BASE_CSS was removed)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py
class DesignSystem:
    LAYOUTS: ClassVar[frozenset[str]]     # {"report", "analytics", "print"} — line 96
    DEFAULT_LAYOUT: ClassVar[str]         # "analytics" — line 98
    @classmethod
    def stylesheet(cls, theme: "str | ThemeConfig | None" = None,
                   layout: str | None = None, *, paged: bool | None = None) -> str: ...  # line 100
# The composed sheet concatenates, in order (verified: design_system/__init__.py:146-156):
#   theme_config.to_css_variables(), _BASE_CSS, _COMPONENTS_CSS, _TAILWIND_CSS,
#   _EDITORIAL_CSS, <layout css>, and (when NOT paged) _PRINT_MEDIA_CSS.
# So the "@media print" block that _screen_css() strips comes from _PRINT_MEDIA_CSS,
# included only when paged is falsy → call with paged=False to keep it.
```

### Does NOT Exist
- ~~`parrot.outputs.formats.infographic_html.BASE_CSS`~~ — removed by
  FEAT-493/TASK-2712 (verified: `grep -n BASE_CSS packages/ai-parrot-visualizations/.../infographic_html.py`
  finds only docstring mentions, no symbol).
- ~~a single sheet that equals the old `BASE_CSS`~~ — the old fragments are
  now split across several `_*_CSS` constants + the `report` layout sheet; do
  not assume one call reproduces every old fragment verbatim.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "tests/test_infographic_html.py", "action": "MODIFY" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py#DesignSystem"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Preserve assertion intent. `test_no_literal_colors_in_base_css`,
  `test_callout_colors_use_variables`, `test_print_styles_untouched` must still
  verify: no literal hex/named colors (var() fallbacks allowed), `var(--callout-
  <level>-bg` present for each level, and `@media print` + `!important` rules
  present.
- A helper like `_report_css()` returning
  `DesignSystem.stylesheet(theme_registry.get("light"), layout="report",
  paged=False)` centralizes the swap; `_screen_css()` then strips `@media print`
  from THAT instead of from `BASE_CSS`.
- If a specific old fragment now lives only in the `report` layout sheet vs the
  base sheet, the composed `stylesheet(..., layout="report")` still contains it
  (it concatenates both) — assert against the composed whole, not a fragment.

---

## Implementation Blueprint

### Steps (in order)
1. Add a module-level `_report_css()` helper and swap the line-54 import —
   *why*: one place to produce the composed sheet the old `BASE_CSS` stood for.
2. Repoint `_screen_css()` and every `BASE_CSS` reference at `_report_css()` —
   *why*: preserves each test's target without touching production code.
3. Run the file; for each still-failing assertion, decide whether the property
   genuinely moved/dropped (document it) or the check needs the composed sheet
   — *why*: M6 is judgment-heavy; a silent deletion is forbidden.

### `tests/test_infographic_html.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.outputs.formats.infographic_html import BASE_CSS' tests/test_infographic_html.py)
# REPLACE line 54 `from parrot.outputs.formats.infographic_html import BASE_CSS, InfographicHTMLRenderer`
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer  # verified: symbol still exists
from parrot.outputs.formats.assets.design_system import DesignSystem  # verified: design_system/__init__.py:91
from parrot.models.infographic import theme_registry  # verified: design_system/__init__.py:24


def _report_css() -> str:
    """The composed 'report'-layout sheet that replaces the legacy BASE_CSS.

    paged=False keeps the `@media print` block (from _PRINT_MEDIA_CSS) that the
    old BASE_CSS carried inline and that `_screen_css()` strips.
    """
    return DesignSystem.stylesheet(theme_registry.get("light"), layout="report", paged=False)
```
**Why this shape**: recreates the old `BASE_CSS` string via the supported
composer so the ~15 downstream assertions can point at `_report_css()` with
their intent intact. Do NOT change `DesignSystem` or any CSS asset — the
production code is correct; only the test lagged the FEAT-493 refactor.

```python
# occurrences: 1 (verified: grep -c 'def _screen_css' tests/test_infographic_html.py)
# MODIFY `_screen_css()` (line ~322) to strip @media print from _report_css()
# instead of BASE_CSS:
#     return re.sub(r"@media print \{.*?\n\}", "", _report_css(), flags=re.S)
#
# FILL IN: repoint every remaining `BASE_CSS` reference (verified locations:
# lines 324, 338-343, and through at least 1325 — re-grep for the exact set)
# at `_report_css()`. For each, confirm the asserted property still holds in the
# composed report sheet; if a property genuinely moved to a different layout or
# was intentionally dropped by FEAT-493, record that in the Completion Note as a
# deliberate removal — bounded by AC "every assertion's intent is preserved".
```
**Why**: `_screen_css()` and the callout/print/fallback assertions describe the
document CSS the composer now emits; pointing them at `_report_css()` keeps the
exact checks. A silent deletion is the one thing this task must not do.

### FILL IN checklist
- [ ] Every `BASE_CSS` reference repointed at `_report_css()`; grep confirms 0 remain — bounded by AC "no reference to BASE_CSS remains".
- [ ] Each translated assertion re-verified against the composed report sheet; any dropped rule documented in the Completion Note — bounded by AC "intent preserved / never a silent deletion".

---

## Acceptance Criteria

- [ ] `grep -n BASE_CSS tests/test_infographic_html.py` returns nothing.
- [ ] `pytest tests/test_infographic_html.py -q` passes.
- [ ] Each previously-`BASE_CSS` assertion still verifies the same design
      property against the composed `report`-layout sheet; any genuinely
      no-longer-applicable rule is recorded as a deliberate, evidenced removal
      in the Completion Note (never silently deleted).
- [ ] `ruff check tests/test_infographic_html.py` clean.

---

## Test Specification

This task *is* a test file. Success = the module collects and its whole suite
passes with the property assertions intact. The implementer must diff the set
of asserted properties before/after to confirm none was silently dropped.

---

## Agent Instructions

Standard SDD flow. No dependencies — can start immediately. This is the
highest-judgment task in the feature: do not rush the per-assertion translation.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
