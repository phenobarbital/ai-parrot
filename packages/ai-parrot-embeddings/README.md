# ai-parrot-embeddings

Concrete backend implementations for the AI-Parrot retrieval stack:
embedding models, vector stores, and rerankers.

This package contributes modules directly to the `parrot.*` namespace
(via PEP 420 implicit namespace packages), so existing imports such as
`from parrot.stores.pgvector import PgVectorStore` continue to work
byte-identically once installed.

## Install

```bash
# Core framework only (no backends)
pip install ai-parrot

# Add specific backends
pip install ai-parrot-embeddings[pgvector,milvus,huggingface]

# Everything
pip install ai-parrot-embeddings[all]
```

See `docs/migration/feat-201-ai-parrot-embeddings.md` for the migration
guide.
