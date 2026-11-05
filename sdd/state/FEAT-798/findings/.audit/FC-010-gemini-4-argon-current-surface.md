---
id: FC-010
query_id: Q019
type: grep
intent: "Current Gemini 4 / Argon surface: enum members, prefix gates, tests and pricing rows that already know about 4.x (what the 2.5 retirement can point to)."
executed_at: 2026-11-04T01:42:07Z
duration_ms: 600
parent_id: null
depth: 0
---

# FC-010 — Argon is wired end-to-end (enum, combined-call whitelist, generation predicate, model-class key, 3 test files) but has no pricing row and is nobody's default

## Summary

`gemini-4-argon` exists as `GoogleModel.GEMINI_4_ARGON` (models.py:19), leads `_default_combined_call_prefixes` (client.py:152), passes the `gemini-3|gemini-4` generation predicate (243) and gets its own `_model_class_key` bucket `gemini4_*` (470). Tests cover it in `test_google_models.py:56-59`, `test_llm_factory.py:118-121` (published as active), and `test_google_client.py:364,404,420-426` (combined call whitelisted, not thinking-only, accepts budget 0). No src file uses it as a default, and the pricing table (FC-011b) has no `gemini-4-*` row. No other 4.x id (no "4-flash"/"4-lite") exists anywhere in packages/.

## Citations

- path: `packages/ai-parrot/tests/test_google_models.py`
  lines: 56-59
  symbol: `test_google_model_enum_has_gemini_4_argon`
  excerpt: |
    def test_google_model_enum_has_gemini_4_argon():
        """GEMINI_4_ARGON is registered and reachable by value (FEAT-688)."""
        assert GoogleModel.GEMINI_4_ARGON.value == "gemini-4-argon"
        assert GoogleModel("gemini-4-argon") is GoogleModel.GEMINI_4_ARGON

- path: `packages/ai-parrot/tests/test_llm_factory.py`
  lines: 118-121
  symbol: `test_list_models_google_includes_argon`
  excerpt: |
    def test_list_models_google_includes_argon():
        """The Gemini 4 Argon id is published as an active Google model."""
        assert "gemini-4-argon" in models["active"]

- path: `packages/ai-parrot/tests/test_google_client.py`
  lines: 404-404, 420-426
  symbol: `test_argon_is_not_thinking_only` (and neighbours)
  excerpt: |
    @pytest.mark.parametrize("model", ["gemini-3.5-flash", "gemini-3.1-pro-preview", "gemini-4-argon"])
    ...
    assert client._model_class_key("gemini-4-argon").startswith("gemini4_")
    def test_argon_is_not_thinking_only(self):
        assert GoogleGenAIClient._requires_thinking("gemini-4-argon") is False
        assert GoogleGenAIClient._rejects_zero_thinking_budget("gemini-4-argon") is False

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 152-152, 243-243, 470-470
  symbol: `_default_combined_call_prefixes` / generation predicate / `_model_class_key`
  excerpt: |
    "gemini-4-argon",
    return model.startswith(("gemini-3", "gemini-4"))
    generation = "gemini4" if GoogleGenAIClient._as_model_str(model).startswith("gemini-4") else "gemini3"

## Notes

- The 3.x "flash" tier (`gemini-3.5-flash`, `gemini-3.7-flash`, `gemini-3.8-flash`) is what the already-migrated bots chose (FC-006); Argon is the only "pro-class" 4.x id, so the natural mapping is 2.5-pro → gemini-4-argon, 2.5-flash → a 3.x flash (or `gemini-flash-latest`).
