# TASK-644: Infographic Theme System

**Feature**: infographic-html-output
**Spec**: `sdd/specs/infographic-html-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements Module 1 from the spec. The theme system provides CSS variable
> configurations for the HTML infographic renderer. Each theme defines colors,
> fonts, and spacing as a Pydantic model (`ThemeConfig`). A `ThemeRegistry`
> singleton manages built-in and user-registered themes.

---

## Scope

- Add `ThemeConfig` Pydantic model to `parrot/models/infographic.py` with fields:
  `name`, `primary`, `primary_dark`, `primary_light`, `accent_green`, `accent_amber`,
  `accent_red`, `neutral_bg`, `neutral_border`, `neutral_muted`, `neutral_text`,
  `body_bg`, `font_family`.
- Add `ThemeRegistry` class with methods: `register(theme)`, `get(name)`, `list_themes()`.
- Create module-level singleton: `theme_registry = ThemeRegistry()`.
- Register 3 built-in themes: `light`, `dark`, `corporate`.
  - `light`: Use CSS values from `docs/infographic-1775694709159.html` (primary: #6366f1, etc.)
  - `dark`: Dark background variant (neutral_bg: #1e293b, neutral_text: #f1f5f9, body_bg: #0f172a)
  - `corporate`: Subdued blue/gray palette (primary: #1e40af, neutral tones)
- Add a `to_css_variables()` method on `ThemeConfig` that returns a `:root { ... }` CSS string.
- Export `ThemeConfig`, `ThemeRegistry`, `theme_registry` from `parrot/models/__init__.py`.

**NOT in scope**:
- HTML rendering (TASK-645)
- ECharts integration (TASK-646)
- Content negotiation (TASK-647)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | Add ThemeConfig, ThemeRegistry, theme_registry, built-in themes |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | Export ThemeConfig, ThemeRegistry, theme_registry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # used throughout parrot/models/
from typing import Dict, List, Optional  # standard

# After this task, these will be importable:
# from parrot.models.infographic import ThemeConfig, ThemeRegistry, theme_registry
```

### Existing Signatures to Use
```python
# parrot/models/infographic.py:311-332
class InfographicResponse(BaseModel):
    template: Optional[str]            # line 313
    theme: Optional[str]               # line 318 — this is the theme name hint
    blocks: List[InfographicBlock]     # line 319
    metadata: Optional[Dict[str, Any]] # line 325

# parrot/models/infographic_templates.py:310-379
class InfographicTemplateRegistry:
    """Follow this same registry pattern for ThemeRegistry."""
    def register(self, template: InfographicTemplate) -> None:  # line 329
    def get(self, name: str) -> InfographicTemplate:  # line 345 — raises KeyError
    def list_templates(self) -> List[str]:  # line 361
```

### Does NOT Exist
- ~~`parrot.themes`~~ — no theme module; add themes to `parrot/models/infographic.py`
- ~~`ThemeConfig`~~ — does not exist yet; this task creates it
- ~~`ThemeRegistry`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the InfographicTemplateRegistry pattern (infographic_templates.py:310-379)
class ThemeRegistry:
    def __init__(self):
        self._themes: Dict[str, ThemeConfig] = {}

    def register(self, theme: ThemeConfig) -> None:
        self._themes[theme.name] = theme

    def get(self, name: str) -> ThemeConfig:
        try:
            return self._themes[name]
        except KeyError:
            raise KeyError(f"Theme '{name}' not found. Available: {self.list_themes()}")

    def list_themes(self) -> List[str]:
        return list(self._themes.keys())

# Singleton + register built-ins
theme_registry = ThemeRegistry()
```

### CSS Variables Reference (from docs/infographic-1775694709159.html)
```css
:root {
    --primary: #6366f1;
    --primary-dark: #4f46e5;
    --primary-light: #818cf8;
    --accent-green: #10b981;
    --accent-amber: #f59e0b;
    --accent-red: #ef4444;
    --neutral-bg: #f8fafc;
    --neutral-border: #e2e8f0;
    --neutral-muted: #64748b;
    --neutral-text: #0f172a;
}
```

### Key Constraints
- `ThemeConfig` must be a Pydantic `BaseModel`
- `to_css_variables()` returns a string like `:root { --primary: #6366f1; ... }`
- Add ThemeConfig/ThemeRegistry at the END of `infographic.py` (after InfographicResponse)
- `theme_registry.get()` raises `KeyError` for unknown theme names (same as template registry)

---

## Acceptance Criteria

- [ ] `ThemeConfig` model validates correctly with defaults
- [ ] `ThemeRegistry` registers and retrieves themes
- [ ] Built-in themes `light`, `dark`, `corporate` are available
- [ ] `ThemeConfig.to_css_variables()` produces valid CSS `:root` block
- [ ] Custom theme registration works: `theme_registry.register(ThemeConfig(name="custom", ...))`
- [ ] Exports work: `from parrot.models.infographic import ThemeConfig, ThemeRegistry, theme_registry`
- [ ] `theme_registry.get("unknown")` raises `KeyError`

---

## Test Specification

```python
# tests/test_infographic_html.py (or inline verification)
import pytest
from parrot.models.infographic import ThemeConfig, ThemeRegistry, theme_registry


class TestThemeConfig:
    def test_defaults(self):
        theme = ThemeConfig(name="test")
        assert theme.primary == "#6366f1"
        assert theme.font_family.startswith("-apple-system")

    def test_to_css_variables(self):
        theme = ThemeConfig(name="test", primary="#ff0000")
        css = theme.to_css_variables()
        assert ":root" in css
        assert "--primary: #ff0000" in css

    def test_custom_values(self):
        theme = ThemeConfig(name="custom", primary="#000", neutral_text="#fff")
        assert theme.primary == "#000"
        assert theme.neutral_text == "#fff"


class TestThemeRegistry:
    def test_builtin_light(self):
        theme = theme_registry.get("light")
        assert theme.name == "light"
        assert theme.primary == "#6366f1"

    def test_builtin_dark(self):
        theme = theme_registry.get("dark")
        assert theme.name == "dark"

    def test_builtin_corporate(self):
        theme = theme_registry.get("corporate")
        assert theme.name == "corporate"

    def test_custom_registration(self):
        reg = ThemeRegistry()
        custom = ThemeConfig(name="brand", primary="#e11d48")
        reg.register(custom)
        assert reg.get("brand").primary == "#e11d48"

    def test_unknown_raises(self):
        with pytest.raises(KeyError):
            theme_registry.get("nonexistent")

    def test_list_themes(self):
        names = theme_registry.list_themes()
        assert "light" in names
        assert "dark" in names
        assert "corporate" in names
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/infographic-html-output.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm `InfographicResponse` is still at line 311
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-644-theme-system.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
