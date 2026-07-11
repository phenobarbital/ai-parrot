---
id: F010
slug: response-models
query: Deep dive into AIMessage, InvokeResult, CompletionUsage, AIMessageFactory
type: read
---

## Finding: Response Data Models

### AIMessage (`parrot/models/responses.py:72`)
Pydantic BaseModel. Key fields: `input`, `output` (Any), `response`, `model`, `provider`, `usage` (CompletionUsage), `stop_reason`, `finish_reason`, `tool_calls` (List[ToolCall]), `structured_output`, `is_structured`, `metadata`, `artifacts`, `output_mode`.

### InvokeResult (`parrot/models/responses.py:1282`)
Pydantic BaseModel. Fields: `output` (Any), `output_type`, `model`, `usage` (CompletionUsage), `raw_response`.
Constructed by `AbstractClient._build_invoke_result()` (base.py:1731).

### CompletionUsage (`parrot/models/basic.py:48`)
Pydantic BaseModel with dual naming (prompt_tokens/input_tokens, completion_tokens/output_tokens).
Factory classmethods: `from_openai()`, `from_groq()`, `from_claude()`, `from_gemini()`, `from_claude_agent()`, `from_grok()`.
**No `from_bedrock()` exists.** Bedrock Converse returns `inputTokens`/`outputTokens` (camelCase) + optional `cacheReadInputTokens`/`cacheWriteInputTokens`.

### ToolCall (`parrot/models/basic.py:23`)
Pydantic BaseModel. Fields: `id`, `name`, `arguments` (Dict), `result`, `error`, `execution_time`.

### AIMessageFactory (`parrot/models/responses.py:389`)
Static-method factory. Methods: `from_completion()`, `from_openai()`, `from_groq()`, `from_grok()`, `from_claude()`, `from_claude_agent()`, `from_gemini()`, `create_message()`, `from_imagen()`, `from_speech()`, `from_video()`.
**No `from_bedrock()` exists.**

### What BedrockClient needs:
1. `CompletionUsage.from_bedrock(usage_dict)` — map `inputTokens`/`outputTokens` + cache token fields
2. `AIMessageFactory.from_bedrock(response, ...)` — extract text from `response['output']['message']['content']`, map `stopReason`, convert `toolUse` blocks to ToolCall
3. `InvokeResult` — use existing `_build_invoke_result()` base class helper
