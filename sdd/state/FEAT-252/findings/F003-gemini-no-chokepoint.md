---
id: F003
query_id: Q003
type: read
intent: Map all Gemini terminal return paths and the response-contract surface
executed_at: 2026-06-23T03:55:00Z
parent_id: null
depth: 0
---

# F003 — Gemini client: redaction scattered, NO _resolve_final_response chokepoint

## Summary
WS2's core contract is **not** implemented. There is no `_resolve_final_response`
method (grep: absent). Instead the committed work sprinkled `redact_text`/
`redact_secrets` across **~14 ad-hoc call sites** in `google/client.py`. There are
**6 terminal `AIMessageFactory.from_gemini(...)` construction sites** (lines 3146,
3796, 4323, 4505, 4802, 4917) reached by `ask`/`ask_stream`/`resume`/`invoke` —
none funnel through a single provenance/echo gate. `_parse_tool_code_blocks` still
converts ` ```tool_code … default_api.X ``` ` blocks into calls (default_api
hunting un-gated). Forced synthesis still skipped ("to avoid unnecessary delays").

## Citations
- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 3146, 3796, 4323, 4505, 4802, 4917
  symbol: `AIMessageFactory.from_gemini (6 terminal sites)`
- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 1580-1652, 2066-2107
  symbol: `_handle_multiturn_function_calls, _get_function_calls_from_response, _safe_extract_text`
  excerpt: |
    1652: "Skipping forced synthesis to avoid unnecessary delays."
- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 1958-1966
  symbol: `_parse_tool_code_blocks (default_api)`
  excerpt: |
    pattern = r"```tool_code\s*\n\s*print\(default_api\.(\w+)\((.*?)\)\)\s*\n\s*```"
- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 1301,1335,1354,1397,1754,1775,3206-3223,3618,4790
  symbol: `redact_text / redact_secrets scatter (~14 sites)`

## Notes
Resolves the brainstorm VERIFY item: 6 from_gemini terminal sites + the multiturn
tail; none unified. WS2 (the brainstorm's *primary* containment) is the biggest gap.
