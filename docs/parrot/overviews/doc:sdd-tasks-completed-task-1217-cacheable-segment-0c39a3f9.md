---
type: Wiki Overview
title: 'TASK-1217: CacheableSegment dataclass + PromptLayer.cacheable attribute'
id: doc:sdd-tasks-completed-task-1217-cacheable-segment-and-layer-cacheable-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundational data-model task for FEAT-181. Every other task depends
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
- concept: mod:parrot.bots.prompts.segments
  rel: mentions
---

# TASK-1217: CacheableSegment dataclass + PromptLayer.cacheable attribute

**Feature**: FEAT-181 — Provider-Agnostic Prompt Caching
**Spec**: `sdd/specs/agnostic-prompt-caching-abstraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational data-model task for FEAT-181. Every other task depends
on `CacheableSegment` and/or the `cacheable` attribute on `PromptLayer`. The
spec (Module 1, §3) defines a new frozen dataclass representing one chunk of
the system prompt with a cache-eligibility flag, and extends `PromptLayer` with
a `cacheable: bool` field whose default derives from `phase`.

---

## Scope

- Create `parrot/bots/prompts/segments.py` with the `CacheableSegment` frozen dataclass.
- Add `cacheable: bool` field to the existing `PromptLayer` frozen dataclass in
  `parrot/bots/prompts/layers.py`, with default `True` when
  `phase == RenderPhase.CONFIGURE`, `False` when `phase == RenderPhase.REQUEST`.
- Update `partial_render()` to propagate the `cacheable` field when creating
  the new `PromptLayer` instance (line 103-110).
- Export `CacheableSegment` from `parrot/bots/prompts/__init__.py`.
- Write unit tests.

**NOT in scope**: `build_segments()` method (TASK-1218), AgentContextLoader
(TASK-1219), client translators (TASK-1222–1224).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/segments.py` | CREATE | `CacheableSegment` frozen dataclass |
| `packages/ai-parrot/src/parrot/bots/prompts/layers.py` | MODIFY | Add `cacheable: bool` field to `PromptLayer`; update `partial_render()` |
| `packages/ai-parrot/src/parrot/bots/prompts/__init__.py` | MODIFY | Export `CacheableSegment` |
| `packages/ai-parrot/tests/test_prompt_caching_segments.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase  # layers.py:22-47
from parrot.bots.prompts.builder import PromptBuilder  # builder.py:20
from parrot.bots.prompts import PromptBuilder, PromptLayer, RenderPhase  # __init__.py:15-29
```

### Existing Signatures to Use
```python
# parrot/bots/prompts/layers.py
class RenderPhase(str, Enum):           # line 35
    CONFIGURE = "configure"             # line 46
    REQUEST = "request"                 # line 47

@dataclass(frozen=True)
class PromptLayer:                       # line 51 (frozen=True at line 50)
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST  # line 65
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None  # line 66
    required_vars: frozenset[str] = field(default_factory=frozenset)  # line 67
    def render(self, context: Dict[str, Any]) -> Optional[str]: ...   # line 69
    def partial_render(self, context: Dict[str, Any]) -> PromptLayer: ...  # line 83

# partial_render creates a new PromptLayer at lines 103-110:
#   return PromptLayer(
#       name=self.name,
#       priority=self.priority,
#       template=partially_resolved,
#       phase=RenderPhase.REQUEST,
#       condition=None,
#       required_vars=frozenset(),
#   )
```

### Does NOT Exist
- ~~`PromptLayer.cacheable`~~ — does not exist yet; this task creates it
- ~~`parrot.bots.prompts.segments`~~ — module does not exist yet; this task creates it
- ~~`CacheableSegment`~~ — does not exist anywhere in the codebase

---

## Implementation Notes

### Pattern to Follow

`PromptLayer` is a frozen dataclass. Adding `cacheable` follows the same pattern
as existing fields. Use `field(default=...)` with a factory or a `__post_init__`
to derive the default from `phase`. Since frozen dataclasses don't allow
`__post_init__` to set attributes directly, use one of:

