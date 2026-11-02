---
id: F012
query_id: Q032
type: grep
intent: "Digest / revision tracking in knowledge subsystems (sha256, source_revision) for the DocumentKB contract."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 800
parent_id: null
depth: 0
merged_from: [FC-013-digest-revision-tracking, FW-009-contractcard-bookcard-digests]
---

# F012 — SHA-256/digest tracking is pervasive in knowledge/*: `BookCard.source_sha256`, contracts `source_sha256` as citation identity, wiki stores, retrieval digests; no literal `source_revision` field

## Summary

*[FC-013-digest-revision-tracking]* ~400 matches across 20+ modules. Highest density: `contracts/catalog_postgres.py` (43), `wiki/store.py` (33), `retrieval/wiki_cache.py` (30), `contracts/library.py` (26), `wiki/ledger/outbox.py`, `retrieval/digest.py`, `manuals/carding.py`, `bookstore/library.py`/`catalog.py`. Bookstore cards carry `source_sha256` + `toc_digest`; contract versions carry `source_sha256` and the docstring says it is "part of the citation identity". The DocumentKB contract (id + sha256 + summaries invalidated on digest change) already exists de facto for bookstore/contracts; the term `source_revision` does not appear.

*[FW-009-contractcard-bookcard-digests]* `ContractCard` (contracts/models.py:L341-457) has `contract_id` (= PageIndex `tree_name`), `source_sha256`, `toc_digest`, `source_uri`, `revision: int`, `versions: list[ContractVersion]`, `field_provenance: dict[str, FieldProvenance]`, `verification: VerificationState`, `stale_fields`, `card_origin: llm|fallback|manual`, `topics`. `BookCard` (bookstore/models.py) has `book_id` (= `tree_name`), `source_sha256`, `toc_digest`, `source_path`, `topics`, `scope: project|global`, `card_origin`, `community_id/label`, plus a typed `BookRelation` graph (`origin: deterministic|llm|community`). Both are durable per-document cards in `library.db`; summaries are LLM `CardDraft` output merged at ingestion.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py`
  lines: 152-180
  symbol: `BookCard`
  excerpt: |
    class BookCard(BaseModel):
        book_id: str   # doubles as the PageIndex tree_name
        topics: list[str]; summary: str = ""; toc_digest: str = ""
        scope: Literal["project", "global"] = "project"
        source_path: str; source_sha256: str
        card_origin: Literal["llm", "fallback", "manual"] = "llm"

- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 296-308
  symbol: `contract version source_sha256`
  excerpt: |
    source_sha256: SHA-256 of the source bytes behind this version.
    source_sha256: str = ""

- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 567-588
  symbol: `citation identity`
  excerpt: |
    version_n and source_sha256 are part of the citation identity so
    source_sha256: str = ""

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/digest.py`
  lines: 1-19
  symbol: `derive_digest`
  excerpt: |
    (19 digest/sha mentions — retrieval digest derivation)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1-33
  symbol: `wiki store hashing`
  excerpt: |
    (33 sha256/digest mentions — page content hashing)

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

*[FC-013-digest-revision-tracking]* Bookstore `scope: project|global` is another existing two-tier precedent.

*[FW-009-contractcard-bookcard-digests]* The source's DocumentKB contract (`id`, `sha256`, extraction state, summaries tied to `source_revision`) is already satisfied shape-wise by `BookCard`/`ContractCard`; what is missing is a generic "summary invalidated when sha256 changes" rule across the bookstore (ContractCard has `stale_fields`; BookCard does not). `scope: project|global` on BookCard is a two-tier precedent. `topics` (not `tags`) is the filter key — the manifest's `scope: {tags: [...]}` should map to `topics`.
