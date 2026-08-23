---
id: F015
query_id: Q019
type: read
intent: Characterize the wiki plane against GraphIndex to establish which substrate carries typed legal entities
executed_at: 2026-08-23T00:41:06Z
depth: 3
parent_id: F014
---

# F015 — The wiki plane is a page/category plane, not a typed graph; but ingest.py already bridges it into GraphIndex

## Summary

`parrot/knowledge/wiki/` models documents, not domain entities: its data model is
`WikiPageCategory`, `WikiConfig`, `SourceManifestEntry`, `WikiSearchResult` — pages with
categories and token counts, linked by `summarizes` edges to sources. There is no entity/
relation vocabulary and no place for `modifica`/`deroga`/`aplica_articulo`. Crucially, the
ingest orchestrator already has a documented bridge: step 5 of its pipeline optionally
"mirror[s] a `wiki_page` node into GraphIndex" via `sync_graph=True`. The two planes are
therefore complementary and already wired, which makes a layered answer to U1 viable rather
than a mutually exclusive fork.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/models.py`
  lines: 25, 52, 159, 227, 268
  symbol: `WikiPageCategory`, `WikiConfig`, `SourceManifestEntry`, `WikiSearchResult`
  excerpt: |
    class WikiPageCategory(str, Enum):
    class WikiSearchResult(BaseModel):
        category: Optional[WikiPageCategory] = Field(

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py`
  lines: 1-22
  excerpt: |
    """Wiki ingest orchestrator for the LLM Wiki feature (FEAT-260).
    4. Upsert the generated pages into the :class:`WikiStore` retrieval
       plane (bodies, categories, token counts) and record
       ``summarizes`` edges page → source.  ``replace_source_slice``
       guarantees re-ingest never accumulates duplicates.
    5. Optionally (``sync_graph=True``) mirror a ``wiki_page`` node into
       GraphIndex.

## Notes

Suggests the natural architecture: wiki namespaces (FEAT-450) as the brain-selection and
document layer; GraphIndex + Ontology as the typed legal graph beneath it.
