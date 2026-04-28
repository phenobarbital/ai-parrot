# Parent-Child Retrieval (Small-to-Big)

**Feature**: FEAT-128
**Design spec**: `sdd/specs/parent-child-retrieval.spec.md`

---

## What it is

Parent-child retrieval is a small-to-big strategy that improves answer quality
for queries whose answer spans multiple paragraphs of the same source section.

The idea: **embed and search over small chunks** (precise retrieval), but **send
their parent documents** to the LLM (full context). The chunk is the *index*;
the parent is the *payload*.

Without parent expansion, a question like *"¿cómo recibiré mi paga?"* may
retrieve four disconnected 512-token chunks from the same handbook section,
and the LLM synthesises a worse answer than it would from the original
1500-word paragraph. With parent expansion, the bot fetches that paragraph
and sends it as one unit.

---

## When to enable it

Enable parent expansion for corpora where answers naturally span multiple
chunks of a single source section:

- HR handbooks and policy documents
- Technical manuals and product guides
- Training materials

Do **not** enable it for FAQ-style corpora where each chunk IS the complete
answer — expanding to the parent would inject irrelevant surrounding text.

> **Token budget warning**: Each expansion fetches a parent document
> (2000–4000 tokens for a parent_chunk, or a full document for 2-level
> ingestion). With 10 retrieved children across 10 distinct parents, you may
> push 40 000 tokens into the LLM context. Set `context_search_limit=5` (or
> lower) when `expand_to_parent=True` to stay within budget.

---

## How to enable

### Option 1 — Constructor injection

```python
from parrot.stores.parents import InTableParentSearcher
from parrot.stores.postgres import PgVectorStore
from parrot.bots.chatbot import Chatbot

store = PgVectorStore(dsn="postgresql://...", table="my_docs")
searcher = InTableParentSearcher(store=store)

bot = Chatbot(
    parent_searcher=searcher,
    expand_to_parent=True,
    context_search_limit=5,   # recommended when expansion is on
)
```

### Option 2 — DB-driven config

Set `expand_to_parent=True` on the bot row in the database. The
`parent_searcher` itself must still be injected via the constructor — it
is not DB-driven in v1.

### Option 3 — Per-call override

You can override the bot-level default on a per-call basis:

```python
# Bot default is expand_to_parent=True, but this call uses children only
ctx, meta = await bot.get_vector_context(question, expand_to_parent=False)

# Bot default is expand_to_parent=False, but opt-in for this call
ctx, meta = await bot.get_vector_context(question, expand_to_parent=True)
```

**Resolution order**: explicit per-call kwarg → bot-level default → `False`.

---

## The 3-level hierarchy

For large documents (above `parent_chunk_threshold_tokens`), expanding to
the entire document would push 50 000+ tokens into the LLM context. Instead,
the ingestion pipeline splits the document into intermediate **parent_chunks**,
and children link to a parent_chunk rather than the full document.

```
document (NOT stored as parent)
  ├── parent_chunk_0  (document_type='parent_chunk', ~4000 chars)
  │     ├── child_chunk_0  (is_chunk=True, parent_document_id=parent_chunk_0.id)
  │     └── child_chunk_1
  ├── parent_chunk_1
  │     ├── child_chunk_2
  │     └── child_chunk_3
  └── parent_chunk_2
        └── child_chunk_4
```

For documents below the threshold, the existing 2-level path is preserved:

```
document (stored as parent, is_full_document=True)
  ├── child_chunk_0
  └── child_chunk_1
```

### Threshold defaults

| Parameter | Default | Description |
|---|---|---|
| `parent_chunk_threshold_tokens` | 16 000 | Documents longer than this (in characters) use the 3-level path. |
| `parent_chunk_size_tokens` | 4 000 | Target size of each parent_chunk (in characters). |
| `parent_chunk_overlap_tokens` | 200 | Overlap between adjacent parent_chunks (in characters). |

> **Note**: The "token" unit in this codebase is **characters** (the chunker
> uses character-based splitting). The names retain the `_tokens` suffix for
> conceptual clarity, but tune them as character counts.

