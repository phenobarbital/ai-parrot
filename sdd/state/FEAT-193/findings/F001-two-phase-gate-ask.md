---
id: F001
intent: Locate the current two-phase tool-calling + structured-output flow in GoogleGenAIClient.ask()
query_ids: [Q001]
---

# F001 — Two-phase gate in `ask()`

The two-phase flow is gated by an explicit `if/else` branch.

## Citations

- `packages/ai-parrot/src/parrot/clients/google/client.py:109-115` — class-level
  comment + `_default_reformat_model`:

  > # Default model used to reformat tool-using responses into structured
  > # output (Gemini cannot combine tools + response_schema in one call).
  > # Override per-instance via the ``reformat_model`` constructor kwarg.
  > _default_reformat_model: str = GoogleModel.GEMINI_3_FLASH_PREVIEW.value

- `packages/ai-parrot/src/parrot/clients/google/client.py:2033-2048` — the gate
  itself (inside `ask()`):

  ```python
  use_structured_output = bool(output_config)
  if _use_tools and use_structured_output:
      self.logger.info(
          "Google Gemini doesn't support tools + structured output simultaneously. "
          "Using tools first, then applying structured output to the final result."
      )
      structured_output_for_later = output_config
      output_config = None              # ← schema deliberately stripped
  else:
      structured_output_for_later = None
      if output_config:
          self._apply_structured_output_schema(generation_config, output_config)
  ```

- `packages/ai-parrot/src/parrot/clients/google/client.py:2337-2474` — the
  deferred SECOND call: after the tool-calling chat completes,
  `structured_output_for_later` triggers a fast-path JSON-detect + fallback
  reformat call to `self._reformat_model` (a separate, fast model, default
  `GEMINI_3_FLASH_PREVIEW`). Adds 1 extra LLM round-trip per tool-using call.

## Notes

- The gate is the **single hook point** to introduce simultaneous-mode for
  whitelisted models. Replace the unconditional fork with a capability check
  (e.g., `supports_combined_tools_and_schema(model)`).
- The reformat model is `_reformat_model` (line 115), separately configurable.
  If combined mode is used, this code path is skipped — the schema lands in
  the SAME chat call's `GenerateContentConfig`.
