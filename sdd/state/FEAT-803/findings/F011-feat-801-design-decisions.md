# F011: FEAT-801 design decisions constraining FEAT-803

From: FW-005

## Summary
FEAT-801 established the **two-surface doctrine**:
- GitHub Pages = informative (what/why/guides, outside SDD flow)
- GitHub Wiki = technical reference (classes, args, parameters, semantics, examples)

Key constraints for FEAT-803:
1. Wiki reflects `main` only — released content
2. Source of truth is the monorepo — wiki repo is a publish target only
3. Migration moves, never copies — technical docs leave `docs/` and nav
4. Language: English (Spanish pages translated during migration)
5. mkdocstrings leaves Pages only in M9, AFTER wiki sync runs green
6. "Never a moment without a published API reference" — M9 is the last step

Pain point #1 from FEAT-801 problem statement: "The informative site is drowned by
technical pages. A newcomer landing on Pages meets 60+ nav entries."

**Post-M7 inventory** (what stays on Pages):
docs/index.md, INSTALL.md, config.md, tools_quick.md, STYLE_GUIDE.md, chapters/**,
guides/**, examples/**, branding/**, postman/**, aws/**, superpowers/**,
docs/decisions/**, docs/sdd/WORKFLOW.md, docs/sdd/CODEX.md, roadmap/brainstorm pages,
@-included files.

## Citations
- wiki:file:sdd/state/FEAT-801/design_research/problem_statement.txt (score=0.51)
- wiki:file:sdd/state/FEAT-801/design_research/constraints_and_goals.txt (score=0.59)
- wiki:file:sdd/specs/github-wiki-technical-reference.spec.md (score=0.42)
- wiki:file:sdd/tasks/index/github-wiki-technical-reference.json (score=1.00)

## Notes
FEAT-803 is the direct solution to FEAT-801 pain point #1. The M7 classification rule
defines the exact post-migration inventory this redesign works with.