You can override the defaults when calling `_chunk_with_late_chunking`:

```python
# Use a lower threshold for smaller hardware budgets
await loader._chunk_with_late_chunking(
    documents,
    vector_store=store,
    parent_chunk_threshold_tokens=8000,
    parent_chunk_size_tokens=2000,
    parent_chunk_overlap_tokens=100,
)
```

---

## Composition with the FEAT-126 cross-encoder reranker

When both a reranker (FEAT-126) and a `parent_searcher` are configured, the
order is strictly:

1. `similarity_search` → child candidates (default: parents excluded).
2. Reranker re-ranks the children, truncates to top-K.
3. Parent expansion runs on the **reranked top-K** (not before reranking).

This order is correct because the reranker scores at the precision of child
chunks; expanding to parents before reranking would cause the reranker to
score coarse parent text, defeating the purpose.

A consequence: when multiple high-scoring children share the same parent, the
deduplication step collapses them into one parent. You may end up with fewer
than `context_search_limit` items in the LLM context — this is by design and
improves relevance density.

---

## Migration warning

Collections ingested **before FEAT-128** may not have universal `is_chunk=True`
markers on child chunks. The default `similarity_search` filter has a
backward-compatibility clause that keeps **legacy chunks** returnable:

```sql
WHERE
  (metadata->>'is_chunk')::boolean = true   -- explicit chunks
  OR (
    metadata->>'is_full_document' IS NULL    -- no parent marker
    AND metadata->>'document_type' IS NULL   -- no document_type marker
  )
```

This means legacy chunks (no markers) ARE returned, but parent rows
(`is_full_document=True` or `document_type='parent'/'parent_chunk'`) are
excluded, which is the correct default.

If you have tooling that relied on parent rows appearing in
`similarity_search` output, use the escape hatch:

```python
results = await store.similarity_search(
    query, limit=10, include_parents=True   # legacy behaviour
)
```

Operators should re-ingest collections where possible to add universal
`is_chunk=True` markers (the normalisation now runs automatically in
`add_documents`).

---

## Limitations (v1)

- **Postgres / pgvector only.** `InTableParentSearcher` uses SQLAlchemy with
  JSONB predicates specific to PostgreSQL. Other stores (Milvus, FAISS,
  BigQuery, ArangoDB) would need their own `<Store>ParentSearcher`
  implementation.

- **DB-driven `parent_searcher` selection is deferred.** In v1, the
  `parent_searcher` instance must be injected via the constructor. A registry
  / import-string lookup is planned for v2.

- **No automatic re-ingestion.** Adding parent-child markers to an existing
  collection requires a re-ingest. There is no online migration path.

---

## API reference

### `parrot.stores.parents.AbstractParentSearcher`

```python
class AbstractParentSearcher(ABC):
    async def fetch(self, parent_ids: list[str]) -> dict[str, Document]:
        """Fetch parent documents by ID. Missing IDs are absent from result."""

    async def health_check(self) -> bool:
        """Optional readiness probe. Default: True."""
```

### `parrot.stores.parents.InTableParentSearcher`

```python
class InTableParentSearcher(AbstractParentSearcher):
    def __init__(self, store: AbstractStore) -> None: ...
```

Issues a single SQL query per `fetch()` call:

```sql
SELECT id, document, cmetadata
FROM <schema>.<table>
WHERE id = ANY(:ids)
  AND (
    (cmetadata->>'is_full_document')::boolean = true
    OR cmetadata->>'document_type' = 'parent_chunk'
  )
```

### `AbstractBot` attributes

```python
bot.parent_searcher    # Optional[AbstractParentSearcher], default None
bot.expand_to_parent   # bool, default False
```

### `LateChunkingProcessor.process_document_three_level`

```python
async def process_document_three_level(
    self,
    document_text: str,
    document_id: str,
    metadata: Optional[dict] = None,
    parent_chunk_size_tokens: int = 4000,
    parent_chunk_overlap_tokens: int = 200,
) -> tuple[list[Document], list[ChunkInfo]]:
    """Split an oversized document into parent_chunks + child chunks."""
```
