---
id: F004
query: Q005, Q014
type: read
target: packages/ai-parrot/src/parrot/bots/prompts/layers.py, builder.py
---

# F004 — PromptBuilder and KNOWLEDGE_LAYER Verification

**Status**: Confirmed exactly

## LayerPriority(IntEnum)
```
IDENTITY=10, PRE_INSTRUCTIONS=15, SECURITY=20, KNOWLEDGE=30,
USER_SESSION=40, TOOLS=50, OUTPUT=60, BEHAVIOR=70, CUSTOM=80
```

## KNOWLEDGE_LAYER
```python
KNOWLEDGE_LAYER = PromptLayer(
    name="knowledge",
    priority=LayerPriority.KNOWLEDGE,  # 30
    phase=RenderPhase.REQUEST,
    template="<knowledge_context>\n$knowledge_content\n</knowledge_context>",
    condition=lambda ctx: bool(ctx.get("knowledge_content", "").strip()),
)
```
Skipped entirely when `knowledge_content` is empty.

## PromptLayer (frozen dataclass)
Fields: name, priority, template, phase, condition, required_vars, cacheable

## PromptBuilder
- `default()` factory includes all 8 standard layers
- Two-phase: `configure(context)` for CONFIGURE-phase, `build(context) -> str` for REQUEST-phase
- `build_segments(context) -> List[CacheableSegment]` for prompt caching (FEAT-181)
- Knowledge injection: caller passes `{"knowledge_content": "<text>"}` in context dict
- Mutation API: `add()`, `remove()`, `replace()`, `get()`, `clone()`
