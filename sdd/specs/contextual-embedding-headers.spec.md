# Feature Specification: Metadata-Driven Contextual Embedding Headers

**Feature ID**: FEAT-127
**Date**: 2026-04-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

Chunks ingested into the vector store today are embedded as bare `page_content`,
without any indication of the document, section, or category they belong to.
A 512-token paragraph about *"how to receive your paycheck"* sitting inside an
employee handbook embeds with the same neighbourhood as a similar paragraph from
a customer-facing FAQ — there is nothing in the embedding space that anchors the
chunk to its source document.

This shows up in retrieval as two failure modes:

1. **Wrong-domain matches**: a query like *"vacation policy"* can pull chunks
   from a generic policy document that uses the same vocabulary but is not the
   handbook the employee should be reading.
2. **Lost context on standalone chunks**: a chunk that begins *"You will receive
   it on the 15th of every month"* — split mid-section by the chunker — has no
   embedding signal that ties it to *"compensation"*. The embedding is dominated
   by the dates and the second-person verb.

Anthropic's "Contextual Retrieval" technique fixes this by prepending an
LLM-generated context summary to each chunk before embedding. We do **not** want
that path — it requires an LLM call per chunk at ingestion (millions of dollars
at field scale, plus determinism issues). What we DO have, however, is rich
structured metadata: every loader produces document-level fields (title, section,
category, page) that already encode the same context an LLM would synthesise.

The parallel spec `ai-parrot-loaders-metadata-standarization` formalises a
canonical `document_meta` sub-dict on every Document. This spec consumes that
contract: it builds a small, deterministic, predictable header from
`document_meta` and prepends it to each chunk's text **for embedding only**. No
LLM calls. No external dependencies. Same chunk + same metadata always produces
the same embedding.

### Goals

1. Provide a deterministic, LLM-free contextual augmentation step that runs
   inside the store-insertion path: `AbstractStore.add_documents` and
   `AbstractStore.from_documents`. Loaders are not modified; the augmentation
   happens at the store boundary because that is where embedding is computed.
2. Produce a single helper `build_contextual_text(document, template)` in
   `parrot/stores/utils/contextual.py` that takes a `Document` (with canonical
   `document_meta`), formats the header from a template string, and returns the
   text to be embedded.
3. Stored `Document.page_content` remains **untouched** — the original chunk
   text. The augmented text is used **only** as input to the embedding model.
   The header is preserved in `metadata['contextual_header']` for traceability.
4. The augmentation is **opt-in per store** via a constructor flag
   `contextual_embedding: bool = False`. When False, the existing path is
   preserved byte-for-byte. When True, every chunk passes through the helper.
5. A default template ships:
   `"Title: {title} | Section: {section} | Category: {category}\n\n{content}"`
   with graceful skipping of empty fields (no `"Title: None | Section: None"`).
   Stores accept an override via `contextual_template: str | Callable` for
   teams that want different framing.
6. Header is hard-capped at ~100 tokens to leave the chunk room within the
   embedding model's max length (typically 512). Truncation at construction
   time, never silent failure mid-batch.

### Non-Goals (explicitly out of scope)

- **LLM-generated context summaries** (Anthropic Contextual Retrieval). Rejected
  for cost and determinism reasons.
- **Modifying the canonical `document_meta` shape**. That is owned by
  `ai-parrot-loaders-metadata-standarization`. This spec consumes it as-is.
- **Modifying loaders**. Loaders return `Document + metadata`. The augmentation
  is store-side.
- **Modifying the embedding clients** (`parrot/embeddings/*.py`). They keep
  receiving `List[str]`. The augmentation happens *above* them, before the
  string list is constructed.
- **Storing the augmented text in `page_content`**. The chunk content stays
  clean so the LLM prompt is not polluted with header noise.
- **Per-document override of the template at ingestion time**. Template is
  store-level; if a team needs per-document templating, they can configure
  multiple stores. We can revisit if needed.
- **Backfilling existing collections**. Re-embedding existing data is a
  migration concern handled by a separate ops procedure.

---

## 2. Architectural Design

### Overview

A new utility module `parrot/stores/utils/contextual.py` exposes:

```
build_contextual_text(
    document: Document,
    template: str | Callable[[Document], str] = DEFAULT_TEMPLATE,
    max_header_tokens: int = 100,
) -> tuple[str, str]   # (text_to_embed, header_used)
```

