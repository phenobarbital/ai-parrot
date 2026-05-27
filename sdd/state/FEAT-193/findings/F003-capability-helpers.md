---
id: F003
intent: Identify existing model-capability gating helpers to follow the established pattern
query_ids: [Q006, Q008]
---

# F003 — Existing model-capability gating helpers

The codebase already uses static helper methods on `GoogleGenAIClient` to
gate features by model family. New capability check should follow the same
pattern.

## Citations

- `packages/ai-parrot/src/parrot/clients/google/client.py:156-204`:

  ```python
  @staticmethod
  def _is_gemini3_model(model: str) -> bool:
      """Check if a model belongs to the Gemini 3.x family."""
      model = GoogleGenAIClient._as_model_str(model)
      if not model:
          return False
      return model.startswith('gemini-3')

  @staticmethod
  def _is_preview_model(model: str) -> bool:
      """Check if a model is a preview variant."""
      model = GoogleGenAIClient._as_model_str(model)
      if not model:
          return False
      return 'preview' in model

  @staticmethod
  def _requires_thinking(model: str) -> bool:
      """Gemini 2.5 Pro and Gemini 3.x Pro models are thinking-only..."""
      model = GoogleGenAIClient._as_model_str(model)
      if not model:
          return False
      return (
          model.startswith('gemini-2.5-pro')
          or model.startswith('gemini-3.1-pro')
          or model.startswith('gemini-3-pro')
      )

  @staticmethod
  def _as_model_str(model) -> str:
      """Normalize a model identifier to a plain string. Accepts GoogleModel enum or string."""
      ...
  ```

## Notes

- Pattern: `@staticmethod` returning `bool`, normalising input via
  `_as_model_str`, using `.startswith(...)` checks for family-level matches.
- The new helper should follow this pattern. Suggested name:
  `_supports_combined_tools_and_schema(model: str) -> bool` (or shorter
  `_supports_combined_call`).
- Source whitelist from user analysis:
  - `gemini-3.1-pro-preview` → matches `startswith('gemini-3.1-pro')`
  - `gemini-3.1-flash-lite-preview` → matches `startswith('gemini-3.1-flash-lite')`
  - `gemini-3.5-flash` → would need a new prefix check (see F005 caveat)
- `gemini-2.5-pro` is explicitly excluded (per the upstream evaluation: API
  400 error when combining tools + response_mime_type).
