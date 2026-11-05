# FW-002: GitHub Pages deployment workflow and landing page overlay

## Query
`wikitoolkit query "GitHub Pages deployment and documentation build"`
+ `wikitoolkit page "file:.github/workflows/docs.yml"`

## Result
The docs workflow (`.github/workflows/docs.yml`) triggers on push to `main` when
`docs/**`, `landing/**`, `mkdocs.yml`, `requirements-docs.txt`, `packages/ai-parrot/src/parrot/**`,
or the workflow itself change. It:
1. Builds mkdocs site (`mkdocs build`) into `site/`
2. **Overlays a static landing page**: `cp -R landing/. site/` — this places `landing/index.html`
   at the site ROOT, so `phenobarbital.github.io/ai-parrot/` serves the landing page while
   `phenobarbital.github.io/ai-parrot/docs/` serves the mkdocs site (because `site_dir: site/docs`).
3. Deploys via `actions/deploy-pages@v5`.

The landing page (`landing/index.html`) is a standalone HTML page with Inter/JetBrains Mono fonts,
Font Awesome icons, Prism syntax highlighting. Sections: Hero, Features, Install, Quick Start,
Architecture, Providers. Links to `docs/` for the full documentation.

Critical: `pip install -e packages/ai-parrot` is needed for mkdocstrings imports (with
`continue-on-error: true`).

## Citations
- wiki:file:.github/workflows/docs.yml (score=1.00) — full workflow content
- landing/index.html:1-60 — standalone HTML landing
- landing/css/style.css — landing styles
- landing/js/main.js — landing JS

## Notes
The two-tier structure (landing at root, mkdocs at /docs/) is already in place.
FEAT-803 redesign should preserve this pattern — the landing page IS the informative front door,
and the mkdocs /docs/ subdirectory becomes the guides/concepts reference.
After M9 removes mkdocstrings, the mkdocs build no longer needs `pip install -e packages/ai-parrot`.
