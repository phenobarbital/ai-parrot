# FC-009: Site size and build dependencies

## Query
File counts, size, and docs build dependencies

## Result
**Size**: 339 markdown files, 7 images (png/jpg/svg/gif), 9.9 MB total under `docs/`.

**Build dependencies**: No `requirements-docs.txt` file exists. No `docs` extra in the workspace `pyproject.toml` or core `pyproject.toml`. mkdocs/mkdocstrings are not declared as project dependencies — they appear to be installed globally or via an undeclared mechanism.

**Installed versions**: `pip show mkdocs-material mkdocstrings` returned exit 1 — not installed in the current venv. The docs build runs outside the project venv.

## Citations
- docs/:* — 339 .md files, 7 image files, 9.9MB total
- pyproject.toml — no docs extra found
- mkdocs.yml:51-72 — mkdocstrings plugin configured but deps not declared

## Notes
The missing `requirements-docs.txt` is a gap the redesign should fix — declare docs build dependencies so CI and contributors can reproduce the build. After FEAT-801 M9 removes mkdocstrings, the dependency list shrinks to just `mkdocs-material` + extensions.
