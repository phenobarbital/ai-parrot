# FW-005: FEAT-801 design decisions relevant to FEAT-803

## Query
`wikitoolkit query "FEAT-801 github wiki technical reference migration"`
+ `wikitoolkit page "file:sdd/state/FEAT-801/design_research/problem_statement.txt"`
+ `wikitoolkit page "file:sdd/state/FEAT-801/design_research/constraints_and_goals.txt"`

## Result
FEAT-801 established the two-surface doctrine:
- **GitHub Pages = informative** (what/why/guides, written on demand, outside SDD flow)
- **GitHub Wiki = technical reference** (classes, arguments, parameters, semantics, examples)

Key decisions that constrain FEAT-803:
1. Wiki reflects `main` only — released content on PyPI
2. Source of truth is the monorepo — wiki repo is a publish target only
3. Migration moves, never copies — technical docs leave `docs/` and mkdocs nav
4. Language: English (Spanish pages translated during migration)
5. `mkdocstrings` leaves Pages only in M9 cut-over, AFTER wiki sync runs green on `main`
6. "Never a moment without a published API reference" — M9 is the last step

The problem statement explicitly describes Pages' future role:
> "The informative site is drowned by technical pages. A newcomer landing on Pages
> meets 60+ nav entries. The site cannot become a clean 'what is parrot, what does it do'
> front door while it also has to be the reference manual."

FEAT-803 is the solution to pain point #1.

## Citations
- wiki:file:sdd/state/FEAT-801/design_research/problem_statement.txt (score=0.51) — three pains
- wiki:file:sdd/state/FEAT-801/design_research/constraints_and_goals.txt (score=0.59) — two-surface doctrine
- wiki:file:sdd/specs/github-wiki-technical-reference.spec.md (score=0.42) — full spec
- wiki:file:sdd/tasks/index/github-wiki-technical-reference.json (score=1.00) — 8 tasks, 5 waves

## Notes
FEAT-801 M7 classification rule (TASK-5172) defines what stays on Pages:
- docs/index.md, INSTALL.md, config.md, tools_quick.md, STYLE_GUIDE.md
- chapters/**, guides/**, examples/**, branding/**, postman/**, aws/**, superpowers/**
- docs/decisions/**, docs/sdd/WORKFLOW.md, docs/sdd/CODEX.md
- roadmap/brainstorm pages, any @-included by CLAUDE.md

Everything else moves to wiki/. This is the post-migration inventory FEAT-803 works with.
