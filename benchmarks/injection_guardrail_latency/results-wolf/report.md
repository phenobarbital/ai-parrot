# Prompt-Injection Guardrail Benchmark

Baseline for `PromptInjectionGuardrail` — regex vs embedding-similarity vs the deBERTa classifier under torch / ONNX / ONNX-int8.

## Setup

- Classifier: `patronus-studio/wolf-defender-prompt-injection-small`
- Embedder: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- ORT / torch thread cap: `2` (BLAS/OMP pinned to 1)
- Timed passes: 10 × 96 samples (warm-up 5)
- Per-tier process isolation: `True`
- Python 3.12.3

Corpus: `clean` 34, `clean_framework` 12, `attack_direct` 20, `attack_paraphrase` 20, `attack_obfuscated` 10 — **96 total**, seed catalogue 22 (held disjoint from every eval bucket).

## 1. Cost per tier

| Tier | load (s) | RSS Δ (MB) | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) | inline-safe | status |
|---|---|---|---|---|---|---|---|---|
| `clf-torch` | 11.90 | 1281.1 | 23.31 | 38.36 | 40.57 | 43.27 | **no** | ok |
| `clf-onnx` | 11.44 | 1584.6 | 15.94 | 32.73 | 49.97 | 54.96 | **no** | ok |

*inline-safe* = p95 ≤ 5 ms, the budget for an on-loop guardrail stage. Anything above belongs behind `run_in_executor` with a `BudgetRouter`/`CircuitBreaker` (see the comparison doc §5.2).

## 2. Detection quality

| Tier | thr | precision | recall | F1 | FP | FN | best-F1 thr | best F1 |
|---|---|---|---|---|---|---|---|---|
| `clf-torch` | 0.98 | 1.00 | 0.74 | 0.85 | 0 | 13 | 0.10 | 0.94 |
| `clf-onnx` | 0.98 | 1.00 | 0.74 | 0.85 | 0 | 13 | 0.10 | 0.94 |

`thr` is the threshold the tier would run at in production. For `clf-*` that is AI-Parrot's current `injection_probability_threshold=0.98`; the best-F1 column shows what the same model would score if it were retuned.

## 2b. Numerical parity vs the PyTorch reference

| Backend | max \|Δ\| | mean \|Δ\| | flipped verdicts | parity |
|---|---|---|---|---|
| `clf-onnx` | 0.000 | 0.000 | 0 (0.0%) | ok |

Same weights, same inputs — so scores must agree within numerical noise. A backend that fails here is **not** a faster version of the model; it is a different, wrong function that happens to run faster.

## 3. Where each tier is blind

| Tier | `attack_direct` | `attack_obfuscated` | `attack_paraphrase` | `clean` | `clean_framework` |
|---|---|---|---|---|---|
| `clf-torch` | 95.0% | 70.0% | 55.0% | 0.0% | 0.0% |
| `clf-onnx` | 95.0% | 70.0% | 55.0% | 0.0% | 0.0% |

Flag rate per bucket. For `clean*` buckets **lower is better** (false positives); for `attack_*` buckets **higher is better** (recall). `clean_framework` is the `<user_context>` wrapper AI-Parrot's integrations inject — a tier that flags those is unusable in Telegram/Slack.

## 4. Per-language quality

| Tier | en benign FP | en recall | es benign FP | es recall | mixed benign FP | mixed recall |
|---|---|---|---|---|---|---|
| `clf-torch` | 0/30 (0.0%) | 81.1% (n=37) | 0/16 (0.0%) | 50.0% (n=12) | — | 100.0% (n=1) |
| `clf-onnx` | 0/30 (0.0%) | 81.1% (n=37) | 0/16 (0.0%) | 50.0% (n=12) | — | 100.0% (n=1) |

Benign false-positive count/rate and attack recall, per sample language, at each tier's production threshold. **Lower FP, higher recall is better.** `mixed` is the single deliberately bilingual obfuscation sample. A language column that is far worse than the others is the regression this table exists to catch — it is how the v1→v2 Spanish false-positive regression had to be hand-derived from a flipped-sample table before this gate existed.

## 5. Tiering

_Skipped — needs `regex`, an `embed-cosine-*`, and a `clf-*` tier in the same run._

## Caveats

- Single machine, single run — treat **ratios** as robust and absolute numbers as indicative, the same standard applied in `sdd/proposals/pii-detection-redaction.comparison.md` §6.
- The corpus is synthetic and small (tens per bucket). It is built to expose *structural* blind spots (paraphrase, obfuscation, framework wrappers), not to estimate production accuracy.
- Latency is measured per single call. Real seams may batch; a batched classifier amortises far better than these numbers suggest.
- int8 dynamic quantization is calibration-free; static quantization with a calibration corpus would likely be faster still, and is untested here.
