# TASK-649: Infographic Helpers Façade

**Feature**: get-infographic-handler
**Spec**: `sdd/specs/get-infographic-handler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-094 exposed `infographic_registry` (templates) and `theme_registry`
(themes) as module-level singletons inside model files. SDK consumers and
the upcoming `InfographicTalk` handler should not reach into
`parrot.models.infographic_templates` / `parrot.models.infographic` just to
list or register entries. This task introduces a small, stable helper
module that wraps those registries with function-level APIs, plus a minimal
extension (`ThemeRegistry.list_themes_detailed`) to mirror the existing
`InfographicTemplateRegistry.list_templates_detailed` method.

Implements **Module 1** of the spec.

---

## Scope

- Create the package `packages/ai-parrot/src/parrot/helpers/` with an empty
  `__init__.py` (the package does not exist yet — verified 2026-04-10).
- Create `packages/ai-parrot/src/parrot/helpers/infographics.py` exporting:
    - `list_templates(detailed: bool = False) -> list[str] | list[dict]`
    - `get_template(name: str) -> InfographicTemplate`
    - `register_template(template: InfographicTemplate | dict) -> InfographicTemplate`
    - `list_themes(detailed: bool = False) -> list[str] | list[dict]`
    - `get_theme(name: str) -> ThemeConfig`
    - `register_theme(theme: ThemeConfig | dict) -> ThemeConfig`
- Add `list_themes_detailed(self) -> List[Dict[str, str]]` to
  `ThemeRegistry` in `packages/ai-parrot/src/parrot/models/infographic.py`.
  Return a list of dicts with `name` and the key colour tokens
  (`primary`, `neutral_bg`, `body_bg`).
- Each `register_*` helper must accept either a validated Pydantic instance
  or a raw dict. Dicts MUST be validated via `model_validate` and surface
  Pydantic `ValidationError` to the caller (do not swallow).
- Write unit tests in
  `packages/ai-parrot/tests/helpers/test_infographics_helpers.py`
  (create the directory if needed, plus a `conftest.py` if required for
  pytest discovery).
- Do NOT re-export helpers from `parrot/__init__.py`; callers use the
  fully-qualified path `from parrot.helpers.infographics import ...`.

**NOT in scope**:
- The `InfographicTalk` HTTP handler (TASK-650).
- Route registration (TASK-651).
- Any deletion or `unregister_*` API.
- PBAC / authentication — helpers are sync pure Python.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/helpers/__init__.py` | CREATE | Empty package marker |
| `packages/ai-parrot/src/parrot/helpers/infographics.py` | CREATE | Façade module with six helper functions |
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | Add `ThemeRegistry.list_themes_detailed` method |
| `packages/ai-parrot/tests/helpers/__init__.py` | CREATE (if missing) | Test package marker |
| `packages/ai-parrot/tests/helpers/test_infographics_helpers.py` | CREATE | Unit tests for the six helpers + `list_themes_detailed` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From inside the new helpers/infographics.py
from parrot.models.infographic_templates import (
    InfographicTemplate, infographic_registry,
)  # verified: packages/ai-parrot/src/parrot/models/infographic_templates.py:47,382
from parrot.models.infographic import (
    ThemeConfig, theme_registry,
)  # verified: packages/ai-parrot/src/parrot/models/infographic.py:339,434
from pydantic import ValidationError  # standard pydantic import
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/infographic_templates.py:310
class InfographicTemplateRegistry:
    def __init__(self) -> None: ...                                 # line 316
    def register(self, template: InfographicTemplate) -> None: ...  # line 332
    def get(self, name: str) -> InfographicTemplate: ...            # line 340
    def list_templates(self) -> List[str]: ...                      # line 361
    def list_templates_detailed(self) -> List[Dict[str, str]]: ...  # line 369

infographic_registry = InfographicTemplateRegistry()                # line 382

# packages/ai-parrot/src/parrot/models/infographic_templates.py:47
class InfographicTemplate(BaseModel):
    name: str                                                       # line 49
    description: str                                                # line 50
    block_specs: List[BlockSpec]                                    # line 51
    default_theme: Optional[str] = None                             # line 55
    def to_prompt_instruction(self) -> str: ...                     # line 60

# packages/ai-parrot/src/parrot/models/infographic.py:387
class ThemeRegistry:
    def __init__(self) -> None: ...                                 # line 394
    def register(self, theme: ThemeConfig) -> None: ...             # line 397
    def get(self, name: str) -> ThemeConfig: ...                    # line 405
    def list_themes(self) -> List[str]: ...                         # line 424
    # list_themes_detailed does NOT yet exist — this task adds it.

theme_registry = ThemeRegistry()                                    # line 434
# Built-ins already registered at lines 438 (light), 453 (dark), 468 (corporate)

