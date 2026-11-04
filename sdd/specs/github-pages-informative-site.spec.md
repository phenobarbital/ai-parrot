---
type: feature
base_branch: dev
projects: [docs]
tags: [docs, github-pages, mkdocs, landing-page, branding, tutorials]
---

# Feature Specification: GitHub Pages Informative Site Redesign

**Feature ID**: FEAT-803
**Date**: 2026-11-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: post-FEAT-801 + M9

---

## 1. Motivation & Business Requirements

### Problem Statement

After FEAT-801 migrates ~100+ technical reference pages from `docs/` to the
GitHub Wiki and M9 removes the mkdocstrings auto-generated API Reference,
the GitHub Pages site is left with two problems:

1. **Structural debt**: the mkdocs nav still has 14 top-level sections and
   175 entries — most of which will be gone. The remaining ~30–40 pages
   need a new, smaller nav optimized for newcomers, not developers digging
   into API internals.
2. **Content gap**: there are no beginner tutorials ("build your first X"),
   no unified brand identity (3 different icons used), no favicon, no
   social card, and the 27 KB getting-started guide is hidden from the nav.

FEAT-801's pain point #1: *"The informative site is drowned by technical
pages. A newcomer landing on Pages meets 60+ nav entries."*

### Goals

- G1: Redesign the standalone landing page (`landing/index.html`) from
  scratch as a compelling product front door with hero, value proposition,
  provider showcase, and clear CTAs.
- G2: Collapse the mkdocs nav from 14 sections to ~6 newcomer-friendly
  sections.
- G3: Rewrite the 7 chapter overview pages as concept introductions
  (what/why) with "deep dive in the Wiki →" cross-links.
- G4: Create 3–4 beginner tutorials (first chatbot, first agent, first
  tool, plus one additional).
- G5: Unify the brand identity: consolidate logo/icon usage, add favicon,
  add social card for OG tags.
- G6: Declare docs build dependencies in `requirements-docs.txt`.
- G7: Update the CI workflow to remove the mkdocstrings install step.

### Non-Goals (explicitly out of scope)

- No Python code changes — this is content and design work only.
- No platform migration — MkDocs Material stays.
- No content duplication between Pages and Wiki — cross-link only (two-surface doctrine).
- No wiki content authoring — FEAT-801 owns that.
- No mkdocstrings removal from mkdocs.yml — M9 owns that decision, but this
  spec prepares the nav structure for a world without it.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:cb75788f6f3023ef176f86f7e20c0dd266189d232763feba1962a5144de97efb evaluation_digest=sha256:d14ca93e985ee2e5806b5a5d864b587338d0dbd56b13cee9f88f1953b8e63bdd rules_version=1 status=pass -->

No eligible decisions govern subsystems: none

## 2. Architectural Design

### Overview

FEAT-803 operates on the existing two-tier deployment architecture:

1. **Landing tier** — `landing/index.html` (standalone HTML with
   Inter/JetBrains Mono, Font Awesome, Prism) serves at the site root
   (`phenobarbital.github.io/ai-parrot/`).
2. **Docs tier** — mkdocs (Material theme) serves at `/docs/`
   (via `site_dir: site/docs`).
3. **Overlay** — `.github/workflows/docs.yml` builds mkdocs, then runs
   `cp -R landing/. site/` to place the landing page at root.

The redesign is a **content and theme refresh**, not a platform migration:

- **Landing tier**: full redesign from scratch — new layout, new copy, new
  visual design. Current sections (Hero, Packages, Features, Install,
  QuickStart, Concepts, Connectivity, Server, Architecture, Providers,
  Contributing) are replaced by a leaner, value-oriented structure.
- **Docs tier**: nav restructured from 14→6 sections; chapter overviews
  rewritten as concept introductions; 3–4 new tutorials added; theme
  refreshed with custom overrides (CSS, partials); Material stays.

### Component Diagram

