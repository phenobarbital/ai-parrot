---
id: F008
query_id: Q013,Q018
type: read
intent: which frontend renderer consumes infographics; is there an A2UI renderer in this repo's UI?
executed_at: 
parent_id: null
depth: 0
---
# F008 — The bundled Svelte UI renders infographics as HTML in an iframe (or 12 legacy JSON block components); it has NO A2UI renderer
## Summary
In `packages/ai-parrot-server/ui/src` the string "a2ui" appears in exactly one file, the generated `AgentChatResponse.d.ts` type — no A2UI renderer exists in this repo's frontend. `AgentChat.svelte.maybeOpenInfographicCanvas()` fires only on `output_mode === "infographic"`, prefers inline HTML (`srcdoc`) and falls back to `metadata.html_url` (iframe `src`). `InfographicCanvas.svelte` supports `mode:'html'` (iframe) and a legacy `mode:'json'` path rendered by `InfographicBlockCanvas` through `infographic-registry.ts`, which registers only 12 block types (FEAT-039) versus 19 backend block types — the 7 newer blocks (accordion, checklist, tab_view, chain, steps, code, card_grid) have no Svelte component. The surface is feature-flagged (`features.infographic` / `__AGENTCHAT_INFOGRAPHIC__`, FEAT-476 TASK-2595).
## Citations
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte`
  lines: 1839-1878
  symbol: `maybeOpenInfographicCanvas`
  excerpt: |
    if (message.output_mode !== "infographic") return;
    if (inlineHtml.includes("<html") ...) tabData = { mode: "html", html: inlineHtml, ...common };
    else if (url) tabData = { mode: "html", url, ...common };
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.svelte`
  lines: 1-60, 263, 284-293, 393-402
  excerpt: |
    // Handles both legacy string format (HTML from FEAT-034) and new structured format (FEAT-039).
    <iframe bind:this={iframeEl} srcdoc={tabData?.html ?? ''} ...>
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-registry.ts`
  lines: 1-35
  excerpt: |
    registry.set("title"|"hero_card"|"summary"|"chart"|"table"|"bullet_list"|"image"|"quote"|"callout"|"divider"|"timeline"|"progress", ...)  // 12 types
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts`
  lines: 1-21
  symbol: `InfographicBlockType` (12 members)
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/canvas-registry.ts`
  lines: 9, 30-31
- path: `packages/ai-parrot-server/ui/src/lib/api/infographic.ts`
  lines: 1-12
  excerpt: |
    FEAT-034 ... LLM generates the full HTML/CSS layout. FEAT-039: Added dedicated infographic handler endpoints
- path: `packages/ai-parrot-server/ui/src/lib/features.ts`
  lines: 28
- path: `packages/ai-parrot-server/ui/src/lib/types/generated/AgentChatResponse.d.ts` (only "a2ui" hit in ui/src)
