---
id: F004
intent: Catalog the existing example and SDK-only test
query_ids: [Q004, Q005]
---

# F004 — Existing example and SDK-only test

## Citations

### Existing example: `examples/google/structured_with_tools.py` (99 lines)

- Defines `WeatherReport` Pydantic schema and a `WeatherTool` (AbstractTool).
- Builds a single hardcoded client call with `model="gemini-2.0-flash"` and
  `enable_tools=True`, then calls
  `client.ask(prompt=..., structured_output=WeatherReport, use_tools=True)`.
- Print branches on `response.structured_output` / `response.tool_calls`.
- Has NO model parameterisation — must be modified to iterate the whitelist.

### SDK-only diagnostic: `examples/google/test_tool_structured_output.py` (85 lines)

- Bypasses `parrot.clients.google.GoogleGenAIClient` entirely and calls
  `genai.Client().models.generate_content(...)` directly with both
  `tools=[get_current_weather]` and `response_mime_type="application/json" +
  response_schema=WeatherResponse` in a single
  `GenerateContentConfig` (lines 34-43).
- Iterates over four model strings (lines 68-73):
  ```python
  models_to_test = [
      "gemini-2.5-pro",          # known to fail with 400
      "gemini-3.1-flash-lite",   # ⚠ NOTE: registry uses 'gemini-3.1-flash-lite-preview'
      "gemini-3.5-flash",        # ⚠ NOTE: NOT in GoogleModel enum (see F005)
      "gemini-3.1-pro-preview"
  ]
  ```
- This file is the **evidence base** for the user's claim that combined-mode
  is now SDK-accepted. It exits with `[EXITO]` when no 400 is raised.

## Notes

- The example needs to grow a `--model` CLI flag (or iterate the whitelist)
  to allow the user to exercise the combined-mode path against each model.
- The SDK-only test passes its tool as a plain Python function, while
  `parrot` builds `types.FunctionDeclaration` from AbstractTool / ToolDefinition
  (see F001 → `_build_tools` at client.py:773-851). The combined-mode SDK
  invocation should still work, but the tool wiring goes through the parrot
  declaration builder, not raw Python callables.
