# ONNX Backend for the Prompt-Injection Guardrail (FEAT-439)

`PromptInjectionGuardrail` (`bots/guardrails/builtin/prompt_injection.py`)
resolves a scoring engine once, at construction, and reuses it for every
turn on every bot in the process. This page covers the env vars, the
resolution order, warm-up for long-lived hosts, air-gapped provisioning,
and the v1→v2 model change this feature shipped.

## Why this exists

Measured on 96 labelled samples (10 timed passes, thread caps applied,
`benchmarks/injection_guardrail_latency/results-v2/report.md`):

| Backend | p50 | p95 | p99 |
|---|---|---|---|
| `clf-torch` (pytector, today's default absent this feature) | 120.71 ms | 147.28 ms | 155.37 ms |
| `clf-onnx` (this feature, when a graph resolves) | **35.16 ms** | 63.71 ms | 68.35 ms |

Same weights, same inputs, **zero flipped verdicts** (max\|Δ\|=0.000) —
the ONNX path is a backend swap, not a different classifier. Re-verified
at the shipping tokenizer length (512), with proper per-tier process
isolation, in
`benchmarks/injection_guardrail_latency/results-v2-512/report.md`: p50
124.35 ms (torch) vs 34.79 ms (ONNX), still 0 flipped verdicts.

This does **not** fix the guardrail running synchronously on the event
loop — `check()` still blocks the loop for the engine's full latency.
Moving it off-loop (`run_in_executor` + `BudgetRouter`/`CircuitBreaker`)
is a separate, follow-up feature.

## Engine resolution

At `PromptInjectionGuardrail.__init__`, a process-wide singleton resolves
the best locally-available engine, in order:

1. **`PARROT_INJECTION_ONNX_DIR`** — if set to a directory containing
   `model.onnx` + tokenizer/config files, this wins over everything. The
   air-gapped / CI answer (see below).
2. **A cached HF snapshot** of `protectai/deberta-v3-base-prompt-injection-v2`
   containing `onnx/model.onnx`. Resolution here is strictly offline
   (`huggingface_hub.try_to_load_from_cache`) — an uncached graph is
   treated as absent, **never** triggering a download.
3. **pytector**, if importable:
   - pointed at a local v2 snapshot directory when one is cached, else
   - the `"deberta"` alias (**v1** — `protectai/deberta-v3-base-prompt-injection`),
     with a WARNING that the fallback model is v1, not the intended v2.
4. **The regex engine** (`PromptInjectionDetector`) — always available,
   today's non-ML floor.

Every step logs: an invalid `PARROT_INJECTION_ONNX_DIR` logs an ERROR
naming the path and the missing piece; an uncached graph logs a WARNING
naming `warmup_injection_model()` as the fix; the v1 fallback logs a
WARNING naming the model mismatch; the engine that actually gets selected
is logged once, at construction, naming both the engine and the model.
**Construction never downloads and never raises** — every failure falls
through to the next step, worst case being today's exact behaviour (the
v1 alias) plus the new warning.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PARROT_INJECTION_ONNX_DIR` | unset | Absolute path to a directory holding `model.onnx` + tokenizer/config files. Wins over everything — the air-gapped answer. |
| `PARROT_INJECTION_ORT_INTRA_OP_THREADS` | `2` | ORT intra-op thread cap for the guardrail's session. |
| `PARROT_INJECTION_ORT_INTER_OP_THREADS` | `1` | ORT inter-op thread cap. |

Uncapped, ONNX Runtime sizes its intra-op pool to every physical core
**per session** — the same failure mode documented for
`voice/tts/supertonic_inference.py` (it pegged every core and froze the
event loop). Caps are always applied before session construction,
regardless of the env vars being set.

## Warm-up for long-lived hosts

The request path never downloads. For a host that wants to avoid paying
the ~700 MB download + cold-start cost on the first real turn, call the
warm-up entry point explicitly at startup:

```python
from parrot.bots.guardrails.builtin.prompt_injection import (
    warmup_injection_model,
)

