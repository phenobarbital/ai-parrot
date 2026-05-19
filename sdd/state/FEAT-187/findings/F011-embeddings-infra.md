---
id: F011
query: Q015
type: tree+read
target: packages/ai-parrot/src/parrot/embeddings/
---

# F011 — Embeddings Infrastructure

**Status**: Confirmed — independent module, proposal correction needed

## Location
`packages/ai-parrot/src/parrot/embeddings/`

## EmbeddingModel (ABC) — base.py
- Abstract method: `encode(texts, **kwargs) -> np.ndarray`
- Also: `embed_documents()`, `embed_query()`
- GPU device detection
- Registry integration

## Providers
| Provider | File | Class |
|----------|------|-------|
| HuggingFace | huggingface.py | SentenceTransformerModel |
| OpenAI | openai.py | OpenAIEmbeddingModel |
| Google | google.py | GoogleEmbeddingModel |

## EmbeddingRegistry — registry.py
- Process-wide singleton with LRU eviction
- Async locks, per-key caching by `(model_name, model_type, matryoshka_dim)`

## Matryoshka support — matryoshka.py
Variable-dimension embeddings with catalog validation (FEAT-150)

## Catalog — catalog.py (~50KB)
Comprehensive model catalog with recommendations and use-case descriptions

## CRITICAL for proposal
The Embed stage (Stage 2) should use `parrot.embeddings.EmbeddingModel` and
`EmbeddingRegistry`, NOT `AbstractClient`. The proposal's open question about
embedding model (`text-embedding-004` vs `gemini-embedding-001`) should also
consider the existing HuggingFace provider with models from the catalog.

The user's note "using huggingfaces embedding models" in the open questions
aligns perfectly with the existing `SentenceTransformerModel` provider.
