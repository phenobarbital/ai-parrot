# F004 — Model API speaks three wire protocols; capability access differs

**Source**: `dev.meta.ai/docs/protocols.md` + per-capability pages

| Format | Endpoint | Reasoning across turns |
|---|---|---|
| Responses | `POST /v1/responses` | Yes (encrypted replay / `previous_response_id`) |
| Chat Completions | `POST /v1/chat/completions` | **No** |
| Messages (Anthropic-shaped) | `POST /v1/messages` | Yes |

Same models, same auth, same per-token cost across all three.

**Capability availability — the decisive split:**

| Capability | Chat Completions | Responses |
|---|---|---|
| Tool calling (function) | ✅ full | ✅ |
| Structured output | ✅ `response_format` | ✅ `text.format` |
| Prompt caching | ✅ automatic | ✅ automatic |
| Reasoning effort | ✅ `reasoning_effort` (top-level) | ✅ `reasoning.effort` (nested) |
| Streaming | ✅ | ✅ |
| **Search grounding** | ❌ **Responses only** | ✅ |
| **Tool search** | ❌ **Responses only** | ✅ |
| **Token counting** | ❌ (`/v1/responses/input_tokens`) | ✅ |
| Custom (freeform) tools | ❌ HTTP 400 | ✅ |
| Reasoning replay / summaries | ❌ | ✅ |

Verbatim: *"Search grounding is not available through the Chat Completions API."*
*"tool search is not available on the Chat Completions API."*

**Implication**: 4 of the 7 capabilities the brief lists are unreachable from a
Chat-Completions-only client. This is the central architectural decision.
