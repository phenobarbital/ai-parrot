---
type: Wiki Overview
title: 'TASK-1358: Move infographic, messaging, and utility renderers to satellite'
id: doc:sdd-tasks-completed-task-1358-move-infographic-messaging-utility-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.outputs.formats.base import BaseRenderer, RenderResult, RenderError
  # core'
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.base
  rel: mentions
- concept: mod:parrot.outputs.formats.infographic_html
  rel: mentions
---

# TASK-1358: Move infographic, messaging, and utility renderers to satellite

**Feature**: FEAT-200 — Extract outputs/formats to ai-parrot-visualizations
**Spec**: `sdd/proposals/ai-parrot-visualizations.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1355, TASK-1356
**Assigned-to**: unassigned

---

## Context

> Moves the remaining non-zero-dep renderers to the satellite: infographic
> renderers (active development area), messaging renderers (card, slack,
> whatsapp), utility renderers (jinja2, template_report, markdown,
> application), and the generators/ and mixins/ sub-packages.
> These are separated from TASK-1357 because infographic_html has recent
> activity (TASK-661/662/663/664) and messaging renderers have different
> dependency profiles.

---

## Scope

- Move these files from `packages/ai-parrot/src/parrot/outputs/formats/` to satellite:
  - `infographic.py`
  - `infographic_html.py`
  - `application.py`
  - `card.py`
  - `slack.py`
  - `whatsapp.py`
  - `jinja2.py`
  - `template_report.py`
  - `markdown.py`
- Move `generators/` sub-package (with `__init__.py`, `abstract.py`, `panel.py`, `streamlit.py`, `terminal.py`)
- Move `mixins/` sub-package (with `__init__.py`, `emaps.py`)
- Verify each renderer still auto-registers via `@register_renderer`
- Verify import paths unchanged

**NOT in scope**: Fixing direct imports of `InfographicHTMLRenderer` (TASK-1359), updating pyproject.toml deps (TASK-1360).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/formats/infographic.py` | DELETE (move) | → satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py` | DELETE (move) | → satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/application.py` | DELETE (move) | → satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/card.py` | DELETE (move) | → satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/slack.py` | DELETE (move) | → satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/whatsapp.py` | DELETE (move) | → satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/jinja2.py` | DELETE (move) | → satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/template_report.py` | DELETE (move) | → satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/markdown.py` | DELETE (move) | → satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/generators/` | DELETE (move) | Entire sub-package → satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/mixins/` | DELETE (move) | Entire sub-package → satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Renderers import base classes from core (stays in place):
from parrot.outputs.formats.base import BaseRenderer, RenderResult, RenderError  # core
from parrot.outputs.formats import register_renderer  # core __init__.py
from parrot.models.outputs import OutputMode  # core

# Direct imports that other files use (TASK-1359 will fix these):
# packages/ai-parrot/src/parrot/bots/abstract.py:3884
from ..outputs.formats.infographic_html import InfographicHTMLRenderer

# packages/ai-parrot/src/parrot/handlers/artifacts.py:514
from ..outputs.formats.infographic_html import InfographicHTMLRenderer

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py:36
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py:33
def get_renderer(mode: OutputMode) -> Type[Renderer]:
    # Lines 82-84: INFOGRAPHIC mode loads both infographic and infographic_html
    # elif mode == OutputMode.INFOGRAPHIC:
    #     import_module('.infographic', 'parrot.outputs.formats')
    #     import_module('.infographic_html', 'parrot.outputs.formats')
```

### Does NOT Exist
- ~~`generators/__init__.py` in satellite~~ — this task moves the existing one from core
- ~~`mixins/__init__.py` in satellite~~ — this task moves the existing one from core

---

## Implementation Notes

### Pattern to Follow
```bash
# Move individual files
git mv packages/ai-parrot/src/parrot/outputs/formats/infographic.py \
       packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py

# Move entire sub-packages
git mv packages/ai-parrot/src/parrot/outputs/formats/generators \
       packages/ai-parrot-visualizations/src/parrot/outputs/formats/generators
git mv packages/ai-parrot/src/parrot/outputs/formats/mixins \
       packages/ai-parrot-visualizations/src/parrot/outputs/formats/mixins
```

### Key Constraints
- **`generators/` and `mixins/` ARE regular packages** — they keep their `__init__.py` files (only namespace boundary levels omit `__init__.py`)
- **After this move, TASK-1359 MUST run** to fix the 3 direct `InfographicHTMLRenderer` imports — they will break if the satellite is not installed or if the import style is wrong
- **Relative imports** within generators/ (e.g., `from .abstract import ...`) should work within the sub-package since generators/ keeps its `__init__.py`
- **Cross-references between moved files**: if `infographic_html.py` imports from `chart.py` (moved in TASK-1357), the import via namespace merging handles it

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py` — the most actively developed renderer
- `packages/ai-parrot/src/parrot/outputs/formats/generators/__init__.py` — sub-package structure

---

## Acceptance Criteria

- [ ] All 9 renderer files moved to satellite
- [ ] `generators/` sub-package moved to satellite with `__init__.py` intact
- [ ] `mixins/` sub-package moved to satellite with `__init__.py` intact
- [ ] `from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer` works (with satellite installed)
- [ ] `get_renderer(OutputMode.INFOGRAPHIC)` returns the renderer class
- [ ] `get_renderer(OutputMode.JINJA2)` returns the renderer class
- [ ] `get_renderer(OutputMode.SLACK)` returns the renderer class
- [ ] `get_renderer(OutputMode.CARD)` returns the renderer class
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/`

---

## Test Specification

```python
import pytest
from parrot.models.outputs import OutputMode
from parrot.outputs.formats import get_renderer

@pytest.mark.parametrize("mode", [
    OutputMode.INFOGRAPHIC,
    OutputMode.JINJA2,
    OutputMode.TEMPLATE_REPORT,
    OutputMode.APPLICATION,
    OutputMode.CARD,
    OutputMode.WHATSAPP,
    OutputMode.SLACK,
])
def test_utility_renderer_resolves(mode):
    """Each moved renderer is still discoverable via get_renderer."""
    renderer_cls = get_renderer(mode)
    assert renderer_cls is not None
    assert hasattr(renderer_cls, 'render')

def test_infographic_html_importable():
    """InfographicHTMLRenderer is importable from its original path."""
    from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
    assert InfographicHTMLRenderer is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-1355 and TASK-1356 are complete**
2. **Read `infographic_html.py`** — it's the most complex renderer (active development)
3. **Move each file** using `git mv`
4. **Move sub-packages** (`generators/`, `mixins/`) as directories
5. **Test** that `get_renderer()` resolves each moved renderer
6. **Commit** with message: `sdd: move infographic/messaging/utility renderers to satellite (TASK-1358)`

---

## Completion Note

Implemented by sdd-worker on 2026-05-28.

Moved 9 renderer files + generators/ and mixins/ sub-packages via `git mv`:
- infographic.py, infographic_html.py, application.py, card.py, slack.py,
  whatsapp.py, jinja2.py, template_report.py, markdown.py
- generators/(__init__.py, abstract.py, panel.py, streamlit.py, terminal.py)
- mixins/(__init__.py, emaps.py)

All moved renderers resolve correctly via `get_renderer()` ✅:
- INFOGRAPHIC→InfographicRenderer, JINJA2→Jinja2Renderer,
  TEMPLATE_REPORT→TemplateReportRenderer, APPLICATION→ApplicationRenderer,
  CARD→CardRenderer, WHATSAPP→WhatsAppRenderer, SLACK→SlackRenderer,
  MARKDOWN→MarkdownRenderer
- `from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer` works ✅
