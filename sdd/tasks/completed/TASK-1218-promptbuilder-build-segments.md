# TASK-1218: PromptBuilder.build_segments() method

**Feature**: FEAT-181 — Provider-Agnostic Prompt Caching
**Spec**: `sdd/specs/agnostic-prompt-caching-abstraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1217
**Assigned-to**: unassigned

---

## Context

This task adds the `build_segments()` method to `PromptBuilder` (spec Module 2,
§3). It also adds the `prompt_caching: bool = False` constructor kwarg. When
prompt caching is enabled, `build_segments()` returns a list of
`CacheableSegment` objects partitioned by `layer.cacheable`. The existing
`build()` method MUST remain unchanged — zero behavior difference for existing
callers.

---

## Scope

- Add `prompt_caching: bool = False` kwarg to `PromptBuilder.__init__()`.
- Implement `build_segments(context: Dict[str, Any]) -> List[CacheableSegment]`:
  sort layers by priority, render each, create a `CacheableSegment` per
  non-empty rendered layer using `layer.cacheable`.
- Ensure `build()` output is byte-identical pre- and post-change for all
  existing presets (`default`, `minimal`, `voice`, `agent`, `rag`).
- Export `build_segments` via `__init__.py` (already exports `PromptBuilder`).
- Write unit tests.

**NOT in scope**: AgentContextLoader (TASK-1219), AbstractBot integration
(TASK-1220), client translators (TASK-1222–1224).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/builder.py` | MODIFY | Add `prompt_caching` kwarg + `build_segments()` |
| `packages/ai-parrot/tests/test_prompt_caching_builder.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.segments import CacheableSegment  # segments.py (TASK-1217)
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase  # layers.py:22-47
from parrot.bots.prompts.builder import PromptBuilder  # builder.py:20
```

### Existing Signatures to Use
```python
# parrot/bots/prompts/builder.py
class PromptBuilder:                     # line 20
    def __init__(self, layers: Optional[List[PromptLayer]] = None):  # line 35
        self._layers: Dict[str, PromptLayer] = {}                    # line 36
        self._configured: bool = False                               # line 37

    def configure(self, context: Dict[str, Any]) -> None: ...  # line 184
    def build(self, context: Dict[str, Any]) -> str: ...       # line 204

    # build() implementation (lines 221-231):
    #   sorted_layers = sorted(self._layers.values(), key=lambda l: l.priority)
    #   parts: List[str] = []
    #   for layer in sorted_layers:
    #       rendered = layer.render(context)
    #       if rendered is not None:
    #           stripped = rendered.strip()
    #           if stripped:
    #               parts.append(stripped)
    #   return "\n\n".join(parts)

    @classmethod
    def default(cls) -> PromptBuilder: ...     # line 44
    @classmethod
    def minimal(cls) -> PromptBuilder: ...     # line 58
    @classmethod
    def voice(cls) -> PromptBuilder: ...       # line 65
    @classmethod
    def agent(cls) -> PromptBuilder: ...       # line 90
    @classmethod
    def rag(cls) -> PromptBuilder: ...         # line 98
```

### Does NOT Exist
- ~~`PromptBuilder.build_segments()`~~ — does not exist yet; this task creates it
- ~~`PromptBuilder.__init__(prompt_caching=...)`~~ — no such kwarg yet; this task adds it
- ~~`PromptBuilder.segments`~~ — no such attribute

---

## Implementation Notes

### Pattern to Follow

`build_segments()` mirrors the iteration in `build()` (lines 221-231) but
produces `CacheableSegment` objects instead of joining strings:

```python
def build_segments(self, context: Dict[str, Any]) -> List[CacheableSegment]:
    sorted_layers = sorted(self._layers.values(), key=lambda l: l.priority)
    segments: List[CacheableSegment] = []
    for layer in sorted_layers:
        rendered = layer.render(context)
        if rendered is not None:
            stripped = rendered.strip()
            if stripped:
                segments.append(CacheableSegment(
                    text=stripped,
                    cacheable=layer.cacheable,
                ))
    return segments
```