await warmup_injection_model()
```

It resolves, downloads the graph if not already cached (skipped entirely
when `PARROT_INJECTION_ONNX_DIR` already points at a valid local graph),
constructs the ORT session, and runs one dummy inference — all off the
event loop (`asyncio.to_thread`). It is the **only** code path in this
feature permitted to download the model. Safe to call more than once:
a second call without `force_download=True` is a fast no-op. A failed
download logs the error and falls back to whatever engine still resolves
offline (pytector or regex) — the host still starts even fully air-gapped.

There is no generic "warm up everything" hook to attach this to (unlike
`AbstractBot.warmup_embeddings`, which is embedding-specific and wired
into exactly one call site) — call it explicitly from your own startup
code.

## Air-gapped / offline provisioning

For hosts with no HF Hub access, populate `PARROT_INJECTION_ONNX_DIR`
with a directory containing the graph + tokenizer/config files, produced
once (on a machine with network access) via the same exporter the
benchmark harness uses:

```bash
source .venv/bin/activate
python -m benchmarks.injection_guardrail_latency.export \
  --model protectai/deberta-v3-base-prompt-injection-v2 \
  --output-dir models/injection-clf-v2 --skip-int8
```

Copy the resulting `models/injection-clf-v2/` directory to the air-gapped
host and point `PARROT_INJECTION_ONNX_DIR` at it. This is the highest
step in the resolution precedence, so it always wins.

## The v1 → v2 model change

This feature moves the primary path from `protectai/deberta-v3-base-prompt-injection`
(v1 — what pytector's `"deberta"` alias resolves to) to
`protectai/deberta-v3-base-prompt-injection-v2`. This is a **measured
behaviour change**, not a drop-in swap — see
[`results-v2/delta-v1-to-v2.md`](../../benchmarks/injection_guardrail_latency/results-v2/delta-v1-to-v2.md)
for the full breakdown. Headline numbers (96-sample corpus, threshold
0.98):

- 21 of 96 verdicts flip (21.9%) — 14 better, 7 worse.
- Recall improves: 0.70 → 0.92 (direct-attack recall 15/20 → 20/20;
  paraphrase 10/20 → 16/20).
- **Spanish benign false positives get markedly worse: 18.8% → 43.8%**
  (n=16 — effect is large, sample is small). Plain business Spanish is
  being scored near 1.0 by v2 in a non-trivial fraction of cases.
- `clean_framework` (the `<user_context>` wrapper AI-Parrot's
  integrations inject) also regresses slightly: 12/12 → 11/12.

**If you operate a Spanish-language deployment**, be aware of this before
relying on v2's default `block_on_threat=False` TRANSFORM behaviour —
legitimate Spanish business input may get wrapped as
`<potentially_unsafe_input>` more often than under v1. The mandatory
follow-up feature for this regression is tracked at
[`sdd/proposals/injection-v2-spanish-fp-mitigation.proposal.md`](../../sdd/proposals/injection-v2-spanish-fp-mitigation.proposal.md).
Until it lands, mitigations available today: keep `block_on_threat=False`
(the default — TRANSFORM, not BLOCK) and/or point
`PARROT_INJECTION_ONNX_DIR`/pytector at a locally-pinned v1 snapshot if
your deployment cannot tolerate the regression.

## Known limitations

- **This does not fix event-loop blocking.** `check()` still calls
  `engine.score()` synchronously; the executor/`BudgetRouter` route is a
  separate follow-up feature.
- **ONNX uses more memory, not less**: measured RSS is *higher* than
  torch (1823 MB vs 1641 MB per process) — the N-workers × ~1.8 GB
  multiplication is unchanged by this feature.
- **Truncation divergence on long inputs**: the ONNX engine truncates at
  512 tokens; pytector's fallback path does not truncate at all. Inputs
  longer than 512 tokens may score differently across engines. This is a
  documented limitation, not a bug to be silently patched around.
- **`injection_probability_threshold` stays at `0.98`** — retuning it is
  explicitly out of scope for this feature (also tracked by the Spanish-FP
  follow-up above).
