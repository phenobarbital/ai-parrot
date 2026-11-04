# TASK-5196: Landing page full redesign

**Feature**: FEAT-803 — GitHub Pages Informative Site Redesign
**Spec**: `sdd/specs/github-pages-informative-site.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-5195
**Assigned-to**: unassigned

---

## Context

`landing/index.html` is the site root (overlaid by `cp -R landing/. site/` in `.github/workflows/docs.yml:46`). It is redesigned from scratch as a lean product front door (spec M1, AC1, AC12, AC13). Implements spec §3 Module 1 (Landing Page Redesign).

**Merge gate**: FEAT-801 (all 8 tasks) and its M9 mkdocstrings cut-over have NOT landed on dev yet (verified at `0b8c3a1fa2`: `mkdocs.yml:54` still has `- mkdocstrings:`, `requirements-docs.txt` still lists `mkdocstrings[python]>=1.0.8`, `.github/workflows/docs.yml:38` still has the editable install). This task may be developed now but the feature must not merge until that gate is clear. Never remove mkdocstrings yourself — M9 owns it.

---

## Scope

- Rewrite `landing/index.html` with sections, in order: Hero → Why AI-Parrot (3–4 cards) → Quick Install → Providers table → Links (Docs, Wiki, GitHub, PyPI) → Footer (GitHub, Issues, Discussions, PyPI).
- Rewrite `landing/css/style.css`: mobile-first, Material-adjacent tokens (green primary, surface/on-surface), 4/8/16/24/32 px spacing scale, light/dark via `prefers-color-scheme` + a toggle mirroring Material `default`/`slate`.
- Rewrite `landing/js/main.js`: theme toggle, mobile nav, copy-to-clipboard for the install snippet, Mermaid init.
- Docs CTA is `href="docs/"` (relative); wiki CTA is `https://github.com/phenobarbital/ai-parrot/wiki`. Never root-absolute `/docs/`.
- Favicon and OG tags: `<link rel="icon" href="docs/branding/favicon.ico">`, `og:image` absolute URL `https://phenobarbital.github.io/ai-parrot/docs/branding/social-card.png`.
- Write `tests/docs_site/test_landing_page.py`.

**NOT in scope**: mkdocs.yml, anything under docs/ (other tasks); changing the overlay step in the workflow.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `landing/index.html` | MODIFY | full rewrite |
| `landing/css/style.css` | MODIFY | full rewrite |
| `landing/js/main.js` | MODIFY | full rewrite |
| `tests/docs_site/test_landing_page.py` | CREATE | static landing checks |

---

## Codebase Contract (Anti-Hallucination)

### Verified External Dependencies (keep these CDNs/versions)
```html
<!-- verified: landing/index.html:11-25 -->
<!-- Inter + JetBrains Mono via Google Fonts; Font Awesome 6.4.0, Prism 1.29.0, Mermaid 10.9.0 via cdnjs -->
```
### Verified Overlay
```yaml
# .github/workflows/docs.yml:45-46
- name: Overlay static landing page at site root
  run: cp -R landing/. site/
```
The docs tier is built into `site/docs/` (`site_dir: site/docs` in mkdocs.yml), so from the landing root the docs are at `docs/`.

