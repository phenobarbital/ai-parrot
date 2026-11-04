---
kind: inline
jira_key: null
fetched_at: "2026-11-04T22:30:00Z"
summary_oneline: "Redesign GitHub Pages (mkdocs) as informative landing site after FEAT-801 wiki migration"
---

# GitHub Pages Informative Site Redesign

Rediseño del sitio GitHub Pages (mkdocs) como cara informativa del proyecto ai-parrot,
una vez que FEAT-801 (GitHub Wiki as the Technical Reference) haya aterrizado en main.

## Context

- FEAT-801 moves all technical reference documentation from `docs/` to the GitHub Wiki.
- M9 (Pages cut-over / mkdocstrings removal) is a post-release follow-up excluded from
  FEAT-801's task graph — it removes the auto-generated API Reference section from mkdocs.
- After both land, the mkdocs site no longer serves as technical reference.

## Goal

Transform the GitHub Pages site into a **product landing / informative site**:
- What is AI-Parrot: value proposition, architecture overview, supported providers
- Key concepts: clients, bots, agents, tools, flows, skills, memory
- Getting started guides: installation, first chatbot, first agent, first tool
- New navigation structure optimized for newcomers (not developers digging into internals)
- Branding and visual identity refresh
- Links to the GitHub Wiki for technical deep-dives
- Links to PyPI, GitHub, community channels

## Constraints

- This is content and design work — no testable logic, no Python code changes.
- Depends on FEAT-801 (wiki infrastructure) and M9 (mkdocstrings removal).
- The first GitHub Wiki page has already been created manually in the repo.
- The mkdocs stack (Material for MkDocs) stays — this is a content/theme redesign, not a platform migration.
- Must preserve existing guides, examples, and branding assets that stay on Pages.