# packages/ai-parrot/src/parrot/models/infographic.py:339
class ThemeConfig(BaseModel):
    name: str
    primary: str = "#6366f1"
    primary_dark: str = "#4f46e5"
    primary_light: str = "#818cf8"
    accent_green: str = "#10b981"
    accent_amber: str = "#f59e0b"
    accent_red: str = "#ef4444"
    neutral_bg: str = "#f8fafc"
    neutral_border: str = "#e2e8f0"
    neutral_muted: str = "#64748b"
    neutral_text: str = "#0f172a"
    body_bg: str = "#f1f5f9"
    font_family: str = ...
    def to_css_variables(self) -> str: ...                          # line 364
```

### Does NOT Exist
- ~~`parrot.helpers`~~ — package does not exist; this task creates it.
- ~~`parrot.helpers.infographics`~~ — module does not exist yet.
- ~~`ThemeRegistry.list_themes_detailed`~~ — this task adds it.
- ~~`InfographicTemplateRegistry.unregister`~~ — no deletion API; do not add.
- ~~`ThemeRegistry.unregister`~~ — no deletion API; do not add.
- ~~`parrot.helpers.__all__`~~ — do not populate an `__all__` list (the
  `__init__.py` stays empty); callers use full import path.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/helpers/infographics.py
"""Helper façade for the infographic template and theme registries.

Wraps parrot.models.infographic_templates.infographic_registry and
parrot.models.infographic.theme_registry so SDK consumers don't need
to import registry singletons directly.
"""
from __future__ import annotations
from typing import List, Union, Dict

from parrot.models.infographic_templates import (
    InfographicTemplate, infographic_registry,
)
from parrot.models.infographic import ThemeConfig, theme_registry


def list_templates(detailed: bool = False) -> Union[List[str], List[Dict[str, str]]]:
    """List available infographic template names.

    Args:
        detailed: When True, return list of dicts with name + description.

    Returns:
        Sorted list of names, or sorted list of detailed dicts.
    """
    if detailed:
        return infographic_registry.list_templates_detailed()
    return infographic_registry.list_templates()


def get_template(name: str) -> InfographicTemplate:
    """Retrieve a template by name (raises KeyError if not found)."""
    return infographic_registry.get(name)


def register_template(
    template: Union[InfographicTemplate, dict],
) -> InfographicTemplate:
    """Register a custom template.

    Accepts either an InfographicTemplate instance or a raw dict that
    will be validated via InfographicTemplate.model_validate. Returns
    the validated template instance.

    Raises:
        pydantic.ValidationError: If the dict payload is malformed.
    """
    if isinstance(template, dict):
        template = InfographicTemplate.model_validate(template)
    infographic_registry.register(template)
    return template


# Mirror pattern for theme helpers.
```

### `ThemeRegistry.list_themes_detailed` Extension

Add inside `packages/ai-parrot/src/parrot/models/infographic.py` after
`list_themes`:

```python
def list_themes_detailed(self) -> List[Dict[str, str]]:
    """Return theme summaries with key colour tokens.

    Returns:
        List of dicts containing name, primary, neutral_bg, body_bg,
        sorted by name.
    """
    return [
        {
            "name": t.name,
            "primary": t.primary,
            "neutral_bg": t.neutral_bg,
            "body_bg": t.body_bg,
        }
        for t in sorted(self._themes.values(), key=lambda x: x.name)
    ]
```

### Key Constraints

- Pure synchronous functions — no async, no I/O, no HTTP concerns.
- Do NOT catch `ValidationError` — let it bubble up so the handler layer
  can convert it to HTTP 400.
- Do NOT catch `KeyError` from `registry.get` — same reasoning.
- Helpers mutate process-wide singletons; do NOT copy or clone the registries.
- Keep `__init__.py` empty — no re-exports.
- Tests must not rely on import ordering side effects; use fresh theme /
  template instances (`name="test_xxx"`) and clean them out of the registry
  via a pytest fixture with `yield`+teardown if registration tests cross
  modules.

### References in Codebase

- `packages/ai-parrot/src/parrot/models/infographic_templates.py:310-382`
  — existing template registry with the exact pattern this façade wraps.
- `packages/ai-parrot/src/parrot/models/infographic.py:387-434`
  — existing theme registry; `list_themes_detailed` follows the shape of
  `list_templates_detailed`.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/helpers/__init__.py` exists and is empty
- [ ] `from parrot.helpers.infographics import list_templates, get_template, register_template, list_themes, get_theme, register_theme` succeeds
- [ ] `list_templates()` returns the built-in names
  (`["basic", "comparison", "dashboard", "executive", "minimal", "timeline_report"]`
  sorted alphabetically — verify actual names from the registry)
- [ ] `list_templates(detailed=True)` returns dicts with `name` and `description`
- [ ] `list_themes()` returns `["corporate", "dark", "light"]`
- [ ] `list_themes(detailed=True)` returns dicts with `name`, `primary`,
      `neutral_bg`, `body_bg`
- [ ] `register_template({...valid dict...})` validates and registers; a
      subsequent `get_template(name)` returns the same instance
- [ ] `register_template({"name": "x"})` raises `pydantic.ValidationError`
- [ ] `get_template("nonexistent")` raises `KeyError` with available list
- [ ] `ThemeRegistry.list_themes_detailed()` method exists and returns the
      built-in three themes
- [ ] All unit tests pass:
      `pytest packages/ai-parrot/tests/helpers/test_infographics_helpers.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/helpers/`
- [ ] No breaking changes to `infographic_registry` or `theme_registry`

---

## Test Specification

```python
# packages/ai-parrot/tests/helpers/test_infographics_helpers.py
import pytest
from pydantic import ValidationError

