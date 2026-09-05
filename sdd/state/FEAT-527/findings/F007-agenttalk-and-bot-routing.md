---
id: F007
query_id: Q010,Q011
type: read
intent: how AgentTalk / bots route infographic results (A2UI vs INFOGRAPHIC)
executed_at: 2026-09-04T19:45:00Z
parent_id: null
depth: 0
---
# F007 — Bots and AgentTalk already branch on InfographicRenderResult.a2ui_envelope; with the default toolkit config the branch taken is the HTML one
## Summary
`PandasAgent.ask()` (data.py) and `BaseBot` (base.py) both detect the last `InfographicRenderResult` tool result; if `a2ui_envelope` is set they call `finalize_a2ui_response()` (→ `OutputMode.A2UI`), otherwise `_finalize_infographic_response()` sets `response.output = html_inline or html_url`, `output_mode = INFOGRAPHIC`. `AgentTalk.post` then checks `OutputMode.A2UI` first (returns `{output_mode:"a2ui", a2ui_envelope}`) and `OutputMode.INFOGRAPHIC` second (`_format_infographic_response`: JSON envelope with `output`=HTML url/inline, `metadata.template_name/theme/html_url`, or raw `text/html` under Accept negotiation, with CSP headers from `JSBundle`s). Streaming is force-disabled for INFOGRAPHIC. Separately, `AbstractBot.get_infographic()` (used by `InfographicTalk`) still calls the deprecated `get_infographic_html_renderer()` and rewrites `output_mode = OutputMode.HTML`.
## Citations
- path: `packages/ai-parrot/src/parrot/bots/data.py`
  lines: 1876-1910
  excerpt: |
    if getattr(infographic_envelope, "a2ui_envelope", None) is not None:
        response.a2ui_envelope = ...; finalize_a2ui_response(response); return response
    explanation = self._finalize_infographic_response(response, infographic_envelope)
- path: `packages/ai-parrot/src/parrot/bots/base.py`
  lines: 895-915, 1425-1445
  symbol: `_finalize_infographic_response`
  excerpt: |
    response.output = envelope.html_inline or envelope.html_url
    response.output_mode = OutputMode.INFOGRAPHIC
- path: `packages/ai-parrot-server/src/parrot/handlers/agent.py`
  lines: 1625-1628
  excerpt: |
    if output_mode in (OutputMode.INFOGRAPHIC, OutputMode.INTERACTIVE): use_stream = False
- path: `packages/ai-parrot-server/src/parrot/handlers/agent.py`
  lines: 2729-2756
  excerpt: |
    if output_mode == OutputMode.A2UI: return json_response({... "output_mode": "a2ui", "a2ui_envelope": ...})
    if output_mode == OutputMode.INFOGRAPHIC: return self._format_infographic_response(...)
- path: `packages/ai-parrot-server/src/parrot/handlers/agent.py`
  lines: 3052-3135
  symbol: `AgentTalk._format_infographic_response`
- path: `packages/ai-parrot-server/src/parrot/handlers/agent.py`
  lines: 3023-3050
  symbol: `AgentTalk._extract_infographic_explanation`
- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 3952-4060
  symbol: `AbstractBot.get_infographic`
  excerpt: |
    output_mode=OutputMode.INFOGRAPHIC ... InfographicHTMLRenderer = get_infographic_html_renderer()
    response.content = html; response.output_mode = OutputMode.HTML
- path: `packages/ai-parrot-server/src/parrot/handlers/infographic.py`
  lines: 1-12, 72, 199-251, 819-833
  symbol: `InfographicTalk`, `_negotiate_accept`
