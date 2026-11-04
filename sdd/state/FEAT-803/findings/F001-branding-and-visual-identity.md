# F001: Branding and visual identity

Merged from: FC-001, FG-002, FW-003

## Summary
Five branding assets exist under `docs/branding/` (SVGs ~230K each + one 1.4M PNG).
Brand identity is **fragmented**: landing page uses Font Awesome `fa-solid fa-parrot`,
mkdocs uses Material's `material/robot-happy-outline`, and the custom SVG logos are unused
in either surface. No favicon, social card, or hero image exists. Branding has been
stable since June 2026 (1 commit).

## Citations
- docs/branding/parrot.svg — primary logo (232K)
- docs/branding/ai-parrot-wordmark-on-dark.svg — wordmark (237K)
- docs/branding/parrot-mono-dark.svg, parrot-mono-light.svg — monochrome variants (233K each)
- docs/branding/parrot-transparent.png — raster logo (1.4M)
- landing/index.html:35 — `<i class="fa-solid fa-parrot"></i>` icon usage
- mkdocs.yml:48 — `logo: material/robot-happy-outline`
- 455ca85609 — single branding commit in the period

## Notes
FEAT-803 should unify visual identity: use the custom SVG logos consistently, add a
favicon, create a social card (OG tags), and consider a hero image for the landing.
