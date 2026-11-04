# FW-003: Branding assets inventory

## Query
`wikitoolkit query "branding assets and visual identity"`
+ `find docs/branding/ -type f`

## Result
Wiki query returned no direct branding page — the term "branding" in the wiki refers
to planogram/retail domain concepts, not the project's own visual identity.

Direct file scan found 5 branding assets under `docs/branding/`:
- `ai-parrot-wordmark-on-dark.svg` — wordmark for dark backgrounds
- `parrot-mono-dark.svg` — monochrome logo, dark variant
- `parrot-mono-light.svg` — monochrome logo, light variant
- `parrot-transparent.png` — logo with transparent background (raster)
- `parrot.svg` — primary logo (vector)

The landing page uses Font Awesome's `fa-solid fa-parrot` icon, not the custom SVG logos.
The mkdocs theme uses Material's `material/robot-happy-outline` icon as its logo.

## Citations
- docs/branding/parrot.svg — primary logo
- docs/branding/ai-parrot-wordmark-on-dark.svg — wordmark
- docs/branding/parrot-mono-dark.svg, parrot-mono-light.svg — monochrome variants
- docs/branding/parrot-transparent.png — raster logo
- landing/index.html:35 — `<i class="fa-solid fa-parrot"></i>` icon usage
- mkdocs.yml:48 — `logo: material/robot-happy-outline`

## Notes
There's a brand inconsistency: the landing page uses FA parrot icon, mkdocs uses Material
robot icon, and custom SVG logos exist but aren't used in either surface. FEAT-803 should
unify the visual identity.
