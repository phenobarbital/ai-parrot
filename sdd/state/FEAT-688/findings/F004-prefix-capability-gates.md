---
id: F004
query_id: Q006
type: read
intent: "Map the SDK call surface and the model-capability gates an SDK/model bump could break"
executed_at: 2026-10-15T17:46:00Z
parent_id: F001
depth: 1
---

# F004 — Every capability decision is a `startswith("gemini-3…")` prefix test

## Summary

`client.py` routes behaviour by **string prefix**, never by enum membership.
Four independent gates decide thinking mode, combined tools+schema, computer
use and 3.x-ness, and each one hardcodes `gemini-2.5…` / `gemini-3…` prefixes.
A model id outside those prefixes is not rejected — it silently takes the
*conservative* branch: no combined call, so `ask()` pays the legacy two-phase
reformat round-trip. Adding a new family to the enum therefore changes nothing
about how it is driven; the prefixes are the real catalogue.

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 144-158
  symbol: `_default_combined_call_prefixes`
  excerpt: |
    _default_combined_call_prefixes: tuple[str, ...] = (
        "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.7-pro",
        "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
        "gemini-3.1-pro", "gemini-3.1-flash-lite",
    )

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 230-239
  symbol: `_is_gemini3_model`
  excerpt: |
    def _is_gemini3_model(model: str) -> bool:
        return model.startswith("gemini-3")

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 270-283
  symbol: `_requires_thinking`
  excerpt: |
    def _requires_thinking(model: str) -> bool:
        return (
            model.startswith("gemini-2.5-pro")
            or model.startswith("gemini-3.7-pro")
            or model.startswith("gemini-3.1-pro")
            or model.startswith("gemini-3-pro")

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 374-391
  symbol: `_is_computer_use_model`
  excerpt: |
    def _is_computer_use_model(model: str) -> bool:
        return model.startswith("gemini-2.5-computer-use") or model.startswith("gemini-3-flash-preview")

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 394-417
  symbol: `_supports_combined_tools_and_schema`
  excerpt: |
    def _supports_combined_tools_and_schema(model, prefixes) -> bool:
        """Returns True when the normalised model identifier starts with any
        prefix in ``prefixes``."""
        return any(model.startswith(p) for p in prefixes)

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 128-131, 166-172
  symbol: `_fallback_model`, `_lightweight_model`, `_default_reformat_model`
  excerpt: |
    _fallback_model: str = "gemini-3.1-flash-lite"
    _lightweight_model: str = "gemini-3.1-flash-lite"
    _default_reformat_model: str = GoogleModel.GEMINI_3_5_FLASH.value

## Notes

`_default_model`, `_fallback_model` and `_lightweight_model` are three more
hardcoded ids that pin the client to the 3.x generation independently of the
enum. `client.py:803` guards on a bare `startswith("gemini")`, which a 4.x id
would still satisfy.
