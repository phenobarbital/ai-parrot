---
id: F001
query_id: Q001
type: read
intent: Understand the Google computer-use-preview reference implementation architecture
executed_at: 2026-06-05T00:00:00Z
duration_ms: 3000
parent_id: null
depth: 0
---

# F001 — Google computer-use-preview reference implementation

## Summary

The reference repo (google-gemini/computer-use-preview) implements a BrowserAgent class
that uses `types.ComputerUse(environment=types.Environment.ENVIRONMENT_BROWSER)` as a
special tool type in the Gemini API. The agent loop sends user queries, receives function
calls from the model, dispatches them to a Computer abstraction (Playwright or Browserbase),
and returns screenshots + URLs as FunctionResponse with inline PNG blobs. Coordinates use
a normalized 0-1000 range denormalized to actual viewport size.

## Citations

- path: `agent.py` (reference repo)
  lines: 38-50
  symbol: `PREDEFINED_COMPUTER_USE_FUNCTIONS`
  excerpt: |
    PREDEFINED_COMPUTER_USE_FUNCTIONS = [
        "open_web_browser", "click_at", "hover_at", "type_text_at",
        "scroll_document", "scroll_at", "wait_5_seconds", "go_back",
        "go_forward", "search", "navigate", "key_combination", "drag_and_drop",
    ]

- path: `agent.py` (reference repo)
  lines: 97-113
  symbol: `_generate_content_config`
  excerpt: |
    self._generate_content_config = GenerateContentConfig(
        temperature=1, top_p=0.95, top_k=40, max_output_tokens=8192,
        tools=[
            types.Tool(computer_use=types.ComputerUse(
                environment=types.Environment.ENVIRONMENT_BROWSER,
                excluded_predefined_functions=excluded_predefined_functions,
            )),
            types.Tool(function_declarations=custom_functions),
        ],
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    )

- path: `agent.py` (reference repo)
  lines: 205-222
  symbol: `run_one_iteration` (FunctionResponse construction)
  excerpt: |
    FunctionResponse(
        name=function_call.name,
        response={"url": fc_result.url, **extra_fr_fields},
        parts=[types.FunctionResponsePart(
            inline_data=types.FunctionResponseBlob(
                mime_type="image/png", data=fc_result.screenshot
            )
        )],
    )

- path: `computers/computer.py` (reference repo)
  lines: 1-100
  symbol: `Computer` (abstract), `EnvState`
  excerpt: |
    class EnvState(pydantic.BaseModel):
        screenshot: bytes  # PNG format
        url: str
    
    class Computer(abc.ABC):
        def screen_size(self) -> tuple[int, int]: ...
        def click_at(self, x: int, y: int) -> EnvState: ...
        def type_text_at(self, x, y, text, press_enter, clear_before_typing) -> EnvState: ...
        # 13 abstract methods total

## Notes

- Supported models: `gemini-2.5-computer-use-preview-10-2025`, `gemini-3-flash-preview`
- Safety decision handling: model can return `safety_decision: {decision: "require_confirmation"}`
- Screenshot memory management: only keeps screenshots from last 3 turns
- Reference Playwright impl uses sync_api (not async) — AI-Parrot will need async adaptation
- Custom functions can be added alongside ComputerUse tools (e.g., multiply_numbers example)