**Option A** (recommended): Use `field(default=None)` and a `__post_init__` with
`object.__setattr__` to derive the value:
```python
cacheable: Optional[bool] = field(default=None)

def __post_init__(self):
    if self.cacheable is None:
        object.__setattr__(self, 'cacheable', self.phase == RenderPhase.CONFIGURE)
```

**Option B**: Make `cacheable` required and set it explicitly on all 8 built-in
layer instances. Simpler but more verbose.

For `CacheableSegment`:
```python
@dataclass(frozen=True)
class CacheableSegment:
    text: str
    cacheable: bool
    ttl_hint: Optional[Literal['short', 'long']] = None
```

### Key Constraints
- `PromptLayer` is `frozen=True` — use `object.__setattr__` in `__post_init__` if needed.
- `partial_render()` at line 103 must propagate `cacheable` to the new instance.
- All 8 built-in layer instances (IDENTITY, PRE_INSTRUCTIONS, SECURITY,
  KNOWLEDGE, USER_SESSION, TOOLS, OUTPUT, BEHAVIOR) must continue to work
  unchanged — their `cacheable` value derives automatically from `phase`.
- Do NOT change the `build()` method or break any existing PromptBuilder caller.

### References in Codebase
- `parrot/bots/prompts/layers.py` — existing `PromptLayer` definition
- `parrot/bots/prompts/domain_layers.py` — domain-specific layers (also frozen)
- `parrot/bots/prompts/__init__.py` — export surface

---

## Acceptance Criteria

- [ ] `CacheableSegment(text="x", cacheable=True)` creates successfully
- [ ] `CacheableSegment.ttl_hint` defaults to `None`
- [ ] CONFIGURE-phase layers have `cacheable=True` by default
- [ ] REQUEST-phase layers have `cacheable=False` by default
- [ ] Explicit `cacheable=False` on a CONFIGURE-phase layer overrides the default
- [ ] `partial_render()` propagates `cacheable` to the returned layer
- [ ] All existing built-in layers (8) still render correctly
- [ ] `from parrot.bots.prompts import CacheableSegment` works
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_prompt_caching_segments.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/prompts/`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_prompt_caching_segments.py
import pytest
from parrot.bots.prompts.segments import CacheableSegment
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase


class TestCacheableSegment:
    def test_creation(self):
        seg = CacheableSegment(text="hello", cacheable=True)
        assert seg.text == "hello"
        assert seg.cacheable is True
        assert seg.ttl_hint is None

    def test_ttl_hint(self):
        seg = CacheableSegment(text="x", cacheable=True, ttl_hint="long")
        assert seg.ttl_hint == "long"

    def test_frozen(self):
        seg = CacheableSegment(text="x", cacheable=True)
        with pytest.raises(AttributeError):
            seg.text = "y"


class TestPromptLayerCacheable:
    def test_configure_phase_default_cacheable_true(self):
        layer = PromptLayer(
            name="test", priority=10, template="$x",
            phase=RenderPhase.CONFIGURE,
        )
        assert layer.cacheable is True

    def test_request_phase_default_cacheable_false(self):
        layer = PromptLayer(
            name="test", priority=10, template="$x",
            phase=RenderPhase.REQUEST,
        )
        assert layer.cacheable is False

    def test_explicit_override(self):
        layer = PromptLayer(
            name="test", priority=10, template="$x",
            phase=RenderPhase.CONFIGURE, cacheable=False,
        )
        assert layer.cacheable is False

    def test_partial_render_propagates_cacheable(self):
        layer = PromptLayer(
            name="test", priority=10, template="$x $y",
            phase=RenderPhase.CONFIGURE, cacheable=True,
        )
        rendered = layer.partial_render({"x": "hello"})
        assert rendered.cacheable is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `PromptLayer` is still at line 51
   with the listed fields, and `partial_render()` still creates a new instance
   at lines 103-110
4. **Update status** in `sdd/tasks/index/agnostic-prompt-caching-abstraction.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1217-cacheable-segment-and-layer-cacheable.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any

---

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-18
**Notes**: Created segments.py with frozen CacheableSegment dataclass. Added cacheable field to PromptLayer using __post_init__ with object.__setattr__ to derive default from phase. partial_render() propagates cacheable. All 15 tests pass.
**Deviations from spec**: none
