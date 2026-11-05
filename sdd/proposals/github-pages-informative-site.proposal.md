---
id: FEAT-803
title: "GitHub Pages Informative Site Redesign"
slug: github-pages-informative-site
type: feature
mode: investigation
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: "2026-11-04"
  summary_oneline: "Redesign GitHub Pages (mkdocs) as informative landing site after FEAT-801 wiki migration"
overall_confidence: high
base_branch: dev
projects: [docs]
tags: [docs, github-pages, mkdocs, landing-page, branding]
research_state: sdd/state/FEAT-803/
created: "2026-11-04"
updated: "2026-11-04"
---

# FEAT-803 — GitHub Pages Informative Site Redesign

> **Mode**: investigation
> **Confidence**: high
> **Source**: `inline` — user-initiated after FEAT-801 task decomposition
> **Audit**: [`sdd/state/FEAT-803/`](../state/FEAT-803/)

---

## 0. Origin

The original request, preserved verbatim. Full source at `sdd/state/FEAT-803/source.md`.

> Rediseño del sitio GitHub Pages (mkdocs) como cara informativa del proyecto ai-parrot,
> una vez que FEAT-801 (GitHub Wiki as the Technical Reference) haya aterrizado en main.

**Initial signals**:
- Verbs: "rediseño" / "transform" → new design, not a fix
- Named entities: GitHub Pages, mkdocs, FEAT-801, M9, Material for MkDocs
- Dependencies: FEAT-801 (8 tasks, all pending) + M9 (post-release cut-over)
- Acceptance criteria provided: goal list in source, no formal ACs

---

## 1. Synthesis Summary

