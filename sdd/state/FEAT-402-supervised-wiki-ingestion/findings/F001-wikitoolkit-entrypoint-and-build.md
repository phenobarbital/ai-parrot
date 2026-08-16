# F001 — `wikitoolkit` entry point and the unsupervised `build` command

- `packages/ai-parrot/pyproject.toml:110-115` — `[project.scripts]`:
  `wikitoolkit = "parrot.knowledge.wiki.cli:main"` (also `parrot-graphindex`).
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:606-738` — `build`
  command. Docstring: "Deterministic and offline: scans source files
  (respecting .gitignore), extracts summaries/API outlines, and writes pages +
  typed edges into the wiki retrieval plane."
- `build` calls `scan_repository(...)` then `_ingest_files(...)`; **no LLM, no
  content evaluation** anywhere in the path. Confirms the request's premise:
  today `wikitoolkit build` is 100% unsupervised ingestion.

Method: read of cli.py 596-775; grep of pyproject.
