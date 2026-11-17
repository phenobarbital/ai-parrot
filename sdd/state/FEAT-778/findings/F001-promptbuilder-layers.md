---
id: F001
query_id: Q020
type: read
intent: "Read PromptBuilder: layer names, ordering, identity layer and whether layers can be replaced per call."
executed_at: 2026-10-30T16:41:41Z
duration_ms: 1200
parent_id: null
depth: 0
merged_from: [FC-001-promptbuilder-layers]
---

# F001 — PromptBuilder is a name-keyed dict of PromptLayer rendered by priority; `identity` is a replaceable slot

## Summary

`PromptBuilder` (362 lines) keeps layers in `self._layers: Dict[str, PromptLayer]` keyed by `layer.name`; `build()` sorts by `layer.priority` and joins non-empty renders. The default stack is IDENTITY, PRE_INSTRUCTIONS, SECURITY, KNOWLEDGE, USER_SESSION, TOOLS, (OUTPUT_LANGUAGE), OUTPUT, BEHAVIOR. `add()` adds-or-replaces by name, `replace()` requires the name to exist, `clone()` deep-copies. `from_system_prompt()` already implements "replace the identity slot with external text" — the exact mechanism a persona.md injection would reuse. Two render phases exist (CONFIGURE static vs REQUEST dynamic). Nothing per-layer tracks a source revision or a token budget.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/prompts/builder.py`
  lines: 35-62
  symbol: `PromptBuilder.__init__`
  excerpt: |
    class PromptBuilder:
        def __init__(self, layers: Optional[List[PromptLayer]] = None, *, prompt_caching: bool = False):
            self._layers: Dict[str, PromptLayer] = {}
            self._configured: bool = False
            if layers:
                for layer in layers:
                    self._layers[layer.name] = layer

- path: `packages/ai-parrot/src/parrot/bots/prompts/builder.py`
  lines: 66-92
  symbol: `PromptBuilder.default`
  excerpt: |
    IDENTITY_LAYER, PRE_INSTRUCTIONS_LAYER, SECURITY_LAYER, KNOWLEDGE_LAYER,
    USER_SESSION_LAYER, TOOLS_LAYER, OUTPUT_LANGUAGE_LAYER, OUTPUT_LAYER, BEHAVIOR_LAYER

- path: `packages/ai-parrot/src/parrot/bots/prompts/builder.py`
  lines: 168-198
  symbol: `PromptBuilder.from_system_prompt`
  excerpt: |
    """Default stack with the identity layer replaced by system_prompt. ..."""
    builder = cls.default()
    builder.add(PromptLayer(name="identity", priority=LayerPriority.IDENTITY,
                            phase=RenderPhase.CONFIGURE, template=system_prompt))

- path: `packages/ai-parrot/src/parrot/bots/prompts/builder.py`
  lines: 200-240
  symbol: `PromptBuilder.add / remove / replace`
  excerpt: |
    def add(self, layer: PromptLayer) -> PromptBuilder:   # "Add or replace a layer by name."
    def remove(self, name: str) -> PromptBuilder:
    def replace(self, name: str, layer: PromptLayer) -> PromptBuilder:
        if name not in self._layers: raise KeyError(...)

- path: `packages/ai-parrot/src/parrot/bots/prompts/builder.py`
  lines: 288-312
  symbol: `PromptBuilder.build`
  excerpt: |
    sorted_layers = sorted(self._layers.values(), key=lambda layer: layer.priority)
    for layer in sorted_layers:
        rendered = layer.render(context) ...
    return "\n\n".join(parts)

## Notes

Identity is a single named slot: two inline experts in one turn cannot both occupy it without a new composition rule. `KNOWLEDGE_LAYER` is the natural slot for a rendered KnowledgeContext.
