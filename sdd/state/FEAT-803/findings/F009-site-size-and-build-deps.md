# F009: Site size and build dependencies

From: FC-009

## Summary
339 markdown files, 7 images, 9.9 MB total under `docs/`. No `requirements-docs.txt`
file, no `docs` extra in pyproject.toml. mkdocs/mkdocstrings appear installed globally
or via an undeclared mechanism — not in the project venv.

## Citations
- docs/:* — 339 .md files, 7 images, 9.9MB total
- pyproject.toml — no docs extra found
- mkdocs.yml:51-72 — mkdocstrings plugin configured but deps not declared

## Notes
The redesign should declare docs build dependencies (requirements-docs.txt or a
pyproject extra). After M9 removes mkdocstrings, the list shrinks to mkdocs-material
+ extensions. Post-migration, page count drops to ~30-40 pages.
