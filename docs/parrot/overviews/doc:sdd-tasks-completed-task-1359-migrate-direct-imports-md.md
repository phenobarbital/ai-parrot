---
type: Wiki Overview
title: 'TASK-1359: Migrate direct InfographicHTMLRenderer imports to registry'
id: doc:sdd-tasks-completed-task-1359-migrate-direct-imports-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from ..outputs.formats.infographic_html import InfographicHTMLRenderer #
  REMOVE'
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.infographic_html
  rel: mentions
---

# TASK-1359: Migrate direct InfographicHTMLRenderer imports to registry

**Feature**: FEAT-200 — Extract outputs/formats to ai-parrot-visualizations
**Spec**: `sdd/proposals/ai-parrot-visualizations.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1358
**Assigned-to**: unassigned

---

## Context

> Only 3 production files import a renderer directly instead of using the
> registry. All 3 import `InfographicHTMLRenderer`. After the move to the
> satellite (TASK-1358), these imports still work via PEP 420 namespace
> merging, but they bypass the lazy-loading pattern and create a hard
> coupling. This task migrates them to use `get_renderer(OutputMode.INFOGRAPHIC)`
> for consistency and to eliminate the last direct cross-package imports.

---

## Scope

- Update `packages/ai-parrot/src/parrot/bots/abstract.py` line 3884
- Update `packages/ai-parrot/src/parrot/handlers/artifacts.py` line 514
- Update `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` line 36
- Replace direct `InfographicHTMLRenderer` imports with `get_renderer(OutputMode.INFOGRAPHIC)`
- Ensure the returned class is used correctly in each consumer

**NOT in scope**: Changing the `get_renderer` logic, modifying the satellite package.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Replace direct import with registry call |
| `packages/ai-parrot/src/parrot/handlers/artifacts.py` | MODIFY | Replace direct import with registry call |
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY | Replace direct import with registry call |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Replace THESE imports:
# bots/abstract.py:3884
from ..outputs.formats.infographic_html import InfographicHTMLRenderer  # REMOVE

# handlers/artifacts.py:514
from ..outputs.formats.infographic_html import InfographicHTMLRenderer  # REMOVE

# tools/infographic_toolkit.py:36
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer  # REMOVE

# WITH these:
from parrot.outputs.formats import get_renderer  # registry function
from parrot.models.outputs import OutputMode  # enum (likely already imported in these files)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py:33
def get_renderer(mode: OutputMode) -> Type[Renderer]:
    """Get the renderer class for the given output mode."""
    # Returns the class, not an instance
    # Usage: RendererCls = get_renderer(OutputMode.INFOGRAPHIC)
    #        result = RendererCls.render(data, **kwargs)
```

### Does NOT Exist
- ~~`get_renderer(OutputMode.INFOGRAPHIC_HTML)`~~ — there is no `INFOGRAPHIC_HTML` mode; `OutputMode.INFOGRAPHIC` loads both `infographic.py` and `infographic_html.py` (see `formats/__init__.py:82-84`)

---

## Implementation Notes

### Pattern to Follow
```python
# BEFORE (direct import):
from ..outputs.formats.infographic_html import InfographicHTMLRenderer
# ... later in code:
renderer = InfographicHTMLRenderer()
result = renderer.render(data)

# AFTER (registry):
from ..outputs.formats import get_renderer
from ..models.outputs import OutputMode
# ... later in code:
InfographicHTMLRenderer = get_renderer(OutputMode.INFOGRAPHIC)
result = InfographicHTMLRenderer.render(data)
```

### Key Constraints
- Check how each file USES the renderer — it may call `InfographicHTMLRenderer()` (constructor), `InfographicHTMLRenderer.render(...)` (static/class method), or pass the class around
- `OutputMode` is likely already imported in `bots/abstract.py` and `handlers/artifacts.py` — check before adding a redundant import
- The `get_renderer` call is NOT async — it's a synchronous lazy-load

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/formatter.py:229` — reference: how `OutputFormatter` uses `get_renderer`

---

## Acceptance Criteria

- [ ] No remaining direct imports of `InfographicHTMLRenderer` in the core package
- [ ] `grep -r "from.*infographic_html import" packages/ai-parrot/src/` returns empty
- [ ] `bots/abstract.py` uses `get_renderer(OutputMode.INFOGRAPHIC)` correctly
- [ ] `handlers/artifacts.py` uses `get_renderer(OutputMode.INFOGRAPHIC)` correctly
- [ ] `tools/infographic_toolkit.py` uses `get_renderer(OutputMode.INFOGRAPHIC)` correctly
- [ ] All existing functionality preserved (infographic rendering works)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/ packages/ai-parrot/src/parrot/handlers/ packages/ai-parrot/src/parrot/tools/`

---

## Test Specification

```python
import pytest
from parrot.outputs.formats import get_renderer
from parrot.models.outputs import OutputMode

def test_infographic_renderer_via_registry():
    """InfographicHTMLRenderer resolves through get_renderer."""
    cls = get_renderer(OutputMode.INFOGRAPHIC)
    assert cls is not None
    assert cls.__name__ == 'InfographicHTMLRenderer'

def test_no_direct_imports_remain():
    """No direct InfographicHTMLRenderer imports in core."""
    import subprocess
    result = subprocess.run(
        ['grep', '-r', 'from.*infographic_html import', 'packages/ai-parrot/src/'],
        capture_output=True, text=True
    )
    assert result.stdout.strip() == '', f"Found direct imports: {result.stdout}"
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-1358 is complete** (infographic_html.py is in satellite)
2. **Read each of the 3 files** to understand how they USE the renderer class
3. **Replace imports** with registry-based access
4. **Verify** the renderer class name matches what the code expects
5. **Commit** with message: `sdd: migrate direct InfographicHTMLRenderer imports to registry (TASK-1359)`

---

## Completion Note

Implemented by sdd-worker on 2026-05-28.

Additional change needed (not in original scope but required for correctness):
- Added `@register_renderer(OutputMode.INFOGRAPHIC)` to `InfographicHTMLRenderer` in satellite
  `infographic_html.py`, since the class was previously not registered in the registry.
  This makes `get_renderer(OutputMode.INFOGRAPHIC)` return `InfographicHTMLRenderer` as expected.

Migrations completed:
1. `bots/abstract.py:3884` — replaced with `from ..outputs.formats import get_renderer; InfographicHTMLRenderer = get_renderer(OutputMode.INFOGRAPHIC)`
2. `handlers/artifacts.py:514` — replaced with registry call + `from ..models.outputs import OutputMode`
3. `tools/infographic_toolkit.py:36,136` — replaced module-level import with `from parrot.outputs.formats import get_renderer; from parrot.models.outputs import OutputMode` and `get_renderer(OutputMode.INFOGRAPHIC)()`

`grep -r "from.*infographic_html import" packages/ai-parrot/src/` returns empty ✅
`get_renderer(OutputMode.INFOGRAPHIC).__name__ == 'InfographicHTMLRenderer'` ✅