### Key Constraints
- `build()` MUST NOT change behavior. Do not modify it.
- `build_segments()` should work regardless of `prompt_caching` flag value —
  the flag is informational for the constructor; `build_segments()` always
  produces segments. The flag is consumed by `AbstractBot` (TASK-1220) to
  decide whether to call `build()` or `build_segments()`.
- All 5 factory methods (`default`, `minimal`, `voice`, `agent`, `rag`) must
  still produce identical `build()` output after this change.

### References in Codebase
- `parrot/bots/prompts/builder.py` — target file
- `parrot/bots/prompts/segments.py` — `CacheableSegment` (from TASK-1217)

---

## Acceptance Criteria

- [ ] `PromptBuilder(prompt_caching=True)` creates successfully
- [ ] `PromptBuilder(prompt_caching=False)` creates successfully (default)
- [ ] `build_segments()` returns `List[CacheableSegment]` with correct partitioning
- [ ] CONFIGURE-phase layers produce `cacheable=True` segments
- [ ] REQUEST-phase layers produce `cacheable=False` segments
- [ ] `build()` output is byte-identical for all 5 presets (regression guard)
- [ ] Empty layers are excluded from segments (same as `build()`)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_prompt_caching_builder.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/prompts/`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_prompt_caching_builder.py
import pytest
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
from parrot.bots.prompts.segments import CacheableSegment


class TestBuildSegments:
    def test_basic_segmentation(self):
        builder = PromptBuilder([
            PromptLayer(name="a", priority=10, template="static",
                        phase=RenderPhase.CONFIGURE),
            PromptLayer(name="b", priority=20, template="$dynamic",
                        phase=RenderPhase.REQUEST),
        ], prompt_caching=True)
        builder.configure({})
        segments = builder.build_segments({"dynamic": "data"})
        assert len(segments) == 2
        assert segments[0].cacheable is True
        assert segments[1].cacheable is False

    def test_empty_layers_excluded(self):
        builder = PromptBuilder([
            PromptLayer(name="a", priority=10, template="text",
                        phase=RenderPhase.CONFIGURE),
            PromptLayer(name="b", priority=20, template="$missing",
                        phase=RenderPhase.REQUEST),
        ], prompt_caching=True)
        builder.configure({})
        segments = builder.build_segments({})
        # "b" renders as "$missing" which is non-empty (safe_substitute keeps placeholder)
        assert len(segments) >= 1

    def test_condition_skips_layer(self):
        builder = PromptBuilder([
            PromptLayer(name="a", priority=10, template="always",
                        phase=RenderPhase.CONFIGURE),
            PromptLayer(name="b", priority=20, template="never",
                        phase=RenderPhase.CONFIGURE,
                        condition=lambda ctx: False),
        ], prompt_caching=True)
        builder.configure({})
        segments = builder.build_segments({})
        assert len(segments) == 1
        assert segments[0].text == "always"


class TestBuildRegression:
    """Ensure build() is unchanged for all presets."""

    @pytest.mark.parametrize("preset", ["default", "minimal", "agent", "rag"])
    def test_preset_build_unchanged(self, preset):
        factory = getattr(PromptBuilder, preset)
        builder_old = factory()
        builder_new = factory()
        ctx = {
            "name": "Test", "role": "helper", "goal": "help",
            "backstory": "", "rationale": "be nice",
            "knowledge_content": "kb data",
            "user_context": "user", "chat_history": "history",
            "output_instructions": "", "has_tools": False,
        }
        builder_old.configure(ctx)
        builder_new.configure(ctx)
        assert builder_old.build(ctx) == builder_new.build(ctx)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1217 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `PromptBuilder.__init__` is at line 35
   and `build()` is at line 204 with the iteration pattern at lines 221-231
4. **Update status** in `sdd/tasks/index/agnostic-prompt-caching-abstraction.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1218-promptbuilder-build-segments.md`
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
**Notes**: Added prompt_caching kwarg to __init__, build_segments() method that mirrors build() but returns List[CacheableSegment], clone() propagation. All 17 tests pass. build() is unchanged — regression verified.
**Deviations from spec**: none
