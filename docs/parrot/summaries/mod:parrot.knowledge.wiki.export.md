---
type: Wiki Summary
title: parrot.knowledge.wiki.export
id: mod:parrot.knowledge.wiki.export
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OKF v0.1 bundle export for the LLM Wiki (export-only boundary).
relates_to:
- concept: class:parrot.knowledge.wiki.export.WikiExportReport
  rel: defines
- concept: func:parrot.knowledge.wiki.export.category_dir
  rel: defines
- concept: func:parrot.knowledge.wiki.export.export_okf_bundle
  rel: defines
- concept: func:parrot.knowledge.wiki.export.generate_index
  rel: defines
- concept: func:parrot.knowledge.wiki.export.okf_type
  rel: defines
- concept: func:parrot.knowledge.wiki.export.page_frontmatter
  rel: defines
- concept: mod:parrot.knowledge.okf.utils
  rel: references
- concept: mod:parrot.knowledge.wiki.store
  rel: references
---

# `parrot.knowledge.wiki.export`

OKF v0.1 bundle export for the LLM Wiki (export-only boundary).

The wiki's internal representation is the machine-first
:class:`WikiStore` SQLite plane; OKF markdown is generated **lazily and
only at export time** as an interchange projection, never read back on
the retrieval path.

Bundle layout (Google OKF v0.1 — markdown files with YAML frontmatter,
one concept per file, ``type`` as the only required field)::

    <output_dir>/
    ├── index.md                 # root catalog of exported pages
    ├── summaries/<id>.md
    ├── entities/<id>.md
    └── <category>s/<id>.md      # one directory per page category

Wiki categories map onto the ``ConceptType.WIKI_*`` vocabulary where a
member exists; other categories export their title-cased raw string —
OKF types are producer-defined, so this remains conformant.

## Classes

- **`WikiExportReport(BaseModel)`** — Result of an OKF bundle export.

## Functions

- `def okf_type(category: str) -> str` — Map a wiki category to an OKF ``type`` string.
- `def category_dir(category: str) -> str` — Directory name for a category (naive English plural, lowercase).
- `def page_frontmatter(page: dict[str, Any], relates_to: list[dict[str, str]]) -> str` — Render OKF frontmatter for one page (deterministic key order).
- `def generate_index(wiki_name: str, entries: list[tuple[str, str, str]]) -> str` — Render the root ``index.md`` (title, relative path, summary).
- `async def export_okf_bundle(store: BaseWikiStore, output_dir: Path, wiki_name: str='') -> WikiExportReport` — Project a wiki store into an OKF v0.1 markdown bundle.
