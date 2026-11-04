# FW-001: Current mkdocs site structure and theme

## Query
`wikitoolkit query "mkdocs site structure and theme configuration"`

## Result
The site uses Material for MkDocs with green/light-green palette, dark mode toggle,
navigation tabs (sticky), sections expand, search, code copy/annotate, and glightbox.
The nav has 14 top-level sections with ~300+ pages total. `mkdocstrings` generates
API reference from `packages/ai-parrot/src` only (one of nine namespaces).
TASK-1602 (completed) did a nav cleanup pass. TASK-5172 (FEAT-801, pending) will
mass-move technical docs to wiki/.

## Citations
- wiki:file:sdd/tasks/completed/TASK-1602-mkdocs-nav-update-and-cleanup.md (score=1.00) — prior nav cleanup
- wiki:file:docs/index.md (score=0.67) — current landing page within mkdocs
- wiki:file:sdd/tasks/active/TASK-5172-techwiki-migration-docs-to-wiki.md (score=0.23) — pending migration
- mkdocs.yml:1-341 — full nav and theme config

## Notes
The nav currently has 14 top-level groups: Home, Getting Started, Foundations, LLM Clients,
Bots & Agents, Memory & Knowledge, Knowledge Graph, Tools/Loaders/RAG, Integrations & Transport,
Prompts, Orchestration & Flows, Advanced, API Reference, Reference, Development.
After FEAT-801 M7 migration, most of these sections will lose their technical pages.
