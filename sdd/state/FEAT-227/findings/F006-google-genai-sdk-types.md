---
id: F006
query_id: Q006
type: read
intent: Catalog the Gemini SDK types required for computer-use integration
executed_at: 2026-06-05T00:00:00Z
duration_ms: 1000
parent_id: null
depth: 0
---

# F006 — Google GenAI SDK types for computer-use

## Summary

The reference implementation imports these key types from the google-genai SDK:
`types.ComputerUse`, `types.Environment.ENVIRONMENT_BROWSER`, `types.FunctionResponsePart`,
`types.FunctionResponseBlob`, `types.ThinkingConfig`. The ComputerUse tool type is
configured alongside regular FunctionDeclaration tools in the same GenerateContentConfig.
The model returns standard FunctionCall objects for the predefined actions (click_at,
navigate, etc.) — the same format as regular function calls.

## Citations

- path: `agent.py` (reference repo)
  lines: 97-113
  symbol: GenerateContentConfig setup
  excerpt: |
    tools=[
        types.Tool(computer_use=types.ComputerUse(
            environment=types.Environment.ENVIRONMENT_BROWSER,
            excluded_predefined_functions=[],
        )),
        types.Tool(function_declarations=custom_functions),
    ],
    thinking_config=types.ThinkingConfig(include_thoughts=True)

- path: `agent.py` (reference repo)
  lines: 205-222
  symbol: FunctionResponse with screenshot
  excerpt: |
    FunctionResponse(
        name=function_call.name,
        response={"url": fc_result.url},
        parts=[types.FunctionResponsePart(
            inline_data=types.FunctionResponseBlob(
                mime_type="image/png", data=fc_result.screenshot
            )
        )],
    )

## Notes

- ComputerUse is a distinct tool type from FunctionDeclaration — both can coexist
- FunctionResponseBlob carries screenshot bytes inline — NOT a URL or file reference
- The model's predefined functions (click_at, etc.) are NOT declared as FunctionDeclarations —
  they are implicit from the ComputerUse tool type
- excluded_predefined_functions allows disabling specific actions (e.g., no drag_and_drop)
- Coordinate system: 0-1000 normalized, denormalized to viewport size
