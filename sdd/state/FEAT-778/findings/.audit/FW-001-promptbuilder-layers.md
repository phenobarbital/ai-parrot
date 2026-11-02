---
id: FW-001
query_id: Q001
type: wiki_page
intent: "PromptBuilder API outline: layers and identity semantics"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-001 — PromptBuilder is a name-keyed layer stack; `identity` is one replaceable layer (priority 10), not a slot that stacks

## Summary

`PromptBuilder` (builder.py:L35-362) holds `self._layers: Dict[str, PromptLayer]` keyed by `layer.name`, with `add()/remove()` mutations and a two-phase render (`configure()` for static vars, `build()` per request). `default()` composes IDENTITY, PRE_INSTRUCTIONS, SECURITY, KNOWLEDGE, USER_SESSION, TOOLS, OUTPUT_LANGUAGE, OUTPUT, BEHAVIOR layers; `minimal()` keeps identity+security+user_session. Because layers are keyed by name, a `persona.md` identity would REPLACE `IDENTITY_LAYER` (one slot) — there is no notion of stacking two identities; `LayerPriority.IDENTITY = 10`, `CUSTOM = 80` (layers.py:22-32) orders them. `configure()` destroys original templates (per FEAT-321 spec), so any per-activation swap must clone a pristine builder.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/prompts/builder.py`
  lines: 35-362
  symbol: `PromptBuilder`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/bots/prompts/builder.py#PromptBuilder
  score: 1.00
  excerpt: |
    class PromptBuilder:
        def __init__(self, layers: Optional[List[PromptLayer]] = None, *, prompt_caching: bool = False):
            self._layers: Dict[str, PromptLayer] = {}
        @classmethod
        def default(cls) -> PromptBuilder:
            return cls([IDENTITY_LAYER, PRE_INSTRUCTIONS_LAYER, SECURITY_LAYER, KNOWLEDGE_LAYER,
                        USER_SESSION_LAYER, TOOLS_LAYER, OUTPUT_LANGUAGE_LAYER, OUTPUT_LAYER, BEHAVIOR_LAYER])

- path: `packages/ai-parrot/src/parrot/bots/prompts/layers.py`
  lines: 22-35
  symbol: `LayerPriority`
  excerpt: |
    class LayerPriority(IntEnum):
        IDENTITY = 10
        CUSTOM = 80
    class RenderPhase(str, Enum):

- path: `packages/ai-parrot/src/parrot/bots/prompts/layers.py`
  lines: 152
  symbol: `IDENTITY_LAYER`
  excerpt: |
    IDENTITY_LAYER = PromptLayer(

## Notes

Answers the source's open question "¿persona.md sustituye o se apila?": the builder model is replace-by-name; stacking two inline experts in one turn would need a second layer name (e.g. `expert_identity`) at a distinct priority. KNOWLEDGE_LAYER already exists in the default stack as the natural slot for a resolved KnowledgeContext.
[cross-lane: type=read, intent=confirm KNOWLEDGE_LAYER template variables ($knowledge_content) in layers.py]
