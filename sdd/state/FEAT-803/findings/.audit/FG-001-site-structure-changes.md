# FG-001: Recent site structure changes (since 2026-06-01)

## Query
`git log --oneline --since="2026-06-01" -- mkdocs.yml docs/index.md docs/chapters/`

## Result
20 commits since June 2026 touching mkdocs.yml, index.md, or chapters/. Key events:
- `7e393385bc` — added 74 orphaned pages to mkdocs nav (bulk nav expansion)
- `4e9b4fefe6` — published Knowledge Graph section (LLM Wiki, PageIndex, GraphIndex)
- `0224f0cf34` — TASK-1602 mkdocs.yml nav update and page cleanup (AgentCrew/AgentsFlow docs reorg)
- `a2c577f444` — added Jev client satellite docs
- Multiple FEAT-specific doc additions (A2UI, FormBuilder, sandbox, etc.)
The nav has grown organically — 310+ lines, 12 top-level sections, heavy on internal/developer docs.

## Citations
- mkdocs.yml — 341-line nav tree, 12 top-level sections
- docs/index.md — current landing page with chapter grid cards and use-case tabs
- docs/chapters/ — 7 chapter overview pages (foundations, llm-clients, bots-agents, memory-knowledge, knowledge-graph, tools-rag, integrations)

## Notes
The nav was never designed for newcomers — it grew by feature accretion. The 74-orphan bulk add (`7e393385bc`) confirms significant content was unlinked and got bulk-wired without curation.