`AbstractStore.add_documents` and `AbstractStore.from_documents` gain a thin
wrapper step: when `self.contextual_embedding` is True, every Document in the
batch is passed through `build_contextual_text` and the result is what gets
embedded. The chunk's `metadata['contextual_header']` is set to the header used
(empty string when `document_meta` was insufficient and the chunk was passed
through). `page_content` is **not** mutated.

The default template is a one-liner because a multi-line header eats more
tokens for the same signal:

```
Title: {title} | Section: {section} | Category: {category}

{content}
```

Empty/None fields are skipped; pipes are collapsed:

- All three fields present → `"Title: A | Section: B | Category: C\n\n{content}"`
- Only `title` present → `"Title: A\n\n{content}"`
- None present → `"{content}"` (no header, traceability records empty string)

### Component Diagram

```
                ┌──────────────────────────────────────┐
                │  Loader.load() → list[Document]      │
                │  (metadata.document_meta canonical)  │
                └──────────────────┬───────────────────┘
                                   │
                                   ▼
                ┌──────────────────────────────────────┐
                │  store.add_documents(documents)       │
                │  store.from_documents(documents)      │
                └──────────────────┬───────────────────┘
                                   │
              ┌────────────────────┴──────────────────────┐
              │  IF self.contextual_embedding:            │
              │    for each doc:                          │
              │      text, header =                       │
              │        build_contextual_text(doc, ...)    │
              │      doc.metadata["contextual_header"]    │
              │        = header                           │
              │      texts_to_embed.append(text)          │
              │  ELSE:                                    │
              │    texts_to_embed = [d.page_content       │
              │                      for d in docs]       │
              └────────────────────┬──────────────────────┘
                                   │
                                   ▼
                ┌──────────────────────────────────────┐
                │  embeddings.embed_documents(texts)   │
                │  (unchanged, sees List[str] only)    │
                └──────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractStore` (`parrot/stores/abstract.py:17`) | extends | `__init__` accepts `contextual_embedding: bool = False` and `contextual_template: str \| Callable = DEFAULT_TEMPLATE`. |
| `AbstractStore.add_documents` (line 207) | modifies | Subclasses receive helper-built `texts_to_embed` instead of bare `page_content` when flag is True. |
| `AbstractStore.from_documents` (line 175) | modifies | Same hook. |
| `parrot/stores/postgres.py:add_documents` (line 586) | implements hook | Concrete store applies the helper before its current `embed_documents` call. |
| `parrot/stores/postgres.py:from_documents` (line 2551) | implements hook | Same. |
| `Document.metadata['document_meta']` (from FEAT in flight) | read-only consumer | This spec depends on the canonical shape; if the field is missing, helper falls through to bare content. |
| `Document.page_content` | preserved | Never mutated. |
| `Document.metadata['contextual_header']` | new, written | Trace of the header that was prepended for the embedding (empty string if none). |

### Data Models

```python
# parrot/stores/utils/contextual.py
from typing import Callable, Union
from parrot.stores.models import Document   # via parrot.stores.models if Document lives there

DEFAULT_TEMPLATE: str = (
    "Title: {title} | Section: {section} | Category: {category}\n\n{content}"
)
DEFAULT_MAX_HEADER_TOKENS: int = 100

# Recognised placeholders in the template string.
# Anything not in this set is left unrendered (formatted as empty string).
KNOWN_PLACEHOLDERS = frozenset({
    "title", "section", "category", "page", "language", "source", "content"
})

ContextualTemplate = Union[str, Callable[[dict], str]]
```

### New Public Interfaces

```python
# parrot/stores/utils/contextual.py
def build_contextual_text(
    document: Document,
    template: ContextualTemplate = DEFAULT_TEMPLATE,
    max_header_tokens: int = DEFAULT_MAX_HEADER_TOKENS,
) -> tuple[str, str]:
    """Build the text that will be embedded plus the header used.

    Reads `document.metadata['document_meta']` (canonical, from
    metadata-standardization). Renders the template, dropping empty fields
    and collapsing the resulting separators. Caps the header at
    `max_header_tokens` (whitespace-tokenised approximation, no real tokeniser
    dependency — the cap is a safety belt, not an exact limit).

    Returns:
        (text_to_embed, header) — header is empty string when no usable
        metadata is present.
    """

# parrot/stores/abstract.py — new __init__ kwargs
class AbstractStore(ABC):
    def __init__(
        self,
        ...,
        contextual_embedding: bool = False,
        contextual_template: ContextualTemplate = DEFAULT_TEMPLATE,
        contextual_max_header_tokens: int = 100,
        ...,
    ):
        ...
```

---

## 3. Module Breakdown

