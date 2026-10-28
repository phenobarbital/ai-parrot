# FEAT-753 TASK-4780 — real-browser smoke (2026-10-27)

Real `mermaid@11.17.2` + real DOMPurify bundled with esbuild, run in headless Google Chrome (Playwright).
Same `initialize` config as `A2UIMermaidDiagram.svelte` (securityLevel strict, htmlLabels false global/flowchart/class)
and the same sanitizer profile (`USE_PROFILES: {svg: true, svgFilters: true}`).
Result (`FEAT-753-mermaid-smoke.json`): flowchart and class diagram render; every node/edge/member label is visible
after sanitization; no `<foreignObject>`, no `<script>`, no page errors. Screenshots alongside.
Build check: `vite build` emits `mermaid.core-*.js` (652 kB) as its own async chunk; no `securityLevel` string in any `index-*.js` entry chunk.
