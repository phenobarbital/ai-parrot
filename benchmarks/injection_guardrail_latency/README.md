# Prompt-Injection Guardrail Benchmark

Baseline + candidate-tier measurement for `PromptInjectionGuardrail`
(`packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py`).

Motivated by `sdd/proposals/nlproxy-guardrails.comparison.md` §4.1/§4.3
and §5.3. It exists to answer four questions with numbers instead of
intuition:

1. What does the classifier AI-Parrot ships today actually cost — per
   call, to load, and in RAM?
2. Does ONNX (and int8) make it cheap enough for an agent hot path?
3. Is the `injection_probability_threshold = 0.98` we run at today
   catching anything the regex tier doesn't already catch?
4. If a cheap embedding tier sits in front of it, **how often would the
   classifier need to run at all?**

Question 4 is the point. A model that is 40× slower but runs on 5% of
turns is cheaper than one that is 5× slower and runs on every turn.

## Tiers measured

| Tier | What it is |
|---|---|
| `regex` | Today's stdlib engine (`parrot.security.prompt_injection.PromptInjectionDetector`), including the `<user_context>` framework-allowlist pre-strip |
| `embed-cosine-torch` | **Proposed** middle tier: one encode, max cosine against a seed attack catalogue |
| `clf-torch` | Today's production path — `protectai/deberta-v3-base-prompt-injection` under PyTorch (what `pytector`'s `"deberta"` alias resolves to) |
| `clf-onnx` | Same weights, ONNX Runtime, fp32 |
| `clf-onnx-int8` | Same weights, ONNX Runtime, dynamic int8 |

## Corpus

96 labelled EN/ES samples in five buckets (`corpus.py`):

| Bucket | n | Label | Purpose |
|---|---|---|---|
| `clean` | 34 | benign | Realistic agent prompts, **including false-positive traps** — legitimate uses of "ignore", "system", "forget", "olvida" |
| `clean_framework` | 12 | benign | Clean prompts wrapped in the `<user_context source="telegram">` metadata our integrations inject |
| `attack_direct` | 20 | injection | Textbook injections the regex tier should catch |
| `attack_paraphrase` | 20 | injection | Same intent, none of the trigger phrases — the bucket the cosine tier exists for |
| `attack_obfuscated` | 10 | injection | Fullwidth, zero-width, spacing, base64, dotless-i |

Plus a 22-prompt `ATTACK_SEED_CORPUS` — the catalogue an embedding tier
would *ship with*.

> **Methodological invariant**: the seed catalogue is held **disjoint**
> from every evaluation bucket, and `corpus.assert_seed_disjoint()`
> enforces it at startup. Scoring a cosine tier against its own seed
> corpus measures `cos(x, x) == 1` and nothing else. Any future YAML
> attack catalogue must preserve this separation when benchmarked.

## Running it

```bash
source .venv/bin/activate

# One-off: export the ONNX graphs (~1 GB on disk, under the gitignored models/)
# The exporter lives in the `dev` extra; the runtime backend it produces
# graphs for lives in `security` alongside pytector.
uv pip install -e 'packages/ai-parrot[dev,security]'
python -m benchmarks.injection_guardrail_latency.export \
    --output-dir models/injection-clf

# Full run — one process per tier so peak RSS is attributable
python -m benchmarks.injection_guardrail_latency.harness \
    --onnx-dir models/injection-clf --isolate \
    --output-dir benchmarks/injection_guardrail_latency/results
```

Quick smoke run with no model downloads:

```bash
python -m benchmarks.injection_guardrail_latency.harness \
    --tiers regex --repeats 3 --output-dir /tmp/bench
```

Useful flags:

| Flag | Default | Meaning |
|---|---|---|
| `--tiers` | all five | Subset to run |
| `--repeats` | 10 | Timed passes over the whole corpus |
| `--intra-op-threads` | 2 | ORT/torch thread cap; **`0` = library default**, i.e. every physical core per session |
| `--clf-threshold` | 0.98 | Classifier decision threshold (matches production) |
| `--isolate` | off | One subprocess per tier — required for meaningful RSS |

## Output

`results/results.json` (machine-readable, includes every per-sample
score) and `results/report.md` (four tables: cost, quality, per-bucket
blind spots, tiering).

## Dependencies

| Need | Extra | Why there |
|---|---|---|
| Run an ONNX guardrail (load a pre-exported graph) | `ai-parrot[security]` | Runtime backend, next to `pytector` — the classifier it accelerates |
| Export / quantize a graph (`export.py`) | `ai-parrot[dev]` | Build-time only; a production install should not carry the optimum/onnx toolchain to load a graph someone else produced |

## Notes on methodology

- **Thread pinning.** `OMP/MKL/OPENBLAS/BLIS_NUM_THREADS` are pinned to 1
  at import time so numbers are comparable across machines. ORT and torch
  are capped separately via `--intra-op-threads`, defaulting to 2 — the
  same cap `voice/tts/supertonic_inference.py:462-472` applies after an
  uncapped ORT pool pegged every core and froze the aiohttp event loop.
  Set `--intra-op-threads 0` to reproduce that failure mode deliberately.
- **RSS.** `parrot.security` is pre-imported before any measurement, so
  each tier's `rss_delta_mb` is the *marginal* cost of enabling it, not
  the framework's import cost. Peak RSS is only meaningful under
  `--isolate`.
- **Per-tier degradation.** A missing ONNX graph or an uninstalled
  backend fails that tier alone (recorded in its `error` field); the run
  continues and the report shows the gap rather than crashing.
- **Composed quality is measured, not projected.** The tiering table
  scores escalated samples with the classifier's real output.

## Caveats

The corpus is synthetic and small. It is built to expose *structural*
blind spots — paraphrase, obfuscation, framework wrappers — not to
estimate production accuracy. Treat ratios as robust and absolute
numbers as indicative, the same standard as
`sdd/proposals/pii-detection-redaction.comparison.md` §6.
