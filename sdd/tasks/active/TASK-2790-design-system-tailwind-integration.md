# TASK-2790: DesignSystem.stylesheet() — fold in generated Tailwind CSS

**Feature**: FEAT-522 — Interactive-HTML Map Rendering + Tailwind CSS Coverage
**Spec**: `sdd/specs/interactive-html-map-tailwind.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2789
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 / §6: `DesignSystem.stylesheet()`
(`design_system/__init__.py:88-119`) concatenates
`theme_config.to_css_variables() + _BASE_CSS + _COMPONENTS_CSS + layout_css`.
TASK-2789 produces `design_system/tailwind.generated.css`. This small task wires
that file into the concatenation, using the exact same `_read_asset()` /
module-level-constant pattern already used for `_BASE_CSS`/`_COMPONENTS_CSS`.

## Scope

- Add `_TAILWIND_CSS: str = _read_asset("tailwind.generated.css") or ""` at
  module level in `design_system/__init__.py`, alongside `_BASE_CSS`/
  `_COMPONENTS_CSS` (line ~57-58).
- Insert `_TAILWIND_CSS` into `stylesheet()`'s `sheet = "\n\n".join(...)` tuple,
  positioned AFTER `_COMPONENTS_CSS` and BEFORE `layout_css` (spec §3 Module 5:
  "base-primitive coverage, not layout-specific").
- `design_system`'s existing `package-data` glob (`["*.css"]`) already covers
  the new file — verify this is actually true (no change needed to
  `pyproject.toml` for this specific file, unlike the flat `formats/assets/`
  files from TASK-2785 which needed a glob extension).

**NOT in scope**:
- Generating the file itself (TASK-2789, already done).
- Any CI wiring (TASK-2791).
- Any change to `_BASE_CSS`/`_COMPONENTS_CSS`/layout CSS content.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py` | MODIFY | Add `_TAILWIND_CSS` constant + fold into `stylesheet()` |

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py
_ASSETS_DIR = Path(__file__).parent  # line 32
def _read_asset(name: str) -> str | None: ...  # line 35 — returns None + logs
                                                  # warning if missing, never raises
_BASE_CSS: str = _read_asset("base.css") or ""            # line 57
_COMPONENTS_CSS: str = _read_asset("components.css") or "" # line 58
_LAYOUT_CSS: dict[str, str | None] = {...}                  # lines 63-68

class DesignSystem:
    @classmethod
    def stylesheet(cls, theme=None, layout=None) -> str:  # line 88
        theme_config, theme_key = cls._resolve_theme(theme)
        layout_key, layout_css = cls._resolve_layout(layout)
        cache_key = (theme_key, layout_key)
        cached = cls._cache.get(cache_key)
        if cached is not None:
            return cached
        sheet = "\n\n".join(
            part for part in (
                theme_config.to_css_variables(),
                _BASE_CSS,
                _COMPONENTS_CSS,
                layout_css or "",
            ) if part
        )  # lines 105-114 — insert _TAILWIND_CSS between _COMPONENTS_CSS and layout_css
        cls._cache[cache_key] = sheet
        return sheet
```

### Does NOT Exist
- ~~`_TAILWIND_CSS` anywhere in this file today~~ — this task creates it.
- ~~A separate package-data entry needed for `tailwind.generated.css`~~ — the
  existing `"parrot.outputs.formats.assets.design_system" = ["*.css"]` glob
  already covers any `*.css` file in this directory, including the new one;
  verify this rather than assuming, but do not add a redundant entry if
  confirmed correct.

---

## Implementation Notes

### Pattern to Follow
```python
_BASE_CSS: str = _read_asset("base.css") or ""
_COMPONENTS_CSS: str = _read_asset("components.css") or ""
_TAILWIND_CSS: str = _read_asset("tailwind.generated.css") or ""  # NEW
...
sheet = "\n\n".join(
    part for part in (
        theme_config.to_css_variables(),
        _BASE_CSS,
        _COMPONENTS_CSS,
        _TAILWIND_CSS,  # NEW
        layout_css or "",
    ) if part
)
```

### Key Constraints
- Must degrade gracefully (empty string, not an exception) if
  `tailwind.generated.css` is missing — matches `_read_asset()`'s existing
  contract (`_read_asset` already returns `None`/logs a warning on
  `FileNotFoundError`; the `or ""` fallback already handles it, same as every
  other asset constant in this file).
- `DesignSystem._cache` is keyed by `(theme_key, layout_key)` — no cache-key
  change needed since `_TAILWIND_CSS` is a fixed module-level constant, not a
  per-call variable.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py` — file being modified.
- `packages/ai-parrot-visualizations/pyproject.toml` — verify the existing `design_system` package-data glob covers the new file (read-only check, likely no change needed).

---

## Acceptance Criteria

- [ ] `_TAILWIND_CSS` module-level constant exists, read via `_read_asset()`.
- [ ] `DesignSystem.stylesheet()`'s output for any `(theme, layout)` pair
  includes the Tailwind-generated rules (verify by checking a known selector
  from TASK-2789's output, e.g. `.a2ui-col`, appears in `stylesheet()`'s
  returned string).
- [ ] `stylesheet()` still returns without raising if
  `tailwind.generated.css` is (hypothetically) absent — verify via a
  monkeypatched/missing-file test, mirroring how the existing layout-CSS
  missing-file fallback is tested (if such a test exists — check
  `test_semantic_classes.py`'s `TestResolutionPrecedence`/related classes for
  precedent).
- [ ] Existing `DesignSystem`/semantic-class tests continue passing unmodified.
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_semantic_classes.py (additions)
from parrot.outputs.formats.assets.design_system import DesignSystem


class TestTailwindCoverageIntegration:
    def test_stylesheet_includes_tailwind_generated_rules(self):
        sheet = DesignSystem.stylesheet()
        assert ".a2ui-col" in sheet  # a known base-primitive selector from TASK-2789's output
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/interactive-html-map-tailwind.spec.md` §3
   Module 5, §6.
2. **Check dependencies** — verify TASK-2789 is in `sdd/tasks/completed/`
   before starting (this task consumes its output file).
3. Verify the Codebase Contract's line numbers against the current
   `design_system/__init__.py` before editing.
4. Update status in the per-spec index → `"in-progress"`.
5. Implement per scope.
6. Verify all acceptance criteria.
7. Move this file to `sdd/tasks/completed/`.
8. Update the per-spec index → `"done"`.
9. Fill in the Completion Note below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
