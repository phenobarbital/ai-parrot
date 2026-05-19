---
id: F009
query: Q010
type: read
target: packages/ai-parrot/pyproject.toml
---

# F009 — pyproject.toml Extras and Dependencies

**Status**: Confirmed

## Package
`ai-parrot`, version dynamic

## Existing extras (27 total)
embeddings, arango, flowtask, pdf, ocr, audio, finance, scheduler, db, bigquery,
reddit, retrieval, tokenizer, agents, agents-lite, charts, mcp, images, anthropic,
claude-agent, openai, google, groq, llms, integrations, milvus, chroma, eda,
security, xai, gemma4, deploy, docling, filesystem-transport, matrix, otel, dev, all

## embeddings extra includes
sentence-transformers>=5.0.0, **faiss-cpu>=1.9.0**, rank_bm25, sentencepiece,
tiktoken, chromadb, bm25s, simsimd, tokenizers, safetensors, einops, accelerate,
peft, xformers

## faiss-cpu
Present in BOTH core dependencies AND [embeddings] extra (faiss-cpu>=1.9.0)

## New dependencies needed
These are NOT declared anywhere:
- `rustworkx` — new [graphindex] extra
- `tree-sitter` — new [graphindex] extra
- `tree-sitter-languages` — new [graphindex] extra
- `pathspec` — new [graphindex] extra
