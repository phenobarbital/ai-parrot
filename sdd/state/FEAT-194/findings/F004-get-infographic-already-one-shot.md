---
id: F004
queries: [Q024, parent of get_infographic]
confidence: high
---

# `bot.get_infographic()` is already the one-shot flow — just gated to a different endpoint

`AbstractBot.get_infographic()` (bots/abstract.py:3788-3893) is the one-shot
orchestrator the user wants for AgentTalk. It does:

1. **Auto-detect template** via `_detect_infographic_template(question)`
   (lines 3743-3786): a short, context-free LLM call that selects the best
   template name from `infographic_registry.list_templates_detailed()`.
   Falls back to `"basic"` on any failure.
2. **Build template instruction** via `tpl.to_prompt_instruction()`.
3. **Augment the question** with the template instruction + theme hint.
4. **Call `self.ask(augmented_question, structured_output=InfographicResponse,
   output_mode=OutputMode.INFOGRAPHIC, ...)`** — single LLM turn with
   structured output.
5. **Content-negotiate the render**: if `"application/json" not in accept`,
   instantiate `InfographicHTMLRenderer()` and call
   `renderer.render_to_html(response.structured_output or response.output,
   theme=theme)` — overwrites `response.content` with HTML and sets
   `response.output_mode = OutputMode.HTML`.

So `OutputMode.INFOGRAPHIC` is referenced in **exactly 3 places** in the
source tree:
- `bots/abstract.py:3877` — inside `get_infographic()`
- `outputs/formats/infographic.py:49` — registration
- `outputs/formats/__init__.py:82` — lazy import dispatch

It is **NOT** dispatched from `bot.ask()` directly. If you pass
`output_mode=INFOGRAPHIC` to `ask()`, you get the system prompt + structured
JSON, but the HTML render step doesn't run.

This is the architectural gap behind the user's "2 steps": for the
infographic to appear as the primary response of AgentTalk, the same
template-detection + render-after-ask pipeline that lives in
`get_infographic()` must be reachable from the main `/chat/` POST.

## Citations
- packages/ai-parrot/src/parrot/bots/abstract.py:3743-3786 —
  `_detect_infographic_template()`
- packages/ai-parrot/src/parrot/bots/abstract.py:3788-3893 —
  `get_infographic()`
- packages/ai-parrot/src/parrot/bots/abstract.py:3877 — `output_mode=
  OutputMode.INFOGRAPHIC` passed to ask()
- packages/ai-parrot/src/parrot/bots/abstract.py:3883-3891 — content
  negotiation + HTML render
