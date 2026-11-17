---
id: FW-009
query_id: Q009
type: wiki_page
intent: "Bookstore / contracts catalog cards: id, sha256, revision"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-009 — Catalog cards already carry `source_sha256`, `toc_digest`, `source_uri/source_path`, `topics`, `scope` and (contracts) `revision` + `versions` + `field_provenance`; the DocumentKB contract exists in two sibling models

## Summary

`ContractCard` (contracts/models.py:L341-457) has `contract_id` (= PageIndex `tree_name`), `source_sha256`, `toc_digest`, `source_uri`, `revision: int`, `versions: list[ContractVersion]`, `field_provenance: dict[str, FieldProvenance]`, `verification: VerificationState`, `stale_fields`, `card_origin: llm|fallback|manual`, `topics`. `BookCard` (bookstore/models.py) has `book_id` (= `tree_name`), `source_sha256`, `toc_digest`, `source_path`, `topics`, `scope: project|global`, `card_origin`, `community_id/label`, plus a typed `BookRelation` graph (`origin: deterministic|llm|community`). Both are durable per-document cards in `library.db`; summaries are LLM `CardDraft` output merged at ingestion.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 341-457
  symbol: `ContractCard`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#ContractCard
  score: 1.00
  excerpt: |
    class ContractCard(BaseModel):
        contract_id: str; tree_name: str = ""
        source_uri: str; source_path: Optional[str]; source_sha256: str = ""
        toc_digest: str = ""; field_provenance: dict[str, FieldProvenance]
        verification: VerificationState = "extracted"; stale_fields: list[str]
        versions: list[ContractVersion]; revision: int

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py`
  symbol: `BookCard`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
  score: 0.85
  excerpt: |
    class BookCard(BaseModel):
        book_id: str; title: str; topics: list[str]; summary: str = ""
        toc_digest: str = ""; tree_name: str; scope: Literal["project", "global"] = "project"
        source_path: str; source_sha256: str; card_origin: Literal["llm", "fallback", "manual"] = "llm"
        community_id: Optional[str]; community_label: Optional[str]

## Notes

The source's DocumentKB contract (`id`, `sha256`, extraction state, summaries tied to `source_revision`) is already satisfied shape-wise by `BookCard`/`ContractCard`; what is missing is a generic "summary invalidated when sha256 changes" rule across the bookstore (ContractCard has `stale_fields`; BookCard does not). `scope: project|global` on BookCard is a two-tier precedent. `topics` (not `tags`) is the filter key — the manifest's `scope: {tags: [...]}` should map to `topics`.
