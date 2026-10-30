---
id: F045
query_id: Q008
type: wiki_page
intent: "OKF bundle export contract"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FW-008-okf-export]
---

# F045 — OKF v0.1 bundle = markdown files with YAML frontmatter (`type`, `title`, `id`, `tags`, `timestamp`, `summary`, `relates_to`) + root `index.md`; export-only projection of `WikiStore`, never read back on retrieval

## Summary

`knowledge/wiki/export.py` defines `export_okf_bundle(store, output_dir, wiki_name) -> WikiExportReport`: pages are written as `<category>s/<id>.md` with deterministic frontmatter (`page_frontmatter`: `type` via `CATEGORY_TO_OKF_TYPE`, `title`, `id`, `tags` (default = category), `timestamp`, optional `summary`, `relates_to: [{concept, rel}]`), plus `index.md` from `generate_index`. The module docstring states the wiki's internal representation is the SQLite `WikiStore`; OKF markdown is "generated lazily and only at export time … never read back on the retrieval path" (though an inverse map `OKF_TYPE_TO_CATEGORY` exists "for consumers that read bundles back (file_store backend)").

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/export.py`
  lines: 1-60
  symbol: `export_okf_bundle` / `page_frontmatter` / `CATEGORY_TO_OKF_TYPE`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/wiki/export.py
  score: 1.00
  excerpt: |
    # module docstring: OKF v0.1 bundle export for the LLM Wiki (export-only boundary).
    # "The wiki's internal representation is the machine-first WikiStore SQLite plane; OKF markdown is
    #  generated lazily and only at export time as an interchange projection, never read back on the
    #  retrieval path."
    CATEGORY_TO_OKF_TYPE = {"summary": "Wiki Summary", "entity": "Wiki Entity", ..., "concept": "Concept"}
    OKF_TYPE_TO_CATEGORY = {v: k for k, v in CATEGORY_TO_OKF_TYPE.items()}  # file_store backend reads back

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/export.py`
  symbol: `page_frontmatter`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/wiki/export.py
  score: 1.00
  excerpt: |
    data = {"type": okf_type(category), "title": ..., "id": page["concept_id"],
            "tags": list(dict.fromkeys(tags)) if tags is not None else [category],
            "timestamp": page.get("updated_at") or ""}
    if relates_to: data["relates_to"] = relates_to

## Notes

The source's Tier-1 `knowledge/*.md` "bundles OKF" would be *authored* OKF files, i.e. the read-back direction. The export module says that direction is handled by a `file_store` backend (`OKF_TYPE_TO_CATEGORY`), so an expert's bundled knowledge could be a file-backed wiki namespace rather than a new loader. `tags` in frontmatter is the natural key for the manifest's `scope: {tags: [...]}`.
[cross-lane: type=grep, intent=locate the wiki file_store backend that reads OKF bundles back (knowledge/wiki/*file*store*)]