After FEAT-801 migrates ~100+ technical reference pages from `docs/` to the GitHub Wiki and M9 removes the mkdocstrings plugin, the GitHub Pages site shrinks from 175 nav entries across 14 sections to roughly 30–40 informative pages in ~6 sections. FEAT-803 redesigns this leaner site as the project's public face: a fresh standalone landing page at the site root, a streamlined mkdocs documentation hub at `/docs/` with concept-oriented chapter overviews cross-linking the wiki, 3–4 beginner tutorials (first chatbot, first agent, first tool, plus one additional), and a unified brand identity (logo, favicon, social card). The existing two-tier deployment pattern (`landing/index.html` at root, mkdocs at `/docs/`, overlay via `cp -R landing/. site/`) is preserved. This is content and design work only — no Python code, no platform migration, Material theme stays.

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-803/findings/`.
> Each cites the finding ID(s) that justify its inclusion.

### 2.1 Localization

| # | Path | Role | Evidence |
|---|------|------|----------|
| 1 | `landing/index.html` | Standalone HTML landing page at site root — full redesign (hero, features, providers, CTAs) | F010 |
| 2 | `landing/css/style.css` | Landing page styles — brand refresh | F010 |
| 3 | `landing/js/main.js` | Landing page JS — updates for new sections/interactions | F010 |
| 4 | `mkdocs.yml` | Collapse 14→6 sections; update theme palette/logo; remove mkdocstrings plugin; add `custom_dir` for overrides | F003, F011 |
| 5 | `docs/index.md` | Rewrite as concept-oriented hub with chapter cards and wiki cross-links | F002, F004 |
| 6 | `docs/chapters/*.md` (7 files) | Rewrite as concept introductions (what/why) with "deep dive in the Wiki →" CTAs; keep 1:1 with wiki sections | F004 |
| 7 | `docs/getting-started.md` | Add to mkdocs nav prominently; minor flow edits | F002 |
| 8 | `docs/config.md` | Add "minimal config" section at top; collapse advanced vars into expandable sections | F005 |
| 9 | `docs/tools_quick.md` | Curate to 3–4 showcase tools; full catalog links to wiki | F006 |
| 10 | `docs/branding/` | Existing assets; add `favicon.ico`, `social-card.png` for OG tags | F001 |
| 11 | `docs/overrides/` (new) | Custom CSS for hero sections, social cards; custom partials for footer/header | F003 |
| 12 | `.github/workflows/docs.yml` | Remove mkdocstrings install step (M9); possibly add social card generation | F010, F009 |
| 13 | `requirements-docs.txt` (new) | Declare mkdocs-material + extensions as docs build dependencies | F009, F010 |
| 14 | `docs/tutorials/` (new) | 3–4 beginner tutorials: first chatbot, first agent, first tool, +1 | F008 |

### 2.2 Constraints Discovered

- **FEAT-801 + M9 dependency.** TASK-5172 mass-moves ~100+ files from `docs/` to the wiki; M9 removes `mkdocstrings`. FEAT-803 cannot merge until both land — it works against the post-migration inventory.
  *Evidence*: F011

- **Material theme stays.** The source explicitly constrains this to a content/theme redesign — no platform migration. MkDocs Material is the framework; customization is via `custom_dir` overrides and palette config, not a replacement.
  *Evidence*: F003

- **Two-surface doctrine.** Pages = informative (what/why/guides); Wiki = technical reference (classes, args, parameters). Never copy content between the two — always cross-link.
  *Evidence*: F011

- **Landing overlay pattern.** `.github/workflows/docs.yml` builds mkdocs into `site/docs/` then overlays `landing/` at root via `cp -R landing/. site/`. This pattern must be preserved — it is the deployment mechanism.
  *Evidence*: F010

- **Existing assets preserved.** Guides, examples, branding, Postman collections that stay on Pages per M7 classification must not be deleted or broken.
  *Evidence*: F007, F008, F001

- **No Python code.** This is content and design work only.
  *Evidence*: source.md

### 2.3 Recent History (Relevant)

| Commit | When | Message | Relevance |
|--------|------|---------|-----------|
| `0f800e796b` | 2026-11-04 | sdd: add 8 tasks for FEAT-801 — github-wiki-technical-reference | FEAT-801 task decomposition complete; defines the post-migration inventory |
| `88a5a6cf20` | ~2026-11-03 | sdd: spec for FEAT-801 | Spec with M7 classification rule and two-surface doctrine |

No recent commits to `landing/`, `mkdocs.yml`, or the `docs/` content files — the site has been stable. Absence of recent changes confirms this is a greenfield redesign against a stable base, not a regression to chase.

---

## 3. Hypothesis

### Hypothesis 1 — The two-tier architecture already exists; this is a content/theme refresh, not a platform migration · Confidence: high

**Supporting evidence**: F010, F011
**Contradicting evidence**: —
**Reasoning**: `landing/index.html` already serves as the standalone landing page at the site root with Inter/JetBrains Mono/Font Awesome/Prism. MkDocs already serves at `/docs/`. The workflow already overlays them. The redesign refreshes both surfaces and restructures the mkdocs content — it does not introduce a new architecture.

### Hypothesis 2 — Post-M7 nav collapses from 175 entries to ~30–40 pages, enabling a 5–6 section structure · Confidence: high

**Supporting evidence**: F003, F011, F004
**Contradicting evidence**: —
**Reasoning**: The M7 classification rule defines exactly what stays: index, install, config, tools_quick, style_guide, 7 chapters, guides, examples, branding, postman, aws, superpowers, decisions, sdd (workflow+codex), roadmap brainstorm pages. Everything else moves to the wiki. The remaining inventory is small enough for a newcomer-friendly 5–6 section nav.

### Hypothesis 3 — The biggest content gap is beginner tutorials · Confidence: high

**Supporting evidence**: F008, F002, F006
**Contradicting evidence**: —
**Reasoning**: `getting-started.md` covers installation but is hidden from nav. There are no "build your first X" walkthroughs anywhere in the codebase. The `examples/` directory contains only passkey files and Postman collections — no code tutorials. This is the #1 content creation opportunity for the informative site.

### Hypothesis 4 — Brand identity unification is a parallel workstream · Confidence: high

**Supporting evidence**: F001, F003
**Contradicting evidence**: —
**Reasoning**: 5 branding SVGs exist but brand identity is fragmented across 3 different icons (robot, parrot, generic). No favicon, no social card, no hero image. This workstream (logo consolidation, favicon, social card, consistent icon usage) is independent of nav restructuring and can run in parallel.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Two-tier deployment (landing HTML at root + mkdocs at /docs/) already exists | F010 | high | Verified in workflow file and landing/ directory |
| C2 | Nav collapses from 14→6 sections after M7 migration | F003, F011 | high | M7 classification rule is explicit; post-migration inventory enumerated |
| C3 | `getting-started.md` exists (27KB) but is hidden from nav | F002 | high | Direct file read confirmed |
| C4 | No beginner tutorials exist in the codebase | F008, F002 | high | Grep + examples/ directory scan found none |
| C5 | 5 branding SVGs exist but no favicon or social card | F001 | high | Direct branding/ directory listing |
| C6 | Brand identity uses 3 different icons (robot, parrot, generic) | F001 | high | Visual inspection of SVG files |
| C7 | mkdocstrings deps not declared in any requirements file | F009 | high | No requirements-docs.txt; no docs extra in pyproject.toml |
| C8 | 7 chapter overview files follow consistent pattern | F004 | high | All 7 read; same intro + bullet + read-next structure |
| C9 | `docs.yml` workflow overlays landing via `cp -R landing/. site/` | F010 | high | Workflow file read verbatim |
| C10 | Stock Material theme — no custom CSS, no overrides directory | F003 | high | mkdocs.yml has no `custom_dir`; `docs/overrides/` does not exist |

Distribution: **10** high, **0** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Should the landing page be redesigned from scratch or iterated?** — *Resolved*: Redesign from scratch. New layout, new sections, new copy.
  *Resolves claims*: C1 (approach, not existence)

- [x] **How many beginner tutorials in scope?** — *Resolved*: 3–4 tutorials (first chatbot, first agent, first tool, plus one additional — likely RAG or deployment).
  *Resolves claims*: C4

- [x] **Consolidate chapter overviews 7→5 or keep 1:1?** — *Resolved*: Keep 1:1 with wiki sections. One overview per wiki section for simpler mapping and cross-linking.
  *Resolves claims*: C8

### Unresolved (defer to spec / implementation)

- [ ] **Which 4th tutorial?** — *Owner*: tbd
  *Blocks*: tutorial content scope
  *Plausible answers*: a) RAG pipeline · b) deployment guide · c) tool creation

- [ ] **Landing page design system?** — *Owner*: tbd
  *Blocks*: visual implementation
  *Plausible answers*: a) keep Inter/JetBrains Mono + FA (current fonts) · b) adopt Material-adjacent design tokens · c) custom design system

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-803`** — *Rationale*: localization is high-confidence across all 14 paths, the three workstreams are well-scoped (landing redesign, mkdocs restructuring, tutorial creation), all unknowns are implementation-level decisions deferrable to the spec. The dependency on FEAT-801 + M9 is a merge constraint, not a blocking uncertainty.

### Alternatives

- **`/sdd-brainstorm FEAT-803`** — if you want to explore alternative site architectures (e.g. Astro, Docusaurus) or radically different content strategies. Not recommended given the "Material stays" constraint.
- **`/sdd-task FEAT-803`** — premature; the spec needs to define the 3–4 tutorials, the new nav structure, and the landing page sections before decomposition.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-803/state.json` |
| Source (raw) | `sdd/state/FEAT-803/source.md` |
| Research plan | `sdd/state/FEAT-803/research_plan.json` |
| Findings (canonical) | `sdd/state/FEAT-803/findings/F001-*.md` … `F011-*.md` |
| Findings (lane originals) | `sdd/state/FEAT-803/findings/.audit/` |
| Synthesis (JSON) | `sdd/state/FEAT-803/synthesis.json` |

**Budget consumed**:
- Files read: 23 / 40
- Grep calls: 3 / 25
- Git calls: 4 / 10
- Wiki queries: 10 (free)
- Truncated: **no**

**Mode determination**: `inline` source describes a redesign → `investigation` (no existing bug; exploratory scope).

**Parallel research (FEAT-708)**: 3 lanes dispatched as forks — codebase (FC, 10 findings), git (FG, 3 findings), wiki (FW, 5 findings). Merged 18→11 canonical findings (7 merged, 11 standalone). Lane originals archived to `findings/.audit/`.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (jlara@trocglobal.com) |
