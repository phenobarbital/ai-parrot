---
id: F020
query_id: Q028,Q029,Q030
type: read
intent: Trace GraphIndexBuilder stages and the chunk/embedding path, and establish how per-version updates would be applied
executed_at: 2026-08-23T00:41:45Z
depth: 2
parent_id: F011
---

# F020 — A 6-stage pipeline with atomic per-document refresh exists, but there are TWO write paths and legal entities need the ontology one

## Summary

`GraphIndexBuilder` orchestrates six stages — Extraction (Code/Loader/Skill extractors run
concurrently), Embedding (`GraphIndexEmbedder`, FAISS), Graph assembly (rustworkx), Cross-
domain resolution, Persistence (ArangoDB + pgvector), Analytics — and exposes
`ingest_document(uri, ctx)` for incremental per-document refresh backed by
`GraphIndexPersistence.replace_document_slice`, an atomic soft-delete-then-upsert. There is a
`LoaderExtractor`, so `parrot_loaders` output already feeds this pipeline. The important
constraint: this path writes `UniversalNode`s whose `kind` is a **closed `NodeKind` enum**
mapping to fixed `gi_*` collections, with free-form metadata only in `domain_tags`. Typed legal
entities (`norma`, `articulo`, `sentencia`) require the *other* write path — the ontology
`EntityDef`/`OntologyGraphStore` route (F003, F016). Reconciling those two paths is a real
design decision the source did not consider.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py`
  lines: 1-17
  symbol: `GraphIndexBuilder`
  excerpt: |
    ``GraphIndexBuilder`` wires together all 6 GraphIndex pipeline stages:
    1. Extraction — CodeExtractor, LoaderExtractor, SkillExtractor run concurrently
    2. Embedding — GraphIndexEmbedder (FAISS index construction)
    5. Persistence — GraphIndexPersistence (ArangoDB + pgvector)
    Entry points:
    - ``build(sources, ctx)`` — full reindex
    - ``ingest_document(uri, ctx)`` — incremental per-document refresh

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py`
  lines: 353, 390
  symbol: `replace_document_slice`
  excerpt: |
    ``GraphIndexPersistence.replace_document_slice``.
        replace_result = await self.persistence.replace_document_slice(

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py`
  lines: 143-171
  symbol: `UniversalNode`
  excerpt: |
    class UniversalNode(BaseModel):
        domain_tags: Arbitrary key-value metadata from the extractor
            (e.g. ``{"symbol_type": "function"}``, ``{"flat": true}``).
        node_id: str
        kind: NodeKind
        embedding_ref: Reference into the FAISS/pgvector index

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py`
  lines: 25-58, 193
  symbol: `GraphIndexEmbedder.embed_nodes`, `_persist_to_pgvector`

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py`
  symbol: `LoaderExtractor`

## Notes

`replace_document_slice` is the natural mechanism for both CENDOJ lazy ingest and consolidated-
text re-ingestion. The two-write-path tension is new and should become an explicit spec
decision, not an assumption.
