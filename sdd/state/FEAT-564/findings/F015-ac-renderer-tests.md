---
id: F015
query_id: Q014
type: read
intent: Existing Adaptive Card renderer tests
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F015 — test_renderers.py — AC coverage baseline

## Summary
Baseline tests for `AdaptiveCardRenderer` live in `packages/parrot-formdesigner/tests/unit/test_renderers.py`: registry dispatch (L357), `TestAdaptiveCardRenderer.test_renders_adaptive_card` (L391-393), fallback-type warnings (L472-490), TASK-2337 native/fallback posture (L787, L809). No test asserts the Submit action payload shape or any endpoint reference.

## Citations
- path: `packages/parrot-formdesigner/tests/unit/test_renderers.py`
  lines: 357-361
  symbol: `test_adaptive_card_registry_dispatch_existing_types`
- path: `packages/parrot-formdesigner/tests/unit/test_renderers.py`
  lines: 391-393
  symbol: `TestAdaptiveCardRenderer.test_renders_adaptive_card`
- path: `packages/parrot-formdesigner/tests/unit/test_renderers.py`
  lines: 472-490
  symbol: `test_adaptive_card_fallback_types_emit_warnings`
- path: `packages/parrot-formdesigner/tests/unit/test_renderers.py`
  lines: 787-823
  symbol: `test_adaptive_card_task2337_native_types_no_warning`, `test_adaptive_card_task2337_fallback_types_emit_warnings`
