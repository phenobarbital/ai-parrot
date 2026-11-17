# FW-004: Getting started and user-facing entry points

## Query
`wikitoolkit query "getting started installation quickstart"`
+ `wikitoolkit page "file:sdd/tasks/completed/TASK-4095-docs-and-supersede.md"`

## Result
The canonical installation/first-use guide is `docs/getting-started.md` (27KB),
created by TASK-3584 (FEAT-586) and extended by TASK-4095 (FEAT-633) with global runtime,
`parrot self`, `parrot sdd`, and CI-verified claims (`<!-- verify: … -->` anchors).

Current entry points for newcomers:
1. Landing page (`landing/index.html`) → links to `docs/` (mkdocs)
2. `docs/index.md` → hero cards linking to 7 chapter overviews
3. `docs/INSTALL.md` → legacy install guide, now points to getting-started.md
4. `docs/getting-started.md` → canonical guide (project-venv + managed runtime)
5. `docs/config.md` → configuration reference
6. `docs/tools_quick.md` → quick start for tools
7. `docs/chapters/*.md` → 7 chapter overview pages (foundations, llm-clients,
   bots-agents, memory-knowledge, knowledge-graph, tools-rag, integrations)

The chapter pages are lightweight (1.6-3.3KB) — they're TOC/overview pages linking
deeper into technical docs that will move to wiki after FEAT-801.

## Citations
- wiki:file:sdd/tasks/completed/TASK-3584-guide-and-claim-convention.md (score=0.31) — getting-started creation
- wiki:file:sdd/tasks/completed/TASK-4095-docs-and-supersede.md (score=0.08) — getting-started extension
- wiki:file:docs/INSTALL.md (score=0.33) — legacy install page
- docs/getting-started.md — 27KB canonical guide
- docs/chapters/*.md — 7 chapter overviews

## Notes
After FEAT-801 migration, the chapter overview pages will need rewriting — their links
will point to moved pages in the wiki. This is a natural place for FEAT-803 to
restructure them as concept-oriented introductions (what/why) with "deep dive in the Wiki →" links.