### Module 1: `parrot/stores/utils/contextual.py`
- **Path**: `packages/ai-parrot/src/parrot/stores/utils/contextual.py`
- **Responsibility**: Pure-function helper `build_contextual_text` plus the
  default template and constants. Zero ML deps; no embeddings, no torch.
  Sits next to `chunking.py` because both are pre-embedding pre-processors.
- **Depends on**: stdlib + `parrot.stores.models.Document`.

### Module 2: `parrot/stores/abstract.py` extension
- **Path**: `packages/ai-parrot/src/parrot/stores/abstract.py`
- **Responsibility**: Add the three constructor kwargs. Add a small protected
  helper `_apply_contextual_augmentation(documents) -> list[str]` that
  subclasses call from their `add_documents` / `from_documents`. Default
  passthrough when flag is False.
- **Depends on**: Module 1.

### Module 3: Wire concrete stores
- **Path**: `packages/ai-parrot/src/parrot/stores/postgres.py`
  (`add_documents` line 586, `from_documents` line 2551)
- **Responsibility**: Replace the inline `[doc.page_content for doc in docs]`
  call to embeddings with `self._apply_contextual_augmentation(docs)`.
  Also write `metadata['contextual_header']` back onto the documents before
  upsert.
- **Depends on**: Module 2.

### Module 4: Wire other stores (`milvus`, `arango`, `bigquery`, `faiss_store`)
- **Path**: `packages/ai-parrot/src/parrot/stores/{milvus,arango,bigquery,faiss_store}.py`
- **Responsibility**: Same change as Module 3 in each store's `add_documents`
  / `from_documents`. Where a store does not currently surface this hook
  cleanly, the change is to call the helper at the same boundary that
  builds the input list to its embedding call.
- **Depends on**: Module 2.

### Module 5: Tests
- **Path**: `packages/ai-parrot/tests/unit/stores/utils/test_contextual.py` and
  `packages/ai-parrot/tests/integration/stores/test_contextual_pgvector.py`
- **Responsibility**: See §4.

### Module 6: Documentation
- **Path**: `docs/contextual-embedding.md`
- **Responsibility**: How to enable per store, what the default template
  produces, how to override, examples of resulting embedded text, and the
  warning about backfilling existing collections.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_build_contextual_text_all_fields_present` | 1 | Default template with full `document_meta` produces the expected one-liner header. |
| `test_build_contextual_text_partial_fields` | 1 | Only `title` present → `"Title: A\n\n{content}"`, no orphan pipes. |
| `test_build_contextual_text_no_meta` | 1 | Empty/missing `document_meta` → returns `(content, "")`. |
| `test_build_contextual_text_skips_none_and_empty_string` | 1 | Both `None` and `""` are treated as missing — no `"Title: None"` ever. |
| `test_build_contextual_text_custom_string_template` | 1 | Template `"[{title}] {content}"` works end-to-end. |
| `test_build_contextual_text_custom_callable_template` | 1 | Callable template receives `document_meta` dict, returns string. |
| `test_build_contextual_text_unknown_placeholder_renders_empty` | 1 | Template referencing `{nonexistent}` does not raise; renders empty. |
| `test_build_contextual_text_caps_header_tokens` | 1 | A 500-token title is truncated; chunk content is preserved verbatim. |
| `test_build_contextual_text_is_deterministic` | 1 | Same `(document, template)` → same `(text, header)` across 100 invocations. |
| `test_apply_contextual_augmentation_off_path_unchanged` | 2 | With flag False, returned list equals `[d.page_content for d in docs]` exactly. |
| `test_apply_contextual_augmentation_writes_header_metadata` | 2 | With flag True, every input document has `metadata['contextual_header']` set. |
| `test_apply_contextual_augmentation_does_not_mutate_page_content` | 2 | After call, `doc.page_content` is byte-equal to before. |

### Integration Tests

| Test | Description |
|---|---|
| `test_pgvector_add_documents_contextual_off_baseline` | Insert 10 docs with flag off; embeddings are computed on raw `page_content` (assert via mock embeddings client). |
| `test_pgvector_add_documents_contextual_on_uses_header` | Same docs with flag on; embeddings are computed on `header + content`; `contextual_header` column/metadata is populated. |
| `test_pgvector_from_documents_contextual_on` | Full ingestion path with chunking + contextual augmentation — chunks get the parent doc's `document_meta`-based header. |
| `test_retrieval_quality_lift_smoke` | A small smoke set: 5 queries × 20 docs, with and without contextual headers; assert at least one query that fails without the header succeeds with it. Not a hard quality gate — calibration is a follow-up. |

### Test Data / Fixtures

```python
@pytest.fixture
def doc_with_full_meta():
    return Document(
        page_content="You will receive it on the 15th of every month.",
        metadata={
            "document_meta": {
                "title": "Employee Handbook",
                "section": "Compensation",
                "category": "HR Policy",
                "language": "en",
            }
        },
    )

