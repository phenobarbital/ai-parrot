---
type: Wiki Overview
title: 'TASK-1489: Multimodal Embedding Benchmark Harness'
id: doc:sdd-tasks-active-task-1489-benchmark-harness-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task delivers the benchmark harness that serves as a decision gate:
  it'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.embeddings.multimodal
  rel: mentions
- concept: mod:parrot.embeddings.multimodal.quantization
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
---

# TASK-1489: Multimodal Embedding Benchmark Harness

**Feature**: FEAT-229 — Multimodal Embedding Provider
**Spec**: `sdd/specs/multimodal-embedding-provider.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1486, TASK-1488
**Assigned-to**: unassigned

---

## Context

This task delivers the benchmark harness that serves as a decision gate: it
determines whether UForm's multilingual text quality justifies adoption over
the current text embedder, and quantifies cross-modal + cost advantages. The
benchmark runs end-to-end on synthetic fallback data and is pluggable for
real Spanish domain data.

Implements spec §3 (Module 6) and the benchmark plan from the brainstorm §7.

---

## Scope

- Create `benchmarks/multimodal_embedding_benchmark.py` with:
  - **Models under test**: UForm multilingual-base, UForm english-large,
    current HF text embedder baseline (pluggable model ID), multilingual-e5-large.
  - **Text retrieval metrics**: Recall@{1,5,10}, MRR, nDCG@10.
  - **Matryoshka recall curve**: same metrics at dims {768, 512, 256, 128, 64}.
  - **Quantization recall delta**: f32 vs i8 vs b1.
  - **Throughput**: embeddings/sec, latency p50/p95 (CPU).
  - **Footprint**: model size on disk, embedding dim, estimated PgVector index size.
  - **Cross-modal** (if image fixtures available): image->text and text->image Recall@k.
  - **Synthetic fallback dataset**: 20-30 query/doc pairs in English + Spanish.
  - **Output**: markdown report + CSV for each metric table.
  - **Decision rule**: document the threshold (within ~3% nDCG@10 of best text baseline).
- Create `benchmarks/fixtures/` with tiny synthetic test data.
- Document how to plug real Spanish domain data (query, relevant_doc_id CSV).

**NOT in scope**: running the benchmark with real domain data (operator task),
modifying any implementation code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `benchmarks/multimodal_embedding_benchmark.py` | CREATE | Main benchmark script |
| `benchmarks/fixtures/synthetic_queries.json` | CREATE | Synthetic query/doc pairs |
| `benchmarks/fixtures/README.md` | CREATE | How to plug real domain data |
| `benchmarks/requirements-benchmark.txt` | CREATE | Benchmark-specific deps |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.embeddings.multimodal import UFormEmbedding, EmbeddingBackend, QuantizationMode  # created in TASK-1484/1486
from parrot.embeddings.multimodal.quantization import matryoshka_slice, l2_normalize  # created in TASK-1485
from parrot.embeddings.registry import EmbeddingRegistry  # verified: packages/ai-parrot/src/parrot/embeddings/registry.py:51
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry:                               # line 51
    async def get_or_create(self, model_name, model_type="huggingface", **kwargs) -> Any:  # line 218

# The benchmark should instantiate models directly for controlled comparison,
# not necessarily through the registry. Direct instantiation pattern:
# provider = UFormEmbedding(model_name="...", backend=EmbeddingBackend.TORCH)
# await provider.initialize_model()
# result = await provider.embed_text(texts)
```

### Does NOT Exist
- ~~`benchmarks/` directory~~ — may not exist; create it
- ~~`parrot.benchmarks`~~ — not a package; benchmark is a standalone script
- ~~`EmbeddingModel.benchmark()`~~ — no such method

---

## Implementation Notes

### Key Constraints
- Benchmark script should be runnable standalone: `python benchmarks/multimodal_embedding_benchmark.py`
- Must work without GPU (CPU-only mode)
- Synthetic data must be small enough to run in <5 minutes on CPU
- Output both markdown (human-readable) and CSV (programmatic) reports
- Include clear TODO markers for plugging real domain data:
  ```python
  # TODO: Replace with real Spanish domain data
  # Format: CSV with columns (query_id, query_text, relevant_doc_id, doc_text)
  ```
- Decision rule documented in the output report header

### References in Codebase
- `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py` — current text embedder to use as baseline
- Spec §7 (Benchmark Plan) — full metric definitions and decision rules

---

## Acceptance Criteria

- [ ] Benchmark runs end-to-end on synthetic fallback data
- [ ] Produces markdown report with all metric tables
- [ ] Produces CSV files for programmatic access
- [ ] Matryoshka recall curve at dims {768, 512, 256, 128, 64}
- [ ] Quantization delta: f32 vs i8 vs b1
- [ ] Throughput numbers (emb/sec, p50/p95 latency)
- [ ] Decision rule documented in report
- [ ] Clear documentation for plugging real domain data
- [ ] Runs without GPU (CPU-only)
- [ ] Script exits cleanly: `python benchmarks/multimodal_embedding_benchmark.py --help`

---

## Test Specification

```python
# The benchmark itself IS the test artifact.
# Verify it runs end-to-end without errors:

# bash: python benchmarks/multimodal_embedding_benchmark.py --synthetic-only --output-dir /tmp/bench_test
# Expected: /tmp/bench_test/report.md exists, /tmp/bench_test/*.csv files exist
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1486 and TASK-1488 are in `sdd/tasks/completed/`
3. **Verify** UForm and baseline models can be loaded
4. **Update status** in `sdd/tasks/index/multimodal-embedding-provider.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Run the benchmark** on synthetic data to verify it completes
7. **Move this file** to `sdd/tasks/completed/TASK-1489-benchmark-harness.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
