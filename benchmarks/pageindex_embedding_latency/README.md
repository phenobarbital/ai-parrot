# PageIndex Embedding Latency Benchmark

FEAT-237 TASK-1551 — CPU latency micro-benchmark for PageIndex embedding models.

## Purpose

Measures embedding inference latency (p50 + p95), peak RSS memory, and
recall@k across the matrix of candidate models x backends x output dimensions
defined in `harness.py`.  Results drive the model selection for the default
`PageIndexToolkit` embedding backend.

## Benchmark Matrix

| Model | Backends | Dimensions |
|---|---|---|
| `Qwen/Qwen3-Embedding-0.6B` | torch, onnx | 512, 256 |
| `Octen/Octen-Embedding-0.6B` | torch, onnx | 512, 256 |
| `intfloat/multilingual-e5-small` | torch | 384 |
| `minishlab/potion-base-8M` | torch | 256 |

## Environment Setup

```bash
# Activate the virtual environment first
source .venv/bin/activate

# Install benchmark dependencies (sentence-transformers, onnxruntime, etc.)
uv pip install sentence-transformers onnxruntime

# Optional: build the compliance corpus first (larger, more realistic oracle)
python -m corpus.compliance_soc2_hipaa.fetch
python -m corpus.compliance_soc2_hipaa.build_tree --use-vec-rank
```

## Running the Benchmark

### Quick smoke run (no corpus, synthetic probe texts)

```bash
python -m benchmarks.pageindex_embedding_latency.harness \
    --output-dir /tmp/bench_results \
    --min-repeats 5 \
    --warmup 0
```

### Full benchmark against the compliance corpus

```bash
python -m benchmarks.pageindex_embedding_latency.harness \
    --storage-dir corpus/compliance_soc2_hipaa/trees \
    --tree-name nist_800_53 \
    --output-dir benchmarks/pageindex_embedding_latency/results
```

### Single model

```bash
python -m benchmarks.pageindex_embedding_latency.harness \
    --model "intfloat/multilingual-e5-small" \
    --output-dir /tmp/bench_results
```

## Output

After running, the output directory contains:

- `results.json` — machine-readable results (all configurations)
- `report.md` — markdown table + recommendation gate

## Interpreting Results

| Metric | Meaning |
|---|---|
| `p50_ms` | Median inference latency (per batch of 50 texts) |
| `p95_ms` | 95th-percentile latency — the **gate metric** |
| `p99_ms` | Tail latency |
| `rss_mb` | Peak resident set size at benchmark end |
| `recall_at_10` | Fraction of oracle-relevant nodes in top-10 embeddings |

**Status values:**

- `OK` — p95 below the latency gate (default: 200 ms)
- `WARN (slow)` — p95 above the latency gate (still measured, but flagged)
- `FAILED` — model could not be loaded or bench failed (check `error` field)

The **recommendation** section identifies the configuration with the lowest
p95 latency among non-failed entries.

## Reproducibility

The harness pins BLAS/OMP/MKL threads to 1 at import time:

```
OMP_NUM_THREADS=1  MKL_NUM_THREADS=1  OPENBLAS_NUM_THREADS=1
```

This ensures latency numbers are comparable across machines with different
CPU core counts.  For benchmarks on multi-core hardware, set these to the
number of physical cores before running:

```bash
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
    python -m benchmarks.pageindex_embedding_latency.harness …
```

## Unit Tests

The metric calculation functions have isolated unit tests:

```bash
pytest tests/benchmarks/test_benchmark_metrics.py -v
```

These tests do NOT require any ML models or corpus files.
