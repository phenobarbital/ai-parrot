---
id: F006
query_id: Q008
type: read
intent: Verify how the Embeddings Registry resolves concrete classes.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 60
parent_id: null
depth: 0
---

# F006 — `EmbeddingRegistry` resolves backends by **import string**

## Summary

`EmbeddingRegistry._build_model()` resolves a concrete embedding class
by building a module path string `f"parrot.embeddings.{model_type}"` and
importing it dynamically via `importlib.import_module`. There is no
compile-time coupling between the Registry and the concrete classes —
which is exactly the property that makes the FEAT-201 split safe: as
long as `parrot.embeddings.huggingface` resolves to the right module at
runtime (via namespace extension), the Registry keeps working unchanged.

## Citations

- path: `packages/ai-parrot/src/parrot/embeddings/registry.py`
  lines: 149-178
  symbol: `EmbeddingRegistry._build_model`
  excerpt: |
    def _build_model(self, model_name: str, model_type: str, **kwargs) -> Any:
        if model_type not in self._supported_embeddings:
            raise ValueError(...)
        cls_name = self._supported_embeddings[model_type]
        module_path = f"parrot.embeddings.{model_type}"
        try:
            module = importlib.import_module(module_path)
            klass = getattr(module, cls_name)
            return klass(model_name=model_name, **kwargs)
        except ImportError as exc:
            raise ImportError(...)

- path: `packages/ai-parrot/src/parrot/embeddings/registry.py`
  lines: 71-93
  symbol: `EmbeddingRegistry.__init__`
  excerpt: |
    _instance: Optional["EmbeddingRegistry"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self, max_models: int = None) -> None:
        from . import supported_embeddings as _supported_embeddings
        from ..conf import EMBEDDING_REGISTRY_MAX_MODELS
        self._supported_embeddings = _supported_embeddings
        ...

- path: `packages/ai-parrot/src/parrot/embeddings/__init__.py`
  lines: 14-18
  symbol: `supported_embeddings`
  excerpt: |
    supported_embeddings = {
        'huggingface': 'SentenceTransformerModel',
        'google': 'GoogleEmbeddingModel',
        'openai': 'OpenAIEmbeddingModel',
    }

## Notes

- The Registry depends on `supported_embeddings` (a dict in
  `parrot.embeddings.__init__`). This dict **must stay in core** because
  it's the dispatch table and is consumed by the Registry on instance
  initialization. The new package contributes the concrete classes, not
  the dispatch table.
- Same pattern in `parrot.stores.__init__` (see F007).
