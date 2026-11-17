# FG-002: Branding assets and changes

## Query
`git log --oneline --since="2026-06-01" -- docs/branding/`

## Result
Only 1 commit since June 2026: `455ca85609` — "Update README with improved branding and structure". The branding directory contains 5 assets:
- `ai-parrot-wordmark-on-dark.svg` (237K)
- `parrot-mono-dark.svg` (233K)
- `parrot-mono-light.svg` (233K)
- `parrot-transparent.png` (1.4M)
- `parrot.svg` (232K)

Branding has been stable for months — no recent visual identity work.

## Citations
- docs/branding/ — 5 logo/wordmark assets (SVG + PNG)
- 455ca85609 — single branding commit in the period

## Notes
Assets are available for use in a redesigned landing page. No favicon or social-card images exist in this directory. The mkdocs theme uses `material/robot-happy-outline` as the logo icon rather than these custom assets.