@pytest.fixture
def doc_with_no_meta():
    return Document(
        page_content="Standalone passage.",
        metadata={},
    )
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `parrot/stores/utils/contextual.py` exists exporting
      `build_contextual_text`, `DEFAULT_TEMPLATE`, `DEFAULT_MAX_HEADER_TOKENS`.
- [ ] `AbstractStore` accepts `contextual_embedding`,
      `contextual_template`, and `contextual_max_header_tokens` kwargs.
      All default to off / sensible values.
- [ ] `PgVectorStore.add_documents` and `from_documents` use the helper
      when `contextual_embedding=True`; identical behaviour to today when
      False (regression test passes byte-for-byte).
- [ ] At least three additional stores wired (target list:
      `milvus`, `faiss_store`, `arango`); remaining stores documented in
      §8 as follow-ups.
- [ ] `Document.page_content` is never mutated by the augmentation path —
      asserted by unit and integration tests.
- [ ] `Document.metadata['contextual_header']` is populated on every
      ingested chunk when the flag is on (empty string is acceptable).
- [ ] Header is capped at `contextual_max_header_tokens` (whitespace
      tokenised) — long titles do not blow up the embedding input.
- [ ] No new external dependencies. The helper is stdlib only.
- [ ] Documentation page in `docs/contextual-embedding.md` with examples
      and the migration warning.
- [ ] Behaviour is documented as **dependent** on
      `ai-parrot-loaders-metadata-standarization` having been merged —
      `document_meta` must be canonical for the helper to produce
      meaningful headers; otherwise the helper degrades gracefully to
      passthrough.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.stores.abstract import AbstractStore     # verified: parrot/stores/abstract.py:17
from parrot.stores.models import Document            # verified: parrot/stores/models.py:21
from parrot.stores.utils.chunking import LateChunkingProcessor  # exists, sibling helper
```

### Existing Class Signatures (re-verified 2026-04-27)

```python
# packages/ai-parrot/src/parrot/stores/abstract.py:17
class AbstractStore(ABC):
    def __init__(self, ...): ...                                            # line 32

    @abstractmethod
    async def from_documents(                                                # line 175
        self,
        documents: List[Any],
        collection: Union[str, None] = None,
        **kwargs,
    ) -> Callable: ...

    @abstractmethod
    async def add_documents(                                                 # line 207
        self,
        documents: List[Any],
        collection: Union[str, None] = None,
        **kwargs,
    ) -> None: ...
```

```python
# packages/ai-parrot/src/parrot/stores/postgres.py
class PgVectorStore(AbstractStore):
    async def add_documents(self, documents, collection=None, **kwargs) -> None: ...   # line 586
    async def from_documents(self, documents, collection=None, **kwargs) -> Callable: ...  # line 2551
