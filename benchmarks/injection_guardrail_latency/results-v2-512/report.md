# Prompt-Injection Guardrail Benchmark

Baseline for `PromptInjectionGuardrail` — regex vs embedding-similarity vs the deBERTa classifier under torch / ONNX / ONNX-int8.

## Setup

- Classifier: `protectai/deberta-v3-base-prompt-injection-v2`
- Embedder: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- ORT / torch thread cap: `2` (BLAS/OMP pinned to 1)
- Timed passes: 10 × 96 samples (warm-up 5)
- Per-tier process isolation: `True`
- Python 3.12.3

Corpus: `clean` 34, `clean_framework` 12, `attack_direct` 20, `attack_paraphrase` 20, `attack_obfuscated` 10 — **96 total**, seed catalogue 22 (held disjoint from every eval bucket).

## 1. Cost per tier

| Tier | load (s) | RSS Δ (MB) | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) | inline-safe | status |
|---|---|---|---|---|---|---|---|---|
| `clf-torch` | 7.15 | 1621.7 | 124.35 | 154.02 | 160.13 | 182.57 | **no** | ok |
| `clf-onnx` | 5.70 | 1850.8 | 34.79 | 61.57 | 63.75 | 70.52 | **no** | ok |

*inline-safe* = p95 ≤ 5 ms, the budget for an on-loop guardrail stage. Anything above belongs behind `run_in_executor` with a `BudgetRouter`/`CircuitBreaker` (see the comparison doc §5.2).

## 2. Detection quality

| Tier | thr | precision | recall | F1 | FP | FN | best-F1 thr | best F1 |
|---|---|---|---|---|---|---|---|---|
| `clf-torch` | 0.98 | 0.85 | 0.92 | 0.88 | 8 | 4 | 0.98 | 0.88 |
| `clf-onnx` | 0.98 | 0.85 | 0.92 | 0.88 | 8 | 4 | 0.98 | 0.88 |

`thr` is the threshold the tier would run at in production. For `clf-*` that is AI-Parrot's current `injection_probability_threshold=0.98`; the best-F1 column shows what the same model would score if it were retuned.

## 2b. Numerical parity vs the PyTorch reference

| Backend | max \|Δ\| | mean \|Δ\| | flipped verdicts | parity |
|---|---|---|---|---|
| `clf-onnx` | 0.000 | 0.000 | 0 (0.0%) | ok |

Same weights, same inputs — so scores must agree within numerical noise. A backend that fails here is **not** a faster version of the model; it is a different, wrong function that happens to run faster.

## 3. Where each tier is blind

| Tier | `attack_direct` | `attack_obfuscated` | `attack_paraphrase` | `clean` | `clean_framework` |
|---|---|---|---|---|---|
| `clf-torch` | 100.0% | 100.0% | 80.0% | 20.6% | 8.3% |
| `clf-onnx` | 100.0% | 100.0% | 80.0% | 20.6% | 8.3% |

Flag rate per bucket. For `clean*` buckets **lower is better** (false positives); for `attack_*` buckets **higher is better** (recall). `clean_framework` is the `<user_context>` wrapper AI-Parrot's integrations inject — a tier that flags those is unusable in Telegram/Slack.

## 4. Tiering

_Skipped — needs `regex`, an `embed-cosine-*`, and a `clf-*` tier in the same run._

## Caveats

- Single machine, single run — treat **ratios** as robust and absolute numbers as indicative, the same standard applied in `sdd/proposals/pii-detection-redaction.comparison.md` §6.
- The corpus is synthetic and small (tens per bucket). It is built to expose *structural* blind spots (paraphrase, obfuscation, framework wrappers), not to estimate production accuracy.
- Latency is measured per single call. Real seams may batch; a batched classifier amortises far better than these numbers suggest.
- int8 dynamic quantization is calibration-free; static quantization with a calibration corpus would likely be faster still, and is untested here.