```
phenobarbital.github.io/ai-parrot/
├── /                   ← landing/index.html  (REDESIGN — M1)
│   ├── css/style.css   ← landing/css/        (REDESIGN — M1)
│   └── js/main.js      ← landing/js/         (REDESIGN — M1)
│
└── /docs/              ← mkdocs build        (RESTRUCTURE — M3/M4/M5/M6)
    ├── index.md        ← concept hub         (M4)
    ├── getting-started ← surfaced in nav     (M3)
    ├── chapters/       ← 7 concept overviews (M4, kept 1:1)
    ├── tutorials/      ← NEW: 3–4 tutorials  (M6)
    ├── config.md       ← minimal config      (M5)
    ├── tools_quick.md  ← curated showcase    (M5)
    ├── branding/       ← +favicon, +social   (M2)
    └── overrides/      ← NEW: custom CSS     (M3)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `landing/index.html` | replaces | Full redesign, preserving the overlay pattern |
| `mkdocs.yml` | modifies | Nav collapse, theme refresh, custom_dir, plugin removal |
| `.github/workflows/docs.yml` | modifies | Remove mkdocstrings step, add requirements-docs.txt |
| `docs/chapters/*.md` | modifies | Rewrite 7 files as concept pages |
| `docs/index.md` | modifies | Rewrite as concept hub |
| GitHub Wiki | cross-links | Every chapter overview links to wiki; never duplicates |

### Data Models

N/A — no Python code, no data models.

### New Public Interfaces

N/A — content and design only.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Landing Page Redesign | yes | HTML/CSS/JS; sections and visual design fixed by spec | — |
| M2: Brand Identity | yes | Asset creation (favicon, social card); parrot icon as primary | — |
| M3: MkDocs Theme & Nav | yes | 6-section nav structure fixed; Material custom_dir pattern | — |
| M4: Content Hub & Chapters | yes | 7 concept overviews, 1:1 with wiki; hub layout fixed | — |
| M5: Page Improvements | yes | Minimal config block pattern; curated tool list | — |
| M6: Beginner Tutorials | yes | 4 tutorials fixed (chatbot, agent, tool, deployment); pattern in spec | — |
| M7: Build Pipeline | yes | requirements-docs.txt contents; workflow step removal | — |

### Module 1: Landing Page Redesign

- **Path**: `landing/index.html`, `landing/css/style.css`, `landing/js/main.js`
- **Responsibility**: Full redesign of the standalone landing page from scratch.
  New hero with parrot branding, streamlined value proposition, provider showcase,
  installation snippet, links to docs and wiki, community links.
- **Depends on**: M2 (uses the consolidated brand assets — favicon, logo)
- **Files**: all CREATE (full rewrite of existing files)

**Design requirements**:
- Keep Inter + JetBrains Mono fonts via Google Fonts CDN.
- Use Font Awesome 6 icons (already loaded).
- Adopt Material Design color tokens and spacing scale (§8 Q2) for visual
  consistency with the mkdocs Material theme (green primary palette, surface
  and on-surface tokens, 4/8/16/24/32 px spacing grid).
- Prism.js for syntax highlighting of code snippets.
- Mermaid for architecture diagram.
- Responsive layout (mobile-first).
- Dark/light theme support matching Material's `default`/`slate` schemes.
- Sections: Hero → Why AI-Parrot (3–4 cards) → Quick Install → Providers table → Links (Docs, Wiki, GitHub, PyPI).
- Clear CTA to `/docs/` and to the GitHub Wiki.
- Footer with GitHub, Issues, Discussions, PyPI links.

### Module 2: Brand Identity Unification

- **Path**: `docs/branding/`
- **Responsibility**: Consolidate brand identity around the parrot icon/logo.
  Create favicon and social card for OG tags.
- **Depends on**: none (independent workstream)
- **Files**:
  - CREATE: `docs/branding/favicon.ico` (derived from parrot.svg)
  - CREATE: `docs/branding/social-card.png` (1200×630, project name + tagline + parrot logo)

**Design requirements**:
- Primary icon: parrot (from `docs/branding/parrot.svg`), not robot
- Favicon: 32×32 + 16×16 from the parrot SVG
- Social card: used in OG meta tags on both landing and docs
- The 5 existing SVGs (`ai-parrot-wordmark-on-dark.svg`, `parrot-mono-dark.svg`,
  `parrot-mono-light.svg`, `parrot-transparent.png`, `parrot.svg`) are preserved

### Module 3: MkDocs Theme & Nav Restructuring

- **Path**: `mkdocs.yml`, `docs/overrides/`
- **Responsibility**: Collapse the 14-section nav to ~6 sections for the
  post-migration inventory. Add Material theme customization via `custom_dir`.
  Prepare for mkdocstrings removal (M9 — not executed by this feature).
- **Depends on**: none
- **Files**:
  - MODIFY: `mkdocs.yml` — rewrite `nav:` (lines 114–340), update `theme:` icon/logo,
    add `custom_dir: docs/overrides`
  - CREATE: `docs/overrides/` directory with custom CSS and partials

**Post-migration nav structure** (~6 sections):

```yaml
nav:
  - Home: index.md
  - Getting Started:
      - Installation: INSTALL.md
      - Configuration: config.md
      - Quick Start: getting-started.md
  - Concepts:
      - Foundations: chapters/foundations.md
      - LLM Clients: chapters/llm-clients.md
      - Bots & Agents: chapters/bots-agents.md
      - Memory & Knowledge: chapters/memory-knowledge.md
      - Knowledge Graph: chapters/knowledge-graph.md
      - Tools & RAG: chapters/tools-rag.md
      - Integrations: chapters/integrations.md
  - Tutorials:
      - Your First Chatbot: tutorials/first-chatbot.md
      - Your First Agent: tutorials/first-agent.md
      - Your First Tool: tutorials/first-tool.md
        - Deployment: tutorials/deployment.md
  - Guides:
      - CLI Agent Daemon: guides/cli-agent-daemon.md
      # other surviving guides from M7 classification
  - About:
      - Style Guide: STYLE_GUIDE.md
      - Branding: branding/
      - SDD Workflow: sdd/WORKFLOW.md
```

**Theme changes**:
- Replace `material/robot-happy-outline` icon with the parrot logo
- Add `custom_dir: docs/overrides` for custom CSS
- Keep green primary palette; landing page uses Material-adjacent tokens for consistency
- Add `extra` OG meta tags referencing `social-card.png`

### Module 4: Content Hub & Chapter Rewrites

- **Path**: `docs/index.md`, `docs/chapters/*.md`
- **Responsibility**: Rewrite docs landing as a concept-oriented hub with
  chapter cards. Rewrite 7 chapter overviews as concept introductions
  (what/why) with "deep dive in the Wiki →" CTAs. Keep 1:1 mapping with
  wiki sections.
- **Depends on**: none
- **Files**:
  - MODIFY: `docs/index.md` — full rewrite as concept hub
  - MODIFY: `docs/chapters/foundations.md`
  - MODIFY: `docs/chapters/llm-clients.md`
  - MODIFY: `docs/chapters/bots-agents.md`
  - MODIFY: `docs/chapters/memory-knowledge.md`
  - MODIFY: `docs/chapters/knowledge-graph.md`
  - MODIFY: `docs/chapters/tools-rag.md`
  - MODIFY: `docs/chapters/integrations.md`

**Chapter overview pattern** (each ~300–500 words):
```markdown
# <Chapter Name>

<2–3 paragraphs explaining what this subsystem is and why it matters.
Written for a newcomer who has never seen the codebase.>

## Key Concepts

- **Concept A**: one-sentence definition
- **Concept B**: one-sentence definition

## What You Can Build

<2–3 concrete use cases / examples>

## Deep Dive

For API reference, class signatures, and implementation details, see the
[<Chapter Name> section in the Wiki](https://github.com/phenobarbital/ai-parrot/wiki/<page>).
```

### Module 5: Page Improvements

- **Path**: `docs/config.md`, `docs/tools_quick.md`
- **Responsibility**: Make config.md newcomer-friendly with a "minimal config"
  section. Curate tools_quick.md to showcase 3–4 tools with the full catalog
  linking to the wiki.
- **Depends on**: none
- **Files**:
  - MODIFY: `docs/config.md` — add "Minimal Configuration" section at top
  - MODIFY: `docs/tools_quick.md` — curate to 3–4 showcase tools

### Module 6: Beginner Tutorials

- **Path**: `docs/tutorials/`
- **Responsibility**: Create 3–4 beginner tutorials with step-by-step code
  walkthroughs. Each tutorial builds a working example from scratch.
- **Depends on**: M3 (tutorials must appear in the nav — shared file: `mkdocs.yml`)
- **Files**:
  - CREATE: `docs/tutorials/first-chatbot.md`
  - CREATE: `docs/tutorials/first-agent.md`
  - CREATE: `docs/tutorials/first-tool.md`
  - CREATE: `docs/tutorials/deployment.md`

**Tutorial pattern** (each ~800–1200 words):
```markdown
# Your First <Thing>

> **Time**: ~10 minutes
> **Prerequisites**: AI-Parrot installed, API key configured

## What You'll Build

<One paragraph describing the end result>

## Step 1: Set Up

<Code block with imports and config>

## Step 2: Define <components>

<Code block with the core logic>

## Step 3: Run It

<Code block running the example>

## What's Next

- Link to related tutorial
- Link to wiki section for deeper understanding
```

### Module 7: Build Pipeline Update

- **Path**: `requirements-docs.txt`, `.github/workflows/docs.yml`
- **Responsibility**: Declare docs build dependencies explicitly. Update the
  CI workflow to use the requirements file and remove the mkdocstrings
  editable install step (which M9 makes unnecessary).
- **Depends on**: M3 (mkdocstrings removal from mkdocs.yml must happen first
  or simultaneously — otherwise the build breaks without the editable install)
- **Files**:
  - CREATE: `requirements-docs.txt`
  - MODIFY: `.github/workflows/docs.yml` — update install step, remove
    editable `pip install -e` step

**requirements-docs.txt contents** (post-M9):
```
mkdocs-material>=9.5
mkdocs-glightbox
pymdown-extensions
```

---

## 4. Test Specification

### Unit Tests

N/A — no Python code to test.

### Integration Tests

| Test | Description |
|---|---|
| `mkdocs build` | The site builds successfully after all changes |
| Landing page renders | `landing/index.html` loads without 404s for CSS/JS/fonts |
| Cross-links valid | Wiki links in chapter overviews resolve to real wiki pages |

### Validation Contract

none — fallback

### Test Data / Fixtures

N/A

---

## 5. Acceptance Criteria

- [x] **AC1**: Landing page (`landing/index.html`) is a complete redesign with hero,
  value proposition, provider showcase, and CTAs to docs and wiki.
  *Resolved in proposal*: redesign from scratch, not iterate.
- [ ] **AC2**: MkDocs nav has ≤6 top-level sections (down from 14).
- [ ] **AC3**: All 7 chapter overview pages rewritten as concept introductions
  with wiki cross-links. Kept 1:1 with wiki sections.
  *Resolved in proposal*: keep 1:1, not consolidate.
- [ ] **AC4**: 3–4 beginner tutorials exist under `docs/tutorials/`.
  *Resolved in proposal*: 3–4 tutorials in scope.
- [ ] **AC5**: `favicon.ico` and `social-card.png` exist in `docs/branding/`.
- [ ] **AC6**: `mkdocs build` succeeds with no errors.
- [ ] **AC7**: `requirements-docs.txt` exists and the CI workflow uses it.
- [ ] **AC8**: `docs/getting-started.md` appears in the mkdocs nav.
- [ ] **AC9**: `docs/config.md` has a "Minimal Configuration" section at top.
- [ ] **AC10**: `docs/tools_quick.md` showcases 3–4 tools with a link to the wiki
  for the full catalog.
- [ ] **AC11**: No content is duplicated between Pages and Wiki — cross-links only.
- [ ] **AC12**: Landing page overlay pattern (`cp -R landing/. site/`) still works.
- [ ] **AC13**: The two-tier site renders correctly on mobile.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This is content/design work with no Python code. The contract below
> documents the file paths, structures, and patterns that must be
> respected during implementation.

### Verified File Structure

```
landing/
├── index.html          # 698 lines, standalone HTML — verified: landing/index.html
├── css/style.css       # landing styles — verified: landing/css/
└── js/main.js          # landing JS — verified: landing/js/

docs/
├── index.md            # mkdocs landing — verified: docs/index.md
├── getting-started.md  # 27KB, hidden from nav — verified: docs/getting-started.md
├── config.md           # 338+ lines, flat env var dump — verified: docs/config.md
├── tools_quick.md      # 522+ lines, full tool catalog — verified: docs/tools_quick.md
├── INSTALL.md          # installation guide — verified: docs/INSTALL.md
├── STYLE_GUIDE.md      # code style guide — verified: docs/STYLE_GUIDE.md
├── chapters/           # 7 overview files — verified: docs/chapters/
│   ├── foundations.md
│   ├── llm-clients.md
│   ├── bots-agents.md
│   ├── memory-knowledge.md
│   ├── knowledge-graph.md
│   ├── tools-rag.md
│   └── integrations.md
├── branding/           # 5 SVGs + 1 PNG — verified: docs/branding/
│   ├── ai-parrot-wordmark-on-dark.svg
│   ├── parrot-mono-dark.svg
│   ├── parrot-mono-light.svg
│   ├── parrot-transparent.png
│   └── parrot.svg
├── overrides/          # DOES NOT EXIST — will be created
└── tutorials/          # DOES NOT EXIST — will be created

mkdocs.yml              # 340 lines — verified: mkdocs.yml
.github/workflows/docs.yml  # 61 lines — verified: .github/workflows/docs.yml
requirements-docs.txt   # DOES NOT EXIST — will be created
```

### Existing Configuration (mkdocs.yml)

```yaml
# Theme — verified: mkdocs.yml:17-49
theme:
  name: material
  icon:
    logo: material/robot-happy-outline    # line 48 — TO BE REPLACED with parrot
  palette:
    - scheme: default
      primary: green                       # line 36
    - scheme: slate
      primary: green                       # line 42

# Plugins — verified: mkdocs.yml:51-72
plugins:
  - search
  - glightbox
  - mkdocstrings:                          # line 54 — REMOVED by M9
      default_handler: python

# Nav — verified: mkdocs.yml:114-340
nav:                                       # line 114 — FULL REWRITE by M3
  - Home: index.md
  # ... 14 sections, 175+ entries
```

### Existing Workflow (.github/workflows/docs.yml)

```yaml
# verified: .github/workflows/docs.yml:35-46
- name: Install doc tooling               # line 35 — MODIFY: use requirements-docs.txt
  run: pip install -r requirements-docs.txt

- name: Install ai-parrot (for mkdocstrings imports)  # line 38 — REMOVE after M9
  run: pip install -e packages/ai-parrot || echo "..."

- name: Build site                         # line 42 — KEEP
  run: mkdocs build

- name: Overlay static landing page at site root  # line 45 — KEEP (critical)
  run: cp -R landing/. site/               # line 46
```

### Landing Page External Dependencies

```html
<!-- verified: landing/index.html:11-25 -->
<!-- Fonts: Inter + JetBrains Mono via Google Fonts -->
<!-- Icons: Font Awesome 6.4.0 via cdnjs -->
<!-- Syntax: Prism 1.29.0 via cdnjs -->
<!-- Diagrams: Mermaid 10.9.0 via cdnjs -->
```

### Does NOT Exist (Anti-Hallucination)

- ~~`docs/overrides/`~~ — directory does not exist; must be created by M3
- ~~`docs/tutorials/`~~ — directory does not exist; must be created by M6
- ~~`requirements-docs.txt`~~ — file does not exist; must be created by M7
- ~~`docs/branding/favicon.ico`~~ — does not exist; must be created by M2
- ~~`docs/branding/social-card.png`~~ — does not exist; must be created by M2
- ~~`mkdocs.yml` `custom_dir`~~ — not configured; must be added by M3
- ~~`docs/index.md` wiki cross-links~~ — none exist; must be added by M4

### Edit Sites (Blueprint Anchors)

Verified against: `285e7605df`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `landing/index.html` | REWRITE | — (full file rewrite) | — | — |
| `landing/css/style.css` | REWRITE | — (full file rewrite) | — | — |
| `landing/js/main.js` | REWRITE | — (full file rewrite) | — | — |
| `mkdocs.yml` | MODIFY | `nav:` | `mkdocs.yml:114` | 1 |
| `mkdocs.yml` | MODIFY | `  - mkdocstrings:` | `mkdocs.yml:54` | 1 |
| `mkdocs.yml` | MODIFY | `    logo: material/robot-happy-outline` | `mkdocs.yml:48` | 1 |
| `docs/index.md` | REWRITE | — (full file rewrite) | — | — |
| `docs/chapters/foundations.md` | REWRITE | — (full file rewrite) | — | — |
| `docs/chapters/llm-clients.md` | REWRITE | — (full file rewrite) | — | — |
| `docs/chapters/bots-agents.md` | REWRITE | — (full file rewrite) | — | — |
| `docs/chapters/memory-knowledge.md` | REWRITE | — (full file rewrite) | — | — |
| `docs/chapters/knowledge-graph.md` | REWRITE | — (full file rewrite) | — | — |
| `docs/chapters/tools-rag.md` | REWRITE | — (full file rewrite) | — | — |
| `docs/chapters/integrations.md` | REWRITE | — (full file rewrite) | — | — |
| `docs/config.md` | MODIFY | `# AI-Parrot Configuration Guide` | `config.md:1` | 1 |
| `docs/tools_quick.md` | MODIFY | `# AI-Parrot Tools Quick Reference Guide` | `tools_quick.md:1` | 1 |
| `.github/workflows/docs.yml` | MODIFY | `- name: Install ai-parrot (for mkdocstrings imports)` | `docs.yml:38` | 1 |
| `docs/overrides/main.css` | CREATE | — | — | — |
| `docs/tutorials/first-chatbot.md` | CREATE | — | — | — |
| `docs/tutorials/first-agent.md` | CREATE | — | — | — |
| `docs/tutorials/first-tool.md` | CREATE | — | — | — |
| `docs/tutorials/deployment.md` | CREATE | — | — | — |
| `requirements-docs.txt` | CREATE | — | — | — |
| `docs/branding/favicon.ico` | CREATE | — | — | — |
| `docs/branding/social-card.png` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Two-surface doctrine**: Pages = informative (what/why/guides), Wiki =
  technical reference (classes, args, parameters). Never copy — always
  cross-link. [F011]
- **Landing overlay**: the workflow runs `cp -R landing/. site/` to overlay
  the landing page at the site root. The mkdocs build goes into `site/docs/`.
  This pattern must be preserved. [F010]
- **Material custom_dir**: use `docs/overrides/` with the `custom_dir`
  config key for CSS and partial overrides. Do not modify Material's
  installed files.
- **Chapter 1:1 mapping**: each `docs/chapters/<name>.md` maps to one
  wiki section. The overview is a concept introduction; the wiki holds the
  technical reference. [F004]

### Known Risks / Gotchas

- **FEAT-801 + M9 merge gate**: this feature cannot merge until FEAT-801
  (all 8 tasks) AND M9 (mkdocstrings cut-over) have landed. The nav
  structure assumes the post-migration inventory — merging before that
  would leave nav entries pointing to moved files. [F011]
- **Wiki URLs not yet stable**: the wiki is being populated by FEAT-801.
  Cross-links in chapter overviews should use a consistent URL pattern
  (`https://github.com/phenobarbital/ai-parrot/wiki/<Page-Name>`) but the
  exact page names won't be final until FEAT-801 completes.
- **mkdocstrings removal timing**: M3 prepares the nav for a world without
  mkdocstrings, but does NOT remove the plugin from `mkdocs.yml` — that's
  M9's job. The CI workflow's editable install step should only be removed
  AFTER M9 has removed the plugin from mkdocs.yml.
- **Favicon generation**: generating `.ico` from SVG requires an external
  tool (ImageMagick, realfavicongenerator.net, or manual export). The
  tutorial author must document which tool was used.
- **Landing page font loading**: Inter and JetBrains Mono are loaded from
  Google Fonts CDN. Consider self-hosting for privacy and performance.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `mkdocs-material` | `>=9.5` | Material theme for mkdocs |
| `mkdocs-glightbox` | `latest` | Image lightbox plugin |
| `pymdown-extensions` | `latest` | Markdown extensions (tabs, details, emoji) |

No new Python dependencies. No new npm packages.

### Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-803-github-pages-informative-site`.
- **Module dependency graph**: M2→M1 (landing uses brand assets), M3→M6 (tutorials need nav), M3→M7 (workflow needs mkdocs.yml changes). All other modules are independent.
- **Shared files**: `mkdocs.yml` is modified by M3 and referenced by M6 — serialize M6 after M3.
- **Exclusive resources**: none — all changes are documentation files.
- **Cross-feature dependencies**: FEAT-801 (all 8 tasks) + M9 must merge first. This feature's branch can be developed in parallel but must not merge until that gate is clear.

---

## Consequences

<!-- decision-audit: input_digest=sha256:cb75788f6f3023ef176f86f7e20c0dd266189d232763feba1962a5144de97efb evaluation_digest=sha256:d14ca93e985ee2e5806b5a5d864b587338d0dbd56b13cee9f88f1953b8e63bdd rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/github-pages-informative-site.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: not recorded
- Unmapped tags: branding, docs, github-pages, landing-page, mkdocs, tutorials
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "branding",
      "docs",
      "github-pages",
      "landing-page",
      "mkdocs",
      "tutorials"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/github-pages-informative-site.spec.md"
    }
  ],
  "evaluation_digest": "sha256:d14ca93e985ee2e5806b5a5d864b587338d0dbd56b13cee9f88f1953b8e63bdd",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:cb75788f6f3023ef176f86f7e20c0dd266189d232763feba1962a5144de97efb",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

### Resolved (carried from proposal)

- [x] **Should the landing page be redesigned from scratch or iterated?** — *Resolved in proposal*: Redesign from scratch. New layout, new sections, new copy.
- [x] **How many beginner tutorials in scope?** — *Resolved in proposal*: 3–4 tutorials (first chatbot, first agent, first tool, plus one additional).
- [x] **Consolidate chapter overviews 7→5 or keep 1:1?** — *Resolved in proposal*: Keep 1:1 with wiki sections.
- [x] **Q1: Which 4th tutorial?** — *Resolved in spec*: Deployment guide — deploy an AI-Parrot agent as a service (server setup, aiohttp handler, production config).
- [x] **Q2: Landing page design system?** — *Resolved in spec*: Material-adjacent tokens — keep Inter + JetBrains Mono + Font Awesome but adopt Material Design color tokens and spacing scale for visual consistency with the mkdocs Material theme.

### Unresolved

None — all questions resolved.

---

## 9. Design Research Cross-Check

Status: skipped (proposal status is `review`, not `accepted` — precondition not met)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-04 | Jesus Lara | Initial draft from FEAT-803 proposal |
| 0.2 | 2026-11-05 | Jesus Lara | Resolve Q1 (4th tutorial → deployment) and Q2 (design system → Material-adjacent tokens); all modules now delegation-eligible |