```

```python
# packages/ai-parrot/src/parrot/stores/models.py
class SearchResult(BaseModel): ...    # line 7
class Document(BaseModel): ...        # line 21
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `build_contextual_text` | `Document.metadata['document_meta']` | dict read | depends on `ai-parrot-loaders-metadata-standarization` |
| `AbstractStore._apply_contextual_augmentation` | `build_contextual_text` | direct call | new method on existing class |
| `PgVectorStore.add_documents` | `_apply_contextual_augmentation` | replaces inline list comprehension | `parrot/stores/postgres.py:586` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/stores/utils/contextual.py`~~ — created by this feature.
- ~~`AbstractStore.contextual_embedding`~~ — attribute does not exist.
- ~~`AbstractStore._apply_contextual_augmentation`~~ — method does not exist.
- ~~`Document.contextual_header`~~ — top-level attribute. The header lives in
  `metadata['contextual_header']`, not as a Document field.
- ~~Modifying `embed_documents` in any of `parrot/embeddings/*.py`~~ — out of
  scope. Embedding clients keep their `List[str]` signature.
- ~~A header builder in `parrot/loaders/`~~ — explicitly NOT here. Loaders
  remain free of store concerns.
- ~~An LLM-based header generator~~ — out of scope by design.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pure function for `build_contextual_text` — no I/O, no logging, no side
  effects. Trivially testable.
- Use `string.Formatter` with a `partial_format`-style approach that does
  NOT raise on missing keys; missing → empty string.
- Whitespace tokenisation for the header cap. We do not pull a tokeniser
  dep just for a soft safety belt.
- Default template stays as a module-level constant so users can compose
  their own around it (e.g. `f"{DEFAULT_TEMPLATE}\n[Source: {source}]"`).
- Stores write `metadata['contextual_header']` BEFORE upsert so the column /
  metadata field is populated atomically with the row.
- Logging at `self.logger.debug` per chunk is too noisy at field scale.
  Log a single summary line per `add_documents` call: number of docs,
  number with non-empty headers, average header length.

### Known Risks / Gotchas

1. **Template-injection from metadata values.** A malicious document could put
   `"{content}{content}{content}"` in a metadata field and break formatting.
   Mitigation: render only via `str.format_map` over a sanitised view of
   `document_meta`, not over arbitrary metadata. Reject curly braces in
   metadata values when formatting (escape `{` to `{{`).
2. **Embedding model max-length blow-up.** If a title is 1000 tokens (rare but
   possible), the header alone could exceed the model's input. The cap protects
   against this, but the cap is approximate (whitespace-based). Document that
   downstream tokenisers may still truncate.
3. **Chunks that already had a "header"** (legacy, hand-rolled). The helper
   does not detect this. Re-ingestion produces double headers. Document that
   collections must be re-built when the flag is flipped, not retroactively
   patched.
4. **Multi-language headers**. The default template uses English keywords
   ("Title", "Section", "Category"). For Spanish/French corpora, embedding
   models may give slightly different scores. The override mechanism is the
   answer; flag this in docs.
5. **Determinism vs upstream metadata changes**. If `document_meta.title`
   changes between two ingestions, the embedding will change. This is correct
   behaviour but a re-indexing trigger that ops needs to know about.
6. **`LateChunkingProcessor` already builds its own contextual text** in
   `parrot/stores/utils/chunking.py:174` (`_create_contextual_text`) using raw
   neighbouring text. The two contextualisations are orthogonal: late-chunking
   uses surrounding text, this spec uses metadata-derived headers. They CAN
   compose (header + neighbour-context + chunk), but for v1 we apply *only one
   or the other* per insertion, with metadata-header winning when both are
   configured. Document this precedence.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none) | — | No new dependencies. The feature is stdlib + existing Pydantic. |

---

## 8. Open Questions

- [ ] Default cap of 100 tokens vs 50 tokens for the header. 100 is generous;
      if benchmarks show 50 is enough, lower it to keep more chunk tokens
      available. — *Owner: implementation, decided after FEAT-126 benchmark.*
- [ ] Should `contextual_header` also be returned in `SearchResult.metadata`
      so retrieval-time code can re-build the augmented text for debugging /
      reranking experiments? Yes is cheap; just confirming. — *Owner: Jesus Lara*: Yes.
- [ ] When BOTH `LateChunkingProcessor` (`store_full_document=True`) and
      `contextual_embedding=True` are configured, do we apply the metadata
      header on top of late-chunking's own contextual text? My recommendation:
      no — the precedence is metadata-header wins. — *Owner: Jesus Lara*: No
- [ ] List of stores to wire in v1 (postgres + milvus + faiss + arango) vs v2
      (bigquery, chroma, others). Postgres is non-negotiable; others can land
      incrementally. — *Owner: implementation*: postgres is mainstream, other can be land incrementally.
- [ ] Migration tooling: do we ship a `scripts/recompute_contextual_embeddings.py`
      that re-embeds an existing collection in place, or leave that to ops? —
      *Owner: Jesus Lara*: create the migration tooling.

---

## Worktree Strategy

**Default isolation unit: `per-spec` (sequential tasks).**

Tasks form a chain: helper (Module 1) → AbstractStore wiring (Module 2) →
postgres (Module 3) → other stores (Module 4) → tests (Module 5) → docs
(Module 6). Modules 4 sub-tasks (per-store wirings) are mutually independent
and could parallelise, but the surface is small enough that sequential
execution in one worktree is simpler and avoids merge churn on store files.

```bash
git worktree add -b feat-127-contextual-embedding-headers \
  .claude/worktrees/feat-127-contextual-embedding-headers HEAD
```

**Cross-feature dependencies**:

- **Hard dependency** on `ai-parrot-loaders-metadata-standarization` being
  merged before this feature lands in production. The helper degrades to
  passthrough without canonical `document_meta`, so dev work can begin in
  parallel, but acceptance testing requires the standardisation in dev.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-27 | Jesus Lara | Initial draft from in-conversation design. |
