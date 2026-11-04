# F004: Chapter overview pages

From: FC-002

## Summary
Seven chapter overview files under `docs/chapters/` serve as section landing pages:
foundations, llm-clients, bots-agents, memory-knowledge, knowledge-graph, tools-rag,
integrations. Each follows a consistent pattern: short intro (1-2 paragraphs) +
"What lives here" bullet list + "Read next" links. Lightweight (1.6-3.3KB each).
Currently developer-oriented with architecture-series links and API reference pointers.

## Citations
- docs/chapters/foundations.md:1-39 — canonical chapter overview pattern
- docs/chapters/ — all 7 files (foundations, llm-clients, bots-agents, memory-knowledge,
  knowledge-graph, tools-rag, integrations)

## Notes
Post-FEAT-801, these pages lose their "Read next" targets (moved to wiki). Rewrite as
concept-level introductions (what/why, not how) with "deep dive in the Wiki →" CTAs.
Some may merge: e.g. memory-knowledge + knowledge-graph → "Knowledge & Memory" concept page.
