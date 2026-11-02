---
id: F022
query_id: Q042
type: grep
intent: "Model/effort tiering precedent (lightweight model, reasoning effort) for `tier` → model policy projection."
executed_at: 2026-10-30T16:46:28Z
duration_ms: 300
parent_id: null
depth: 0
merged_from: [FC-023-model-tier-precedent]
---

# F022 — Only a two-level precedent exists: `AbstractClient._lightweight_model` resolved by `_resolve_invoke_model` (explicit model > self.model > _lightweight_model > _default_model); no `tier`/`reasoning_effort` field on clients

## Summary

`clients/base.py` has `_lightweight_model: Optional[str] = None` (line 309) and the precedence docstring at ~1978/2058-2085. No `reasoning_effort`, `model_tier` or `effort` identifiers in base.py. A `tier: judgment|balanced|templated` → model/effort policy would be new; the only hook is per-call model selection in `invoke()`.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 309
  symbol: `AbstractClient._lightweight_model`
  excerpt: |
    _lightweight_model: Optional[str] = None

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 2058-2085
  symbol: `AbstractClient._resolve_invoke_model`
  excerpt: |
    :attr:`_lightweight_model` > ``_default_model``.
    ``self.model`` outranks :attr:`_lightweight_model` because
    if self._lightweight_model is not None: return self._lightweight_model

## Notes

`BotConfig.model: ModelConfig` (FC-006) is where a per-agent model policy is declared today; `clients/base.py` must not be modified without discussion (CONTEXT.md).
