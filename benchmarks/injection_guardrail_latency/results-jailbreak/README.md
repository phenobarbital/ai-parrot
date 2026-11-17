# FEAT-761 jailbreak bake-off — results and verdict

Reproduce:

```bash
PYTHONPATH=packages/ai-parrot/src:. python -m benchmarks.injection_guardrail_latency.compare_jailbreak \
  --onnx-root <root> --out benchmarks/injection_guardrail_latency/results-jailbreak
```

`<root>/<model_id>/<graph_path>` must hold each ONNX graph (madhurjindal is exported first with
`python -m benchmarks.injection_guardrail_latency.export --model madhurjindal/Jailbreak-Detector-Large --output-dir <root>/madhurjindal/Jailbreak-Detector-Large/onnx`).
No weights or graphs are committed.

## Environment

| | |
|---|---|
| Date | 2026-10-27 (run), 2026-10-28 (gate re-evaluation) |
| CPU | Intel Core i7-9850H @ 2.60 GHz, 12 logical cores |
| Threads | pinned to 1 intra-op / 1 inter-op (`pin_thread_env(1)`) |
| Sequence length | `max_length=512` |
| Python | 3.12.3 |
| onnxruntime | 1.31.0 |
| transformers / tokenizers / huggingface_hub | 5.21.0 / 0.23.3 / 2.3.0 |
| model2vec / scikit-learn / skops | 0.10.0 / 1.9.1 / 0.16.0 |

## Decision rule (pre-registered, one amendment)

Winner = highest combined ES+EN F1 subject to (a) 0 Spanish-benign false positives at the selected
threshold and (b) p50 latency within budget at 512 tokens; ties → more permissive license (apache/MIT over
llama4), then smaller artifact. Only `eligible` candidates can win.

> **Amendment (2026-10-28).** The p50 budget was **30 ms** when the rule was registered. After the first
> measurement run (all three real classifiers measured 43.6–44.8 ms) the operator relaxed it to **45 ms**.
> This was decided *after seeing the results*, so the gate is weaker independent evidence than a
> budget fixed in advance. The gate was re-applied to the **same measurements** (no model re-run); the
> spec (§5, §8) and `P50_BUDGET_MS` carry the amendment. Under the original 30 ms rule no eligible
> candidate with a real operating point passed.

## Verdict

Winner: **`madhurjindal/Jailbreak-Detector-Large`** (MIT), fp32 graph `onnx/model.onnx`,
threshold **0.0448**, revision `d6e5232b642c5b94540bf2d892eafb00748a2f63`,
sha256 `c3762562cdd923c4c1dae5d105be179d842f1dfb7f6da03a3654c6c8679d09fa`.
No llama4 attribution is required (the winner is MIT; gravitee, which is llama4, did not win).

| Candidate | License | Gate | p50 / p95 (ms) | F1 combined | F1 EN / ES | ES jailbreak recall | ES-benign FP | Threshold |
|---|---|---|---|---|---|---|---|---|
| **madhurjindal/Jailbreak-Detector-Large** | mit | **pass (winner)** | 44.81 / 52.7 | **0.641** | 0.654 / 0.627 | 0.44 | 0 | 0.0448 |
| vllm-sr/mmbert32k-jailbreak-detector-merged | apache-2.0 | pass | 44.28 / 47.3 | 0.462 | 0.542 / 0.372 | 0.32 | 0 | 0.3658 |
| gravitee-io/Llama-Prompt-Guard-2-86M-onnx (fp32) | llama4 | pass | 43.57 / 51.8 | 0.427 | 0.478 / 0.372 | 0.28 | 0 | 0.9981 |
| enguard/medium-guard-128m-xx-prompt-jailbreak-binary-in-the-wild | mit | pass (degenerate) | 0.21 / 0.3 | 0.000 | 0.000 / 0.000 | 0.00 | 0 | 1.01 |

`0dinai/jailbreak-embeddings-base-onnx` and `protectai/deberta-v3-base-prompt-injection-v2` are not
eligible and could not be measured on this machine (missing `optimum` backend / no exported graph);
they are listed under `skipped` in `manifest.json` with the reason.

## Caveats the reader must weigh

1. **Thin latency margin.** The winner's p50 is 44.81 ms against a 45.0 ms limit (0.19 ms margin); p95 is
   52.7 ms. Treat the pin as "about 45 ms on this CPU", not a guarantee.
2. **Threshold fitted to a small bucket.** 0.0448 sits just above the highest Spanish-benign score of a
   25-item set. It holds on this corpus; production Spanish traffic may false-positive more. ES jailbreak
   recall is only 0.44.
3. **enguard "passes" with F1 0.** It selected threshold 1.01 and flags nothing, so it has zero false
   positives and trivial latency. The gate has no minimum-F1 guard; enguard cannot win only because its F1
   is lower. Its sklearn head was pickled with 1.7.2 and loaded with 1.9.1 (`InconsistentVersionWarning`), so
   its scores may also be unreliable. A minimum-F1/recall guard is recommended follow-up work.
4. **Budget relaxed post hoc** (see the amendment above).

## Extra run: int8 graph of the winner (not in the pre-registered matrix)

`model_int8.onnx` (323 MB, `backend="onnx-int8"`), same corpus and settings:

| p50 / p95 (ms) | RSS (MB) | Selected threshold | F1 | ES-benign FP |
|---|---|---|---|---|
| 29.6 / 34.2 | 1572 | 1.01 | 0.000 | 0 |

The quantized model is unusable: it returns almost the same score (≈0.08–0.13) for every input in every
bucket, so it cannot separate jailbreaks from benign text. fp32 spans ≈0.001–0.99. Its "pass" is the same
degenerate no-detection pass as enguard. The raw int8 output was not committed (it is outside this task's
file list); the figures above are copied from that run.
