---
id: F001
query_id: Q001
type: grep
intent: Detect whether a PromptBuilder (or equivalent helper) already exists.
executed_at: 2026-05-18T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F001 — PromptBuilder already exists with layers + presets + two-phase render

## Summary

A fully-featured `PromptBuilder` class **already exists** at
`parrot/bots/prompts/builder.py:20`. It manages a collection of `PromptLayer`
instances, orchestrates a two-phase render (CONFIGURE = static vars resolved
once, REQUEST = dynamic vars resolved per call), and exposes factory presets
(`default`, `minimal`, `voice`, `agent`, `rag`). It is consumed by
`AbstractBot.__init__(prompt_builder=...)` (legacy `system_prompt_template`
remains as fallback). The public output is a single rendered string from
`build(context) -> str`. There is NO concept of cache markers, segments, or
provider hints in the current API. Spec reference noted inside the file
points to `sdd/specs/composable-prompt-layer.spec.md`.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/prompts/builder.py`
  lines: 20-241
  symbol: `PromptBuilder`
  excerpt: |
    class PromptBuilder:
        """Composable system prompt builder.

        Usage:
            builder = PromptBuilder.default()
            ...
            prompt = builder.build({"knowledge_content": "...", ...})
        """
        def __init__(self, layers: Optional[List[PromptLayer]] = None):
            self._layers: Dict[str, PromptLayer] = {}
            self._configured: bool = False

- path: `packages/ai-parrot/src/parrot/bots/prompts/builder.py`
  lines: 204-231
  symbol: `PromptBuilder.build`
  excerpt: |
    def build(self, context: Dict[str, Any]) -> str:
        """Phase 2: Resolve REQUEST-phase variables and assemble final prompt."""
        sorted_layers = sorted(self._layers.values(), key=lambda l: l.priority)
        parts: List[str] = []
        for layer in sorted_layers:
            rendered = layer.render(context)
            if rendered is not None:
                stripped = rendered.strip()
                if stripped:
                    parts.append(stripped)
        return "\n\n".join(parts)

- path: `packages/ai-parrot/src/parrot/bots/prompts/builder.py`
  lines: 42-112
  symbol: factory presets
  excerpt: |
    @classmethod
    def default(cls) -> PromptBuilder: ...
    @classmethod
    def minimal(cls) -> PromptBuilder: ...
    @classmethod
    def voice(cls) -> PromptBuilder: ...
    @classmethod
    def agent(cls) -> PromptBuilder: ...
    @classmethod
    def rag(cls) -> PromptBuilder: ...

- path: `packages/ai-parrot/src/parrot/bots/prompts/__init__.py`
  lines: 28-49
  symbol: re-exports + deprecation notes
  excerpt: |
    from .builder import PromptBuilder
    # ── Legacy: prompt templates (deprecated — use PromptBuilder instead) ──
    # Deprecated: use PromptBuilder.default() instead

- path: `packages/ai-parrot/src/parrot/bots/prompts/presets.py`
  lines: 15-34
  symbol: `_PRESETS` + `register_preset` / `get_preset`
  excerpt: |
    _PRESETS: Dict[str, Callable[[], PromptBuilder]] = {
        "default": PromptBuilder.default,
        "minimal": PromptBuilder.minimal,
        ...
    }

## Notes

The two-phase design (CONFIGURE once / REQUEST per call) is a near-perfect
fit for prompt caching: the CONFIGURE-resolved layers are stable across
calls (matches a cache prefix), while REQUEST layers are volatile (must
sit AFTER the cache boundary). This boundary is already encoded in the
layer's `phase` attribute and naturally maps to "cacheable" vs
"non-cacheable" content.
