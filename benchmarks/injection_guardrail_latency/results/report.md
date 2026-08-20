# Prompt-Injection Guardrail Benchmark

Baseline for `PromptInjectionGuardrail` — regex vs embedding-similarity vs the deBERTa classifier under torch / ONNX / ONNX-int8.

## Setup

- Classifier: `protectai/deberta-v3-base-prompt-injection`
- Embedder: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- ORT / torch thread cap: `2` (BLAS/OMP pinned to 1)
- Timed passes: 10 × 96 samples (warm-up 5)
- Per-tier process isolation: `True`
- Python 3.12.3

Corpus: `clean` 34, `clean_framework` 12, `attack_direct` 20, `attack_paraphrase` 20, `attack_obfuscated` 10 — **96 total**, seed catalogue 22 (held disjoint from every eval bucket).

## 1. Cost per tier

| Tier | load (s) | RSS Δ (MB) | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) | inline-safe | status |
|---|---|---|---|---|---|---|---|---|
| `regex` | 0.00 | 0.0 | 0.01 | 0.02 | 0.02 | 0.03 | yes | ok |
| `embed-cosine-torch` | 26.76 | 2365.4 | 7.78 | 8.56 | 9.48 | 21.82 | **no** | ok |
| `clf-torch` | 7.27 | 1503.3 | 118.99 | 145.83 | 158.18 | 193.61 | **no** | ok |
| `clf-onnx` | 5.59 | 1910.7 | 32.96 | 59.85 | 65.97 | 81.11 | **no** | ok |
| `clf-onnx-int8` | 5.06 | 1392.5 | 21.08 | 41.15 | 42.62 | 49.85 | **no** | ok |

*inline-safe* = p95 ≤ 5 ms, the budget for an on-loop guardrail stage. Anything above belongs behind `run_in_executor` with a `BudgetRouter`/`CircuitBreaker` (see the comparison doc §5.2).

## 2. Detection quality

| Tier | thr | precision | recall | F1 | FP | FN | best-F1 thr | best F1 |
|---|---|---|---|---|---|---|---|---|
| `regex` | 0.90 | 0.92 | 0.24 | 0.38 | 1 | 38 | 0.60 | 0.43 |
| `embed-cosine-torch` | 0.85 | 1.00 | 0.02 | 0.04 | 0 | 49 | 0.40 | 0.87 |
| `clf-torch` | 0.98 | 0.90 | 0.70 | 0.79 | 4 | 15 | 0.98 | 0.79 |
| `clf-onnx` | 0.98 | 0.90 | 0.70 | 0.79 | 4 | 15 | 0.98 | 0.79 |
| `clf-onnx-int8` | 0.98 | 0.00 | 0.00 | 0.00 | 0 | 50 | 0.50 | 0.04 |

`thr` is the threshold the tier would run at in production. For `clf-*` that is AI-Parrot's current `injection_probability_threshold=0.98`; the best-F1 column shows what the same model would score if it were retuned.

## 2b. Numerical parity vs the PyTorch reference

| Backend | max \|Δ\| | mean \|Δ\| | flipped verdicts | parity |
|---|---|---|---|---|
| `clf-onnx` | 0.000 | 0.000 | 0 (0.0%) | ok |
| `clf-onnx-int8` | 1.000 | 0.449 | 39 (40.6%) | **FAILED** |

Same weights, same inputs — so scores must agree within numerical noise. A backend that fails here is **not** a faster version of the model; it is a different, wrong function that happens to run faster.

> ⚠️ **Do not read the latency table as a win for `clf-onnx-int8`.** Its timings are real; its answers are not.

## 3. Where each tier is blind

| Tier | `attack_direct` | `attack_obfuscated` | `attack_paraphrase` | `clean` | `clean_framework` |
|---|---|---|---|---|---|
| `regex` | 55.0% | 10.0% | 0.0% | 2.9% | 0.0% |
| `embed-cosine-torch` | 0.0% | 0.0% | 5.0% | 0.0% | 0.0% |
| `clf-torch` | 75.0% | 100.0% | 50.0% | 11.8% | 0.0% |
| `clf-onnx` | 75.0% | 100.0% | 50.0% | 11.8% | 0.0% |
| `clf-onnx-int8` | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

Flag rate per bucket. For `clean*` buckets **lower is better** (false positives); for `attack_*` buckets **higher is better** (recall). `clean_framework` is the `<user_context>` wrapper AI-Parrot's integrations inject — a tier that flags those is unusable in Telegram/Slack.

## 4. Tiering — does the classifier earn its keep?

Composed: `regex` → `embed-cosine-torch` → `clf-torch` @ 0.98.

| cosine band (low, high) | escalation | escalated n | precision | recall | F1 | effective p50 (ms) | vs classifier-always |
|---|---|---|---|---|---|---|---|
| (0.20, 0.45) | 46.9% | 45 | 0.90 | 0.90 | 0.90 | 63.559 | 1.9× |
| (0.25, 0.50) | 49.0% | 47 | 0.90 | 0.86 | 0.88 | 66.038 | 1.8× |
| (0.30, 0.55) | 42.7% | 41 | 0.89 | 0.80 | 0.84 | 58.601 | 2.0× |
| (0.30, 0.60) | 46.9% | 45 | 0.91 | 0.78 | 0.84 | 63.559 | 1.9× |
| (0.35, 0.60) | 35.4% | 34 | 0.90 | 0.76 | 0.83 | 49.925 | 2.4× |

*effective p50* = regex + cosine (always) + escalation × classifier. Classifier-always would be 118.99 ms p50 on every turn.

Quality here is **measured, not projected**: escalated samples are scored with the classifier's real output, not assumed correct.

## Caveats

- Single machine, single run — treat **ratios** as robust and absolute numbers as indicative, the same standard applied in `sdd/proposals/pii-detection-redaction.comparison.md` §6.
- The corpus is synthetic and small (tens per bucket). It is built to expose *structural* blind spots (paraphrase, obfuscation, framework wrappers), not to estimate production accuracy.
- Latency is measured per single call. Real seams may batch; a batched classifier amortises far better than these numbers suggest.
- int8 dynamic quantization is calibration-free; static quantization with a calibration corpus would likely be faster still, and is untested here.
