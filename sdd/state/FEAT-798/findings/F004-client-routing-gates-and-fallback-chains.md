---
id: F004
query_id: Q013
type: grep
intent: "Routing gates in the Google client: prefix whitelists (_requires_thinking, _default_combined_call_prefixes, _is_gemini3_model, computer-use) and any hardcoded gemini-2.5 default model."
executed_at: 2026-11-04T01:39:51Z
duration_ms: 700
parent_id: null
depth: 0
---

# F004 — Class default is already gemini-flash-latest; 2.5 survives only in the thinking gate, computer-use gate and 7 secondary fallbacks

## Summary

`GoogleGenAIClient._default_model` is `GEMINI_FLASH_LATEST` (line 130) with `_fallback_model`/`_lightweight_model = "gemini-3.1-flash-lite"` and `_default_reformat_model = GEMINI_3_5_FLASH` (171). The combined tools+schema whitelist (151-160) already leads with `gemini-4-argon` and contains no 2.5 prefix. Remaining 2.5 touch-points are: `_requires_thinking` (303-314) gating on `"gemini-2.5-pro"`; `_is_computer_use_model` (420) gating on `"gemini-2.5-computer-use"`; the generation predicate at 243 (`startswith(("gemini-3","gemini-4"))`) which treats 2.5 as legacy; the `_model_class_key` at 470 (gemini4 vs gemini3); and seven `GoogleModel.GEMINI_2_5_FLASH.value` fallbacks (F002). Docstrings at 110-117, 164, 569, 1819, 1857, 3507 still describe 2.5-pro behaviour.

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 128-133
  symbol: `GoogleGenAIClient._default_model`
  excerpt: |
    models: type[Enum] = GoogleModel
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value
    _fallback_model: str = "gemini-3.1-flash-lite"
    _model_garden: bool = False
    _lightweight_model: str = "gemini-3.1-flash-lite"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 151-160
  symbol: `GoogleGenAIClient._default_combined_call_prefixes`
  excerpt: |
    _default_combined_call_prefixes: tuple[str, ...] = (
        "gemini-4-argon",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-pro",
        "gemini-3.1-flash-lite",
    )

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 171-171
  symbol: `GoogleGenAIClient._default_reformat_model`
  excerpt: |
    _default_reformat_model: str = GoogleModel.GEMINI_3_5_FLASH.value

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 243-243
  symbol: (generation predicate, renamed from `_is_gemini3_model`)
  excerpt: |
    return model.startswith(("gemini-3", "gemini-4"))

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 303-314
  symbol: `GoogleGenAIClient._requires_thinking`
  excerpt: |
    def _requires_thinking(model: str) -> bool:
        """Check if a model only works in thinking mode (budget > 0).
        Gemini 2.5 Pro, Gemini 3.x Pro, and computer-use models are
        thinking-only and reject budget=0.
        """
        ...
        return model.startswith(
            ("gemini-2.5-pro", "gemini-3.1-pro", "gemini-3-pro")
        ) or GoogleGenAIClient._is_computer_use_model(model)

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 403-420
  symbol: `GoogleGenAIClient._is_computer_use_model`
  excerpt: |
    return model.startswith(("gemini-2.5-computer-use", "gemini-3-flash-preview"))

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 470-470
  symbol: `GoogleGenAIClient._model_class_key`
  excerpt: |
    generation = "gemini4" if GoogleGenAIClient._as_model_str(model).startswith("gemini-4") else "gemini3"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 110-117
  symbol: (class docstring)
  excerpt: |
    Only Gemini-2.5-pro works well with multi-turn function calling.
    ...
    For all other models (e.g. ``gemini-2.5-pro``), the legacy two-phase flow is preserved.

## Notes

- Gates are prefix-based, so leaving `"gemini-2.5-pro"` in `_requires_thinking` after deleting the enum member is harmless at runtime but misleading; FEAT-688 precedent removed dead prefixes together with the member.
- `GEMINI_COMPUTER_USE` (2.5 computer-use preview) is wired into `_is_computer_use_model` and `_requires_thinking`; the computer-use agent in `parrot_tools` defaults to `gemini-3.8-flash` (F014), so the 2.5 id is likely a legacy path.
