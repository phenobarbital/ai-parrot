# FC-008: Style guide and theme configuration

## Query
Read `docs/STYLE_GUIDE.md` first 30 lines; check for `docs/overrides/`

## Result
**Style Guide**: `STYLE_GUIDE.md` is a code style guide (Python conventions, naming, docstrings), NOT a documentation style guide. It covers PEP 8, Black formatting, type hints, naming conventions. Stays on Pages.

**Theme overrides**: No `docs/overrides/` directory exists. The site uses stock Material for MkDocs theme with no custom templates, partials, or CSS overrides.

**Theme config** (from mkdocs.yml:17-50): Material theme with:
- `navigation.tabs` + `navigation.tabs.sticky` — top-level tabs
- Green primary/accent palette with dark mode toggle
- Robot icon (`material/robot-happy-outline`) as logo
- GitHub social links
- No custom CSS, no custom JS, no analytics

## Citations
- docs/STYLE_GUIDE.md:1-30 — code style, not docs style
- mkdocs.yml:17-50 — theme configuration

## Notes
The lack of custom overrides means the site is fully stock Material theme. A redesign could add custom CSS, hero sections, and social cards without conflicts. The green palette is the project's brand color.
