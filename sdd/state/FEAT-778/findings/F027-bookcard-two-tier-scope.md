---
id: F027
query_id: Q047
type: read
intent: "Bookstore catalog models: card fields (id, hash, revision, tags) for the mandatory wiki/bookstore source."
executed_at: 2026-10-30T16:46:28Z
duration_ms: 300
parent_id: null
depth: 0
merged_from: [FC-028-bookcard-two-tier-scope]
---

# F027 — `BookCard` = id (`book_id` == PageIndex tree), `topics` (tag-like), `summary`, `toc_digest`, `scope: project|global`, `source_sha256`, `card_origin llm|fallback|manual`, `community_id`

## Summary

`knowledge/bookstore/models.py` classes: `TocEntry`, `CardDraft`, `BookCard`, `BookRelation`, `RelationJudgement`, `RelationDraft`, `CommunityLabelDraft`, `BookCommunity`, `RelateSummary`. The card is the DocumentKB-shaped catalog entry (id + sha256 + LLM summary); `topics` is the only tag-like filter (the source's `scope: {tags: [...]}` would map to topics/communities); `scope` already distinguishes project vs global libraries.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py`
  lines: 98-152
  symbol: `TocEntry / CardDraft / BookCard`
  excerpt: |
    class TocEntry(BaseModel): ...
    class CardDraft(BaseModel): ...
    class BookCard(BaseModel):
        """The catalog card ("ficha hemeroteca") for one indexed book.
        ``book_id`` doubles as the PageIndex ``tree_name`` — one slug, one tree, one card."""

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py`
  lines: 160-180
  symbol: `BookCard fields`
  excerpt: |
    topics: list[str]; summary: str = ""; toc_digest: str = ""
    scope: Literal["project", "global"] = "project"
    source_path: str; source_sha256: str; source_format: Literal["pdf","md","txt","epub","mobi","docx"]
    card_origin: Literal["llm", "fallback", "manual"] = "llm"; community_id: Optional[str]

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py`
  lines: 210-336
  symbol: `BookRelation / BookCommunity / RelateSummary`
  excerpt: |
    class BookRelation(BaseModel): ... class BookCommunity(BaseModel): ... class RelateSummary(BaseModel):

## Notes

No "summary invalidated when sha changes" rule visible in models; it would live in `bookstore/catalog.py`/`library.py` (13-14 sha mentions each, FC-013).
