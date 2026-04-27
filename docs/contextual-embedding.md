# Contextual Embedding Headers

> **Feature**: FEAT-127 — Metadata-Driven Contextual Embedding Headers  
> **Since**: ai-parrot next minor  
> **Stability**: stable

---

## What it does

When you ingest documents into a vector store today, each chunk is embedded as
bare `page_content` text — 512 tokens with no signal about *which document* the
chunk came from.  This causes two failure modes:

1. **Wrong-domain matches** — a query for "vacation policy" can pull chunks from
   any document that uses the same vocabulary.
2. **Lost context** — a chunk that starts *"You will receive it on the 15th of
   every month"* has no embedding signal tying it to *"compensation"*.

The fix is to prepend a short, deterministic **contextual header** to each
chunk *before it is embedded*.  The header is built from structured metadata
that loaders already attach to every `Document` (title, section, category, …).

```
Title: Employee Handbook | Section: Compensation | Category: HR Policy

You will receive it on the 15th of every month.
```

Key properties:

- **LLM-free** — no API call per chunk.  Same input → same embedding, every time.
- **Store-side** — loaders are unchanged; augmentation happens at the embedding
  boundary inside `add_documents` / `from_documents`.
- **Opt-in** — disabled by default; existing collections are unaffected.
- **Non-destructive** — `page_content` is never mutated.  The header travels in
  `metadata['contextual_header']` for traceability.

---

## Enabling it

Pass `contextual_embedding=True` to any supported store constructor.

### PgVectorStore

```python
from parrot.stores.postgres import PgVectorStore

store = PgVectorStore(
    dsn="postgresql://user:pass@host/db",
    table="my_collection",
    contextual_embedding=True,           # ← enable
)
await store.connection()
await store.add_documents(documents)
```

### MilvusStore

```python
from parrot.stores.milvus import MilvusStore

store = MilvusStore(
    host="localhost",
    port=19530,
    collection_name="my_collection",
    contextual_embedding=True,
)
await store.connection()
await store.add_documents(documents)
```

### FAISSStore

```python
from parrot.stores.faiss_store import FAISSStore

store = FAISSStore(
    collection_name="my_collection",
    contextual_embedding=True,
)
await store.connection()
await store.add_documents(documents)
```

### ArangoDBStore

```python
from parrot.stores.arango import ArangoDBStore

store = ArangoDBStore(
    host="localhost",
    port=8529,
    collection_name="my_collection",
    contextual_embedding=True,
)
await store.connection()
await store.add_documents(documents)
```

---

## The default template

```python
from parrot.stores.utils.contextual import DEFAULT_TEMPLATE

print(DEFAULT_TEMPLATE)
# "Title: {title} | Section: {section} | Category: {category}\n\n{content}"
```

### Worked examples

| `document_meta` | Resulting header |
|---|---|
| `{"title": "Handbook", "section": "Pay", "category": "HR"}` | `Title: Handbook \| Section: Pay \| Category: HR` |
| `{"title": "FAQ"}` | `Title: FAQ` |
| `{}` or absent | *(no header — passthrough)* |

Fields that are `None` or empty strings are **silently dropped** — no orphan
pipes, no `"Title: None"` in the output.

The header is capped at `contextual_max_header_tokens` (default: 100 words,
whitespace-tokenised) so that extremely long titles do not consume the
embedding model's input budget.

---

## Customising the template

### String template

Any format-map style string with named placeholders from the set
`{title, section, category, page, language, source, content}`:

```python
store = PgVectorStore(
    dsn=...,
    table="my_collection",
    contextual_embedding=True,
    contextual_template=(
        "[{title}] ({category})\n\n{content}"
    ),
)
```

For Spanish corpora, where embedding models may score English keywords
differently, use a Spanish-language template:

```python
contextual_template=(
    "Título: {title} | Sección: {section} | Categoría: {category}\n\n{content}"
)
```

### Callable template

Pass a callable that receives the raw `document_meta` dict and returns the
**full text to embed** (header + content).  Split on the first `"\n\n"` to
declare the header:

```python
def my_template(meta: dict) -> str:
    title = meta.get("title", "Untitled")
    content = meta.get("content", "")   # 'content' is NOT in document_meta
    # Typically you'd still want the page_content — see note below.
    return f"[{title}]\n\n{content}"

store = PgVectorStore(
    dsn=...,
    contextual_embedding=True,
    contextual_template=my_template,
)
```