### Does NOT Exist
- ~~`docs/overrides/`~~ — does not exist on dev; created by TASK-5197
- ~~`docs/tutorials/`~~ — does not exist on dev; created by TASK-5201 / TASK-5202
- ~~favicon / social-card raster assets~~ — do not exist yet on dev; created by TASK-5195
- ~~`tests/docs_site/`~~ — does not exist; each task creates its own test module there (no `__init__.py`, no `conftest.py`)
- ~~Wiki page slugs derived from section labels~~ — section labels (e.g. "Bots & Agents") are NOT page slugs; take targets from `wiki/_index.yaml` / the released `techwiki-manifest.json`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "landing/index.html",
      "action": "MODIFY"
    },
    {
      "path": "landing/css/style.css",
      "action": "MODIFY"
    },
    {
      "path": "landing/js/main.js",
      "action": "MODIFY"
    },
    {
      "path": "tests/docs_site/test_landing_page.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Content/design only — no product Python code. Test modules are plain-pytest, filesystem-only (no `parrot` import needed except where stated).
- Two-surface doctrine: Pages = what/why; Wiki = technical reference. Cross-link, never copy (AC11).


---

## Implementation Blueprint

### Steps (in order)
1. Read the current three files to reuse provider names and install commands (copy facts, not layout) — *why*: avoid inventing providers.
2. Write `index.html` section skeleton with ids `hero`, `why`, `install`, `providers`, `links`, `footer` — *why*: tests target these ids.
3. Write CSS tokens on `:root` and override them under `[data-theme="dark"]` and `@media (prefers-color-scheme: dark)` — *why*: matches Material schemes.
4. Write JS; keep it dependency-free besides Prism/Mermaid — *why*: static overlay, no build step.
5. Write the test module.

### `landing/index.html` (MODIFY — full rewrite)
```html
<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI-Parrot — Async-first AI Agents for Python</title>
  <link rel="icon" href="docs/branding/favicon.ico">
  <meta property="og:title" content="AI-Parrot">
  <meta property="og:image" content="https://phenobarbital.github.io/ai-parrot/docs/branding/social-card.png">
  <!-- FILL IN: og:description, twitter:card, fonts/FA/Prism/Mermaid tags at the verified versions -->
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <header id="hero"><!-- FILL IN: logo docs/branding/parrot.svg, headline, CTAs href="docs/" + wiki --></header>
  <section id="why"><!-- FILL IN: 3–4 value cards --></section>
  <section id="install"><!-- FILL IN: uv pip install ai-parrot snippet with copy button --></section>
  <section id="providers"><!-- FILL IN: providers table (OpenAI, Anthropic, Google, Groq, VertexAI, HuggingFace, ...) --></section>
  <section id="links"><!-- FILL IN: Docs, Wiki, GitHub, PyPI --></section>
  <footer id="footer"><!-- FILL IN: GitHub, Issues, Discussions, PyPI --></footer>
  <script src="js/main.js" defer></script>
</body>
</html>
```
### `landing/css/style.css` / `landing/js/main.js` (MODIFY — full rewrite)
FILL IN entirely — bounded by spec M1 design requirements; no file over the readability of ~400 lines.

### `tests/docs_site/test_landing_page.py` (CREATE)
```python
"""FEAT-803 AC1/AC12: landing page structure and project-relative links."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "landing" / "index.html").read_text(encoding="utf-8")


def test_required_sections_present() -> None:
    for section_id in ("hero", "why", "install", "providers", "links", "footer"):
        assert f'id="{section_id}"' in HTML, section_id


def test_docs_cta_is_project_relative() -> None:
    assert 'href="docs/"' in HTML
    assert 'href="/docs' not in HTML


def test_wiki_cta_and_branding() -> None:
    assert "github.com/phenobarbital/ai-parrot/wiki" in HTML
    assert "docs/branding/favicon.ico" in HTML
    assert "social-card.png" in HTML
    # FILL IN: assert every local href/src (css/, js/, docs/branding/) resolves to a file in landing/ or docs/
```
### FILL IN checklist
- [ ] Copy (hero, cards) — bounded by AC1
- [ ] CSS tokens + responsive breakpoints — bounded by AC13
- [ ] Local link resolution test

---

## Acceptance Criteria

- [ ] Landing is a complete redesign with hero, value cards, install, providers, links (AC1)
- [ ] Docs CTA uses `href="docs/"`; no root-absolute `/docs` (spec M1)
- [ ] Renders at 360 px width with no horizontal scroll (AC13 — check manually, note in Completion Note)
- [ ] Overlay still works: only files under `landing/` changed (AC12)
- [ ] `pytest tests/docs_site/test_landing_page.py -q` passes

## Validation Commands

- `pytest tests/docs_site/test_landing_page.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug github-pages-informative-site --feature-id FEAT-803`).
2. Read the spec; check every Depends-on is `done` in `sdd/tasks/index/github-pages-informative-site.json`.
3. Verify the Codebase Contract; fix stale entries first.
4. Implement from the blueprint, completing every FILL IN.
5. Run the Validation Commands; commit only listed files.
6. `parrot sdd task close TASK-5196 github-pages-informative-site verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
