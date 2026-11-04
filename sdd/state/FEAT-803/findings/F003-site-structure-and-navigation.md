# F003: Site structure, navigation, and theme

Merged from: FC-008, FC-010, FG-001, FW-001

## Summary
Material for MkDocs with green/light-green palette, dark mode toggle, sticky nav tabs,
section expand, search, code copy/annotate, glightbox. **Stock theme — no custom CSS,
no overrides directory, no custom JS.** Nav has 14 top-level sections with ~175 entries,
grown organically by feature accretion. A bulk add of 74 orphaned pages (`7e393385bc`)
confirms content was unlinked. TASK-1602 did a prior cleanup. After FEAT-801 M7 migration,
most technical sections lose their pages. `STYLE_GUIDE.md` is a code-style guide (Python
conventions), NOT a docs style guide.

**Current nav sections** (175 entries):
Home(1) · Getting Started(3) · Foundations(11) · LLM Clients(8) · Bots & Agents(17) ·
Memory & Knowledge(13) · Knowledge Graph(8) · Tools/RAG(18) · Integrations(28) ·
Prompts(5) · Orchestration(7) · Advanced(30) · API Reference(11, removed by M9) ·
Reference(2) · Development(15+)

## Citations
- mkdocs.yml:17-50 — theme config (Material, green palette, robot icon)
- mkdocs.yml:114-341 — full nav tree (175 entries, 14 sections)
- docs/STYLE_GUIDE.md:1-30 — code style, not docs style
- 7e393385bc — bulk add of 74 orphaned pages
- wiki:file:sdd/tasks/completed/TASK-1602-mkdocs-nav-update-and-cleanup.md — prior nav cleanup

## Notes
For an informative site post-migration, the nav collapses to ~5-6 sections: Home (redesigned),
Getting Started (expanded), Concepts (from Foundations/Clients/Bots), Guides, Integrations
(summary), and "Technical Reference → Wiki" link. Development section stays but is less
prominent. The stock theme is a clean slate for custom CSS/templates.
