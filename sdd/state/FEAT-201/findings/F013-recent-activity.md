---
id: F013
query_id: Q021/Q022/Q023
type: git_log
intent: Confirm no in-flight refactor collision on the three subsystems.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 120
parent_id: null
depth: 0
---

# F013 — All three subsystems have active recent work; coordination required

## Summary

The 90-day git log shows continuous work on all three subsystems —
heaviest on embeddings (matryoshka truncation FEAT-150, catalog work),
followed by stores (contextual embedding, PgVector metadata_filters,
parent-child retrieval factory FEAT-128/133), and lightest on rerankers
(reranker factory + cross-encoder reranker FEAT-133). No active SDD
spec references "ai-parrot-embeddings" or a packaging refactor, so no
direct collision exists today — but FEAT-201 must merge cleanly with the
matryoshka and contextual-embedding work that landed in the past 90 days.

## Citations

- path: `packages/ai-parrot/src/parrot/embeddings/`
  lines: null
  symbol: 90-day commit themes (top 8 of 15+)
  excerpt: |
    2c72af9c embedding catalog
    2f37c5b3 implementing matryoska vector truncation
    7f2d5b99 feat(matryoshka-embedding-truncation): TASK-1039 — integration tests and documentation
    d48ec222 feat(matryoshka-embedding-truncation): TASK-1036 — EmbeddingRegistry Matryoshka cache key
    fe949c6d feat(matryoshka-embedding-truncation): TASK-1035 — SentenceTransformerModel Matryoshka encoding
    b3f25477 feat(matryoshka-embedding-truncation): TASK-1034 — MatryoshkaConfig Pydantic model + catalog validator
    47615dd1 feat(embedding-catalog-as-prefix-source-of-truth): TASK-973 — Refactor _resolve_prefixes
    c01257b2 feat(embeddings-catalog-update): TASK-962/963/964/965/966 — full catalog schema extension and new models

- path: `packages/ai-parrot/src/parrot/stores/`
  lines: null
  symbol: 90-day commit themes (top 9 of 15+)
  excerpt: |
    21039d51 fix(concept-document-authority): address 5 code-review issues
    c5904533 feat(concept-document-authority): TASK-1087 — PgVectorStore metadata_filters extension
    ff1f5435 feat(ephemeral-agents): TASK-1037 — FAISS S3 persistence
    84ce2866 feat(matryoshka-embedding-truncation): TASK-1037 — AbstractStore.create_embedding forwards matryoshka kwarg
    8647fb87 feat(bot-reranker-and-parent-searcher-config): TASK-906 — Implement parrot/stores/parents/factory.py + unit tests
    f3f80ee1 feat(contextual-embedding-headers): TASK-864/865/866 — Wire Milvus/FAISS/Arango stores to augmentation hook
    66475ac2 feat(contextual-embedding-headers): TASK-863 — Wire PgVectorStore add_documents/from_documents to augmentation hook
    595544e9 feat(contextual-embedding-headers): TASK-862 — Wire _apply_contextual_augmentation into AbstractStore

- path: `packages/ai-parrot/src/parrot/rerankers/`
  lines: null
  symbol: 90-day commit themes (5 commits)
  excerpt: |
    32d17205 fix(feat-133): address code review issues — factory guards, logging, dead code, DDL
    499c4d18 feat(bot-reranker-and-parent-searcher-config): TASK-905 — Implement parrot/rerankers/factory.py + unit tests
    bc927376 feat(local-cross-encoder-reranker): TASK-865 — LLMReranker Debug Implementation
    18b1c64e feat(local-cross-encoder-reranker): TASK-864 — LocalCrossEncoderReranker Implementation
    b0f171fa feat(local-cross-encoder-reranker): TASK-863 — Reranker Data Models and Abstract Base Class

## Notes

- **Matryoshka (FEAT-150)** is the most recent embeddings feature and
  touches `EmbeddingRegistry` (cache-key), `SentenceTransformerModel`
  (encoding), and `AbstractStore.create_embedding` (kwarg forwarding).
  Since `AbstractStore` stays in core and the SentenceTransformer model
  moves to `ai-parrot-embeddings[huggingface]`, the Matryoshka wiring
  must be re-tested across the move.
- **Contextual embedding (FEAT-127/128)** wired contextual augmentation
  into Milvus / FAISS / Arango / PgVector stores — these wirings move
  with the concrete stores.
- **Parent-child retrieval (FEAT-128)** added `parrot/stores/parents/`
  with a factory pattern. This sub-package likely STAYS in core (it's
  higher-level orchestration over AbstractStore), but the spec phase
  should confirm.
