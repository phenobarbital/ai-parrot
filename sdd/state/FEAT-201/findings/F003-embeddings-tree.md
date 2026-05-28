---
id: F003
query_id: Q003
type: tree
intent: Enumerate the parrot.embeddings module tree (base vs concrete backends).
executed_at: 2026-05-28T00:00:00Z
duration_ms: 30
parent_id: null
depth: 0
---

# F003 — `parrot/embeddings/` tree: 3 backends + base/registry/catalog/matryoshka

## Summary

The embeddings subsystem is a flat module with 9 Python files. **3 are
concrete backends** (`google.py`, `huggingface.py`, `openai.py`); the rest
are base infrastructure (Abstract, Registry, Catalog, Matryoshka config,
Processor, public `__init__.py`).

## Citations

- path: `packages/ai-parrot/src/parrot/embeddings/`
  lines: null
  symbol: tree
  excerpt: |
    embeddings/
    ├── __init__.py          ← supported_embeddings map + public API
    ├── base.py              ← AbstractEmbeddingModel (STAYS in core)
    ├── registry.py          ← EmbeddingRegistry singleton (STAYS in core)
    ├── catalog.py           ← EMBEDDING_MODELS dict + helpers (STAYS in core)
    ├── matryoshka.py        ← MatryoshkaConfig (Pydantic) (STAYS in core)
    ├── processor.py         ← post-processing helpers (likely STAYS)
    ├── google.py            ← GoogleEmbeddingModel (MOVES → ai-parrot-embeddings[google])
    ├── huggingface.py       ← SentenceTransformerModel (MOVES → [huggingface])
    └── openai.py            ← OpenAIEmbeddingModel (MOVES → [openai])

## Notes

- The base/concrete split is clean here: each backend is a single file
  matching the `model_type` key (`google`, `huggingface`, `openai`) used
  by the Registry's import-string resolution (see F005).
- `processor.py` may have backend-specific code worth a closer look in
  the spec phase, but the user's directive (Abstract/Registry stay) does
  not depend on it.
