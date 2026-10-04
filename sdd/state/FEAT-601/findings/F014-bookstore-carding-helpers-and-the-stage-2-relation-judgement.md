---
id: F014
query_id: Q014
type: read
intent: bookstore carding.py helpers and relations.py judge_relations/candidate_pairs + judgement log and force mechanics
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F014 — Bookstore carding helpers and the Stage-2 relation judgement log/force

## Summary
The carding helpers do not depend on the bookstore itself. `slugify(text)` uses NFKD, is ASCII-only, capped at 64 chars, and falls back to "book". `unique_slug(base, taken)` appends `-N`. `derive_toc(tree, max_depth=2)` walks a PageIndex tree into `(TocEntry list, digest)`. `sample_sections(loader, node_ids, max_samples=2)` takes the first and middle nodes. `generate_card_fields(adapter, *, filename, doc_description, toc_digest, samples)` makes one `ask_structured` call. `judge_relations` makes exactly one structured LLM call per source card and drops any hallucinated ids. `candidate_pairs` removes anything already in `judged`. The `force` flag lives in `Bookstore.relate_books`: `judged = set() if force else store.judged_pairs(book_id)`. Judgements go to the SQLite table `relation_judgements`, primary key `(src_book_id, dst_book_id)`, written with INSERT OR REPLACE.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py`
  lines: 49-70
  symbol: `slugify`
  excerpt: |
    def slugify(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
        slug = _SLUG_RE.sub("-", ascii_text).strip("-")
        slug = slug[:_MAX_SLUG_LEN].strip("-")
        return slug or "book"
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py`
  lines: 73-85
  symbol: `unique_slug`
  excerpt: |
    def unique_slug(base: str, taken: set[str]) -> str:
        if base not in taken: return base
        n = 2
        while f"{base}-{n}" in taken: n += 1
        return f"{base}-{n}"
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py`
  lines: 88-138
  symbol: `derive_toc`
  excerpt: |
    def derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str]:
        """Walk a PageIndex tree dict into ToC entries plus a text digest."""
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py`
  lines: 157-190
  symbol: `generate_card_fields`
  excerpt: |
    async def generate_card_fields(adapter: Any, *, filename: str, doc_description: str,
                                   toc_digest: str, samples: list[str]) -> CardDraft:
        draft = await adapter.ask_structured(prompt, CardDraft)
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py`
  lines: 193-215
  symbol: `sample_sections`
  excerpt: |
    def sample_sections(content_loader: Any, node_ids: list[str], max_samples: int = 2) -> list[str]:
        picks = [node_ids[0]]
        if len(node_ids) > 2: picks.append(node_ids[len(node_ids) // 2])
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py`
  lines: 296-359
  symbol: `candidate_pairs`
  excerpt: |
    def candidate_pairs(card: BookCard, cards: list[BookCard], det_relations: list[BookRelation],
                        fts_hits: list[BookCard], judged: set[str], cap: int = 8) -> list[BookCard]:
        if other_id == card.book_id or other_id in judged: continue
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py`
  lines: 372-413
  symbol: `judge_relations`
  excerpt: |
    async def judge_relations(adapter: Any, card: BookCard, candidates: list[BookCard], *,
                              model_name: str = "") -> RelationDraft:
        draft = await adapter.ask_structured(prompt, RelationDraft)
        valid_ids = {c.book_id for c in candidates}
        judgements = [j for j in draft.judgements if j.dst_book_id in valid_ids]
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py`
  lines: 640-677
  symbol: `Bookstore.relate_books (Stage 2 loop)`
  excerpt: |
    judged = set() if force else store.judged_pairs(book_id)
    candidates = candidate_pairs(card, all_cards, det, fts_hits, judged)
    draft = await judge_relations(self.adapter, card, candidates, model_name=model_name)
    store.record_judgements(book_id, draft.judgements, model=model_name)
    for judgement in draft.judgements:
        store.delete_relation_pair(book_id, judgement.dst_book_id, origin="llm")
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py`
  lines: 127-135
  symbol: `relation_judgements (DDL)`
  excerpt: |
    CREATE TABLE IF NOT EXISTS relation_judgements (
        src_book_id TEXT NOT NULL, dst_book_id TEXT NOT NULL,
        judged_at TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
        rel TEXT NOT NULL, confidence REAL NOT NULL,
        PRIMARY KEY (src_book_id, dst_book_id))
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py`
  lines: 597-645
  symbol: `CatalogStore.record_judgements / judged_pairs / delete_judgements`
  excerpt: |
    "INSERT OR REPLACE INTO relation_judgements " ...
    def judged_pairs(self, src: str) -> set[str]:
        "SELECT dst_book_id FROM relation_judgements WHERE src_book_id = ?"
    def delete_judgements(self, book_id: str) -> int:

## Notes
- `judge_relations`, `candidate_pairs` and `generate_card_fields` are built around `BookCard`/`RelationDraft`/`CardDraft`. Reusing them for Step→Media or Procedure similarity means generalising the models or copying the pattern, not calling them directly.
- `delete_relation_pair(..., origin="llm")` shows relations tagged with an `origin` field so re-judging replaces only LLM edges. The same idea fits procedures: manual-derived edges vs. LLM-inferred illustrated_by edges.
- `slugify` turns non-Latin titles into "book". Manuals with non-ASCII model names need an explicit slug.

