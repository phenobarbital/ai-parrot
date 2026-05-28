---
id: F005
query_id: Q005
type: tree
intent: Enumerate the parrot.rerankers module tree.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 30
parent_id: null
depth: 0
---

# F005 — `parrot/rerankers/` tree: 2 concrete rerankers + abstract/factory/models

## Summary

The rerankers subsystem is the smallest of the three (6 Python files).
2 concrete rerankers (`local.py` — cross-encoder, `llm.py` — LLM-based)
plus abstract base, factory, models, and public `__init__.py`.

## Citations

- path: `packages/ai-parrot/src/parrot/rerankers/`
  lines: null
  symbol: tree
  excerpt: |
    rerankers/
    ├── __init__.py          ← AbstractReranker re-export + lazy __getattr__ (STAYS)
    ├── abstract.py          ← AbstractReranker (STAYS in core)
    ├── models.py            ← RerankedDocument, RerankerConfig Pydantic models (STAYS)
    ├── factory.py           ← create_reranker() dispatcher (STAYS in core)
    ├── local.py             ← LocalCrossEncoderReranker (MOVES → [reranker-local])
    └── llm.py               ← LLMReranker (MOVES → [reranker-llm])

- path: `packages/ai-parrot/src/parrot/rerankers/__init__.py`
  lines: 30-50
  symbol: `__getattr__` (lazy import)
  excerpt: |
    def __getattr__(name: str):
        if name == "LocalCrossEncoderReranker":
            from parrot.rerankers.local import LocalCrossEncoderReranker
            return LocalCrossEncoderReranker
        if name == "LLMReranker":
            from parrot.rerankers.llm import LLMReranker
            return LLMReranker
        raise AttributeError(...)

- path: `packages/ai-parrot/src/parrot/rerankers/factory.py`
  lines: 26-83
  symbol: `create_reranker`
  excerpt: |
    from parrot.rerankers.abstract import AbstractReranker
    # line 54:
    from parrot.rerankers.local import LocalCrossEncoderReranker  # noqa: PLC0415
    # line 83:
    from parrot.rerankers.llm import LLMReranker  # noqa: PLC0415

## Notes

- The rerankers `__init__.py` and `factory.py` already use **lazy
  imports** (module-level `__getattr__` + local `import` inside
  `create_reranker`). This is exactly the resolution pattern that
  survives unchanged across a namespace-package split — neither imports
  concrete classes at module load time.
- No existing extras in the host pyproject isolate reranker
  dependencies — they currently piggy-back on `embeddings` /
  `agents`. FEAT-201 introduces new extras (e.g.
  `[reranker-local]` requiring `sentence-transformers` /
  `cross-encoder` deps; `[reranker-llm]` requiring nothing beyond core).