> **Note**: When using a callable template, the callable receives only the
> `document_meta` sub-dict, not `page_content`.  To include the chunk text you
> must close over it or use a store-level wrapper.  The string template form
> (with `{content}`) is more ergonomic for most use-cases.

---

## What gets stored

`page_content` is **never modified**.  The augmented text is used exclusively
as input to the embedding model.  The header is persisted in the row's metadata
column so it is visible at retrieval time.

Before (off):

```json
{
  "document": "You will receive it on the 15th of every month.",
  "cmetadata": {
    "document_meta": {
      "title": "Employee Handbook",
      "section": "Compensation",
      "category": "HR Policy"
    }
  }
}
```

After (on):

```json
{
  "document": "You will receive it on the 15th of every month.",
  "cmetadata": {
    "document_meta": {
      "title": "Employee Handbook",
      "section": "Compensation",
      "category": "HR Policy"
    },
    "contextual_header": "Title: Employee Handbook | Section: Compensation | Category: HR Policy"
  }
}
```

`contextual_header` is also surfaced in `SearchResult.metadata` so retrieval
code can access it without round-tripping to the source document:

```python
results = await store.similarity_search("vacation policy", limit=5)
for r in results:
    print(r.metadata.get("contextual_header", ""))
    # "Title: Employee Handbook | Section: Compensation | Category: HR Policy"
```

---

## Precedence with late chunking

When both `store_full_document=True` (late-chunking mode) and
`contextual_embedding=True` are configured, **metadata-header wins**.

Late chunking builds embeddings from neighbouring chunk text (contextual
window); this feature builds embeddings from metadata-derived headers.  They
are orthogonal, but applying both would produce unpredictable embeddings.  The
resolution: when `contextual_embedding` is True, the metadata-header path
replaces the late-chunking embeddings for every chunk.  The late-chunking
pipeline still runs to produce chunks; only their final embedding is
overridden.

> Decision rationale: spec §8 Q3, answered by Jesus Lara.

---

## Migrating existing collections

Flipping `contextual_embedding=True` on a collection that was ingested without
the flag produces **inconsistent retrieval** — new chunks have header-augmented
embeddings; old chunks do not.  You must re-embed the entire collection.

Use the provided migration script:

```bash
python packages/ai-parrot/scripts/recompute_contextual_embeddings.py \
    --dsn postgresql://user:pass@host/db \
    --table my_collection \
    --schema public \
    --batch-size 200 \
    --dry-run      # validate first
```

Then run without `--dry-run` to apply the UPDATEs.

Available flags:

| Flag | Default | Description |
|---|---|---|
| `--dsn` | *(required)* | PostgreSQL DSN |
| `--table` | *(required)* | Table to recompute |
| `--schema` | `public` | Schema |
| `--embedding-model` | parrot config | Model name or JSON config |
| `--template` | DEFAULT_TEMPLATE | Custom header template |
| `--max-header-tokens` | 100 | Header token cap |
| `--batch-size` | 200 | Rows per batch |
| `--limit` | — | Process at most N rows (testing) |
| `--dry-run` | — | Read + embed but do NOT write |

> **Migration is Postgres-only** in v1.  Milvus / FAISS / Arango re-indexing
> must be handled via a full re-ingest.

---

## Dependency

This feature reads `document.metadata['document_meta']` in the canonical shape
defined by **`ai-parrot-loaders-metadata-standarization`**.  If that spec has
not been merged and loaders do not produce `document_meta`, the helper degrades
gracefully to passthrough (no header, original text embedded as-is).

Expected `document_meta` shape:

```python
{
    "title": "Employee Handbook",       # str | None
    "section": "Compensation",          # str | None
    "category": "HR Policy",            # str | None
    "page": 3,                          # int | None
    "language": "en",                   # str | None
    "source": "s3://bucket/path.pdf",   # str | None
}
```

Any keys not in the known set are simply unused (not an error).

---

## Implementation notes

- The helper `build_contextual_text` is a pure function — no I/O, no logging,
  deterministic.  It lives in `parrot/stores/utils/contextual.py`.
- Brace-injection is neutralised: `{` and `}` in metadata values are escaped to
  `{{` / `}}` before `str.format_map`.
- The token cap uses whitespace tokenisation (`.split()`), not a sub-word
  tokeniser.  It is a safety belt; downstream models may still truncate if a
  title is pathological.
- Multi-language collections should use a language-matching header template
  (see "Customising the template").
- Re-indexing is required whenever `document_meta` changes for an already-
  ingested document — a title change updates the embedding.
