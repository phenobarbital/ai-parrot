# F002: Getting started flow and entry points

Merged from: FC-005, FG-003, FW-004

## Summary
The canonical install guide `docs/getting-started.md` (27KB) exists and is well-written
(OS-specific blocks, uv-based, CI-verified claims) but is **hidden from mkdocs nav** —
reachable only via a link inside `INSTALL.md`. The nav shows only INSTALL.md, config.md,
and tools_quick.md under "Getting Started". Current entry points for newcomers:
1. Landing page → links to /docs/
2. docs/index.md → hero cards linking 7 chapter overviews
3. INSTALL.md → points to getting-started.md
4. getting-started.md → comprehensive but unlisted in nav
5. config.md → flat env-var reference
6. tools_quick.md → tools catalog (cookbook-style)
7. chapters/*.md → 7 chapter overviews (1.6-3.3KB each)

## Citations
- docs/getting-started.md:1-50 — canonical install guide (27KB, not in nav)
- mkdocs.yml:116-119 — nav shows INSTALL.md, config.md, tools_quick.md only
- docs/INSTALL.md — legacy install, references getting-started.md
- docs/chapters/*.md — 7 chapter overviews
- wiki:file:sdd/tasks/completed/TASK-3584-guide-and-claim-convention.md — getting-started creation
- wiki:file:sdd/tasks/completed/TASK-4095-docs-and-supersede.md — getting-started extension

## Notes
The informative site MUST surface getting-started.md prominently. After FEAT-801 migration,
chapter overview pages lose their deep-dive links — rewrite them as concept introductions
with "deep dive in the Wiki →" links. The config page needs a "minimal config" section
instead of the current flat dump.
