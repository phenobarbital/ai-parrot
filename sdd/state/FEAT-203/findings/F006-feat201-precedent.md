---
id: F006
query: "FEAT-201 PEP 420 precedent pattern"
type: read
---

## Finding: ai-parrot-embeddings extraction pattern

### Package structure:
```
packages/ai-parrot-embeddings/src/parrot/
├── .gitkeep (NO __init__.py)
├── embeddings/ (.gitkeep, NO __init__.py)
│   ├── google.py, huggingface.py, openai.py, version.py
├── stores/ (.gitkeep, NO __init__.py)
│   ├── postgres.py, pgvector.py, milvus.py, arango.py, bigquery.py, faiss_store.py
└── rerankers/ (.gitkeep, NO __init__.py)
    ├── local.py, llm.py
```

### Key patterns:
1. NO __init__.py at namespace levels (PEP 420)
2. Host __init__.py calls extend_path(__path__, __name__)
3. Host uses lazy __getattr__ or string-dispatch (importlib.import_module)
4. Satellite depends on ai-parrot (core)
5. Host meta-extras pull satellite: `all = ["ai-parrot[...], ai-parrot-embeddings[all]"]`
6. pyproject.toml: `namespaces = true` in [tool.setuptools.packages.find]
7. Dynamic version via version.py in satellite
8. Wheel-content test verifies zero __init__.py at namespace levels
9. Namespace-import test verifies cross-distribution imports

### What stayed in core:
- Abstract base classes (AbstractStore, EmbeddingModel, AbstractReranker)
- Registries, catalogs, factories
- Models (SearchResult, Document, DistanceStrategy)
- The supported_* dispatch dicts
