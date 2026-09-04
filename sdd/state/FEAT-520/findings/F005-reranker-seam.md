# F005 — Re-ranking seam confirmed
**Query**: Q004 | **Confidence**: high

- Contract: `parrot/rerankers/` (core) — `AbstractReranker`, `models.py` (RerankedDocument, RerankerConfig), `factory.py` (config-dict factory, TASK-905).
- Cross-encoder impl: `packages/ai-parrot-embeddings/src/parrot/rerankers/local.py` `LocalCrossEncoderReranker` (HuggingFace, TASK-864); `llm.py` LLMReranker. Wired into AbstractBot retrieval (TASK-866).
- Consumption pattern to copy: `HybridPageIndexSearch._apply_reranker` — builds `parrot.models.stores.SearchResult` docs, `await reranker.rerank(query, docs, top_n=top_k)`, falls back to fused order on error.
⇒ D6 step 4 plugs in exactly as designed.
