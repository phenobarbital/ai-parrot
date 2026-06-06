---
id: F004
query_id: Q004
type: read
intent: Understand Google client tool handling and computer-use readiness
executed_at: 2026-06-05T00:00:00Z
duration_ms: 2000
parent_id: null
depth: 0
---

# F004 — Google client tool handling and model support

## Summary

GoogleGenAIClient wraps the google-genai SDK. Tool definitions are built via
`_build_tools()` which creates `types.Tool(function_declarations=[...])`. The client
supports combined tools+schema for whitelisted model prefixes (gemini-3.1-pro,
gemini-3.5-flash, gemini-3.1-flash-lite). There is NO existing `types.ComputerUse`
support — the client only handles FunctionDeclaration-based tools. Adding ComputerUse
requires extending `_build_tools()` to emit `types.Tool(computer_use=...)` alongside
regular function declarations.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 959-1037
  symbol: `_build_tools()`
  excerpt: |
    # Creates types.Tool(function_declarations=[...]) from AbstractTool instances
    # Two categories: "custom_functions" and "builtin_tools" (GoogleSearch)
    # Does NOT handle types.ComputerUse currently

- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 96-137
  symbol: `GoogleGenAIClient`
  excerpt: |
    _default_model = GoogleModel.GEMINI_FLASH_LATEST.value
    _fallback_model = 'gemini-3.1-flash-lite-preview'

- path: `packages/ai-parrot/src/parrot/models/google.py`
  lines: 9-37
  symbol: `GoogleModel` enum
  excerpt: |
    # Does NOT include computer-use models currently
    # Has: gemini-flash-latest, gemini-3.1-pro-preview, gemini-3.5-flash,
    # gemini-2.5-pro, gemini-2.5-flash, etc.

- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 1108-1150
  symbol: `_process_tool_result_for_api()`
  excerpt: |
    # Coerces non-string dict keys for Gemini compatibility
    # Does NOT handle FunctionResponseBlob (screenshot bytes) currently

## Notes

- Computer-Use requires `types.Tool(computer_use=types.ComputerUse(...))` — a new tool type
- FunctionResponse for computer-use actions returns screenshots as FunctionResponseBlob
- The google-genai SDK types (ComputerUse, Environment, FunctionResponsePart, FunctionResponseBlob) 
  may need an SDK version check — the reference repo uses the latest SDK
- ThinkingConfig(include_thoughts=True) is required for computer-use models
- GoogleGenAIClient already has `_requires_thinking()` helper for model detection