from parrot.helpers.infographics import (
    list_templates, get_template, register_template,
    list_themes, get_theme, register_theme,
)
from parrot.models.infographic_templates import (
    InfographicTemplate, infographic_registry,
)
from parrot.models.infographic import ThemeConfig, theme_registry


@pytest.fixture
def cleanup_registries():
    """Remove test-registered templates/themes after each test."""
    yield
    for name in list(infographic_registry._templates.keys()):
        if name.startswith("test_"):
            del infographic_registry._templates[name]
    for name in list(theme_registry._themes.keys()):
        if name.startswith("test_"):
            del theme_registry._themes[name]


class TestListTemplates:
    def test_returns_sorted_names(self):
        names = list_templates()
        assert isinstance(names, list)
        assert names == sorted(names)
        assert "basic" in names

    def test_detailed_returns_dicts(self):
        detailed = list_templates(detailed=True)
        assert all("name" in d and "description" in d for d in detailed)


class TestGetTemplate:
    def test_known_template(self):
        tpl = get_template("basic")
        assert isinstance(tpl, InfographicTemplate)
        assert tpl.name == "basic"

    def test_unknown_raises_keyerror(self):
        with pytest.raises(KeyError, match="not found"):
            get_template("does_not_exist")


class TestRegisterTemplate:
    def test_accepts_model_instance(self, cleanup_registries):
        tpl = InfographicTemplate(
            name="test_custom",
            description="Test template",
            block_specs=[],
        )
        out = register_template(tpl)
        assert out is tpl
        assert get_template("test_custom") is tpl

    def test_accepts_dict(self, cleanup_registries):
        out = register_template({
            "name": "test_custom_dict",
            "description": "From dict",
            "block_specs": [],
        })
        assert isinstance(out, InfographicTemplate)
        assert out.name == "test_custom_dict"

    def test_invalid_dict_raises_validation_error(self):
        with pytest.raises(ValidationError):
            register_template({"name": "test_bad"})  # missing description + block_specs


class TestListThemes:
    def test_returns_builtins(self):
        names = list_themes()
        assert set(["light", "dark", "corporate"]).issubset(set(names))

    def test_detailed_shape(self):
        detailed = list_themes(detailed=True)
        for entry in detailed:
            assert set(entry.keys()) == {"name", "primary", "neutral_bg", "body_bg"}


class TestThemeRegistryListDetailed:
    def test_method_exists_on_registry(self):
        assert hasattr(theme_registry, "list_themes_detailed")
        detailed = theme_registry.list_themes_detailed()
        assert isinstance(detailed, list)
        assert all("name" in d for d in detailed)


class TestRegisterTheme:
    def test_accepts_model(self, cleanup_registries):
        theme = ThemeConfig(name="test_sunset", primary="#ff6b35")
        out = register_theme(theme)
        assert out is theme
        assert get_theme("test_sunset") is theme

    def test_accepts_dict(self, cleanup_registries):
        out = register_theme({"name": "test_dict_theme"})
        assert isinstance(out, ThemeConfig)
        assert out.name == "test_dict_theme"
        assert out.primary == "#6366f1"  # default


class TestGetTheme:
    def test_known(self):
        t = get_theme("light")
        assert isinstance(t, ThemeConfig)

    def test_unknown_raises(self):
        with pytest.raises(KeyError):
            get_theme("no_such_theme")
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec at `sdd/specs/get-infographic-handler.spec.md` for full context.
2. Verify the Codebase Contract: confirm `infographic_registry`,
   `theme_registry`, `InfographicTemplate`, and `ThemeConfig` exist at the
   listed line numbers. If files have changed, update the contract first.
3. Confirm `packages/ai-parrot/src/parrot/helpers/` does not yet exist —
   `ls` the directory; if it somehow exists, reconcile before creating.
4. Update status in `sdd/tasks/.index.json` → `"in-progress"`.
5. Implement Module 1 per the scope above.
6. Run `pytest packages/ai-parrot/tests/helpers/test_infographics_helpers.py -v`
   after activating `.venv`.
7. Verify all acceptance criteria.
8. Move this file to `sdd/tasks/completed/TASK-649-helpers-facade.md` and
   update the index → `"done"`.
9. Fill in the Completion Note below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-10
**Notes**: All 16 tests pass. Template name is "timeline" (not "timeline_report") — test corrected. conftest.py added to tests/helpers/ to resolve worktree sys.path isolation issue.

**Deviations from spec**: Minor — test used actual template name "timeline" instead of "timeline_report" per spec text; the registry uses "timeline".
