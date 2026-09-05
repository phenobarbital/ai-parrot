# F014 — Both protocols and all constraint claims verified live

Model used: `muse-spark-1.3-contributor` (synthetic prompts only).

| # | Probe | Result |
|---|---|---|
| 1 | `POST /v1/chat/completions` | **200** — returned `'pong'` |
| 2 | `POST /v1/responses` | **200** — `status: "completed"` |
| 3 | `POST /v1/responses/input_tokens` | **200** — `{"object":"response.input_tokens","input_tokens":169}` |
| 4 | `tool_choice: "required"` | **400** ✓ constraint confirmed |
| 5 | function tool with `strict: true` | **200** ✓ accepted |

Probe 4 error, verbatim:
```
only `"auto"` is supported for `tool_choice`. `"none"`, `"required"`,
and named function choices are not curren[tly supported]
```

**Conclusions**:
- **C7 upgraded low→high**: `strict: true` with a conformant schema is accepted.
  `ToolFormat.OPENAI` can be inherited unchanged. No Meta-specific tool format
  needed (unlike Groq).
- **C6 confirmed by live 400**, not just by doc reading.
- Token counting is reachable **without** implementing Responses generation —
  it is a standalone POST.
