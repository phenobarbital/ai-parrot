# F010: Deployment workflow and existing landing page

From: FW-002

## Summary
**Two-tier structure already exists**:
- `landing/index.html` serves at the site ROOT (`phenobarbital.github.io/ai-parrot/`)
- mkdocs serves at `/docs/` (via `site_dir: site/docs`)
- `.github/workflows/docs.yml` builds mkdocs then overlays: `cp -R landing/. site/`

The landing page is standalone HTML with Inter/JetBrains Mono fonts, Font Awesome icons,
Prism syntax highlighting. Sections: Hero, Features, Install, Quick Start, Architecture,
Providers. Links to `docs/` for full documentation.

Trigger: push to `main` when docs/**, landing/**, mkdocs.yml, requirements-docs.txt,
packages/ai-parrot/src/parrot/**, or the workflow change.

## Citations
- wiki:file:.github/workflows/docs.yml (score=1.00) — full workflow
- landing/index.html:1-60 — standalone HTML landing
- landing/css/style.css — landing styles
- landing/js/main.js — landing JS

## Notes
FEAT-803 should preserve this two-tier pattern. The landing page IS the informative front
door; the mkdocs /docs/ becomes guides/concepts. After M9, the mkdocs build no longer
needs `pip install -e packages/ai-parrot`. The `requirements-docs.txt` path in the
workflow trigger suggests a file that doesn't exist yet (see F009).
