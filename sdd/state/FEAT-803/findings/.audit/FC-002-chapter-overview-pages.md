# FC-002: Chapter overview pages

## Query
`ls docs/chapters/`

## Result
Seven chapter overview files serve as section landing pages:
- `foundations.md` (1.7K) — core abstractions, hooks, data models
- `llm-clients.md` (1.8K) — AbstractClient providers
- `bots-agents.md` (1.6K) — Chatbot, Agent, AgentCrew
- `memory-knowledge.md` (1.8K) — conversation memory, RAG stores
- `knowledge-graph.md` (3.3K) — PageIndex, GraphIndex, LLM Wiki
- `tools-rag.md` (2.1K) — @tool decorator, toolkits, loaders
- `integrations.md` (2.2K) — Telegram, Teams, WhatsApp, MCP, A2A

Structure: each is a short intro (1-2 paragraphs) + "What lives here" bullet list + "Read next" links to child pages. See `foundations.md` for the pattern (lines 1-39).

## Citations
- docs/chapters/foundations.md:1-39 — canonical chapter overview pattern
- docs/chapters/ — all 7 files

## Notes
These chapter pages are developer-oriented (deep-dive structure). An informative site would keep concept-level overviews but strip the architecture-series links and API reference pointers. Some of these may move to wiki under FEAT-801 M7, so the redesign must coordinate with the migration map.
