# F016 — Responses API wire shape + search grounding verified live

**Top-level response keys**:
`background, completed_at, created_at, error, id, incomplete_details,
instructions, max_output_tokens, model, object, output, parallel_tool_calls,
reasoning, service_tier, status, store, temperature, tool_choice, tools,
top_logprobs, top_p, truncation, usage`

**`output` is a list of typed items** — not a `choices` array:
```
type='reasoning'  (content empty — private CoT)
type='message'    content[].text -> 'pong'
```
`output_text` is an **OpenAI-SDK-computed convenience property**, not a wire
field. A raw-HTTP implementation must fold `output[]` items of
`type == "message"` itself.

**Search grounding — live, working**:
Request `tools: [{"type": "web_search"}]`, asking who won the 2026 FIFA World Cup.
Output item sequence:
```
['reasoning', 'message', 'web_search_call', 'reasoning', 'message']
```
Final message text: `"Spain won 2026 World Cup"` — a real post-training fact
retrieved live, confirming genuine grounding rather than parametric recall.

**Caveat observed**: `annotations` came back **empty (0 citations)** on both
message parts, although the docs advertise "inline citations". Either citations
need an explicit opt-in, or they are inconsistently populated. **Do not promise
citation extraction in acceptance criteria without re-verifying.**
