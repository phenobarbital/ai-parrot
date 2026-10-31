# Bundled Pricing Tables

FEAT-177 — OpenTelemetry + Cost Observability.

Each JSON file covers one provider's model pricing. The `CostCalculator` loads
these files once at first construction (module-level cache) and uses them to
compute USD cost estimates per LLM API call.

## File Format

```json
{
  "pricing": {
    "last_updated": "YYYY-MM-DD",
    "source": "URL",
    "currency": "USD"
  },
  "models": {
    "<model-id>": {
      "input_per_1m":  <float>,    // USD per 1M input tokens (required)
      "output_per_1m": <float>,    // USD per 1M output tokens (required)
      "cached_input_per_1m": <float>,  // USD per 1M cached input (cache-read) tokens (optional)
      "cache_creation_per_1m": <float>, // USD per 1M cache-creation (cache-write) tokens (optional; defaults to input_per_1m)
      "valid_from": "YYYY-MM-DD"   // pricing effective date (optional)
    }
  }
}
```

## Provider → File Mapping

| `gen_ai.system` value | File | Notes |
|---|---|---|
| `openai` | `openai.json` | |
| `anthropic` | `anthropic.json` | includes `claude-agent` client |
| `gemini` | `google.json` | covers Gemini API; Vertex pricing may differ |
| `aws.bedrock` | `aws.bedrock.json` | Bedrock-hosted third-party models (`zai.*`, `minimax.*`, `mistral.*`, `qwen.*`); US East on-demand Standard |
| `groq` | `groq.json` | |
| `nvidia` | `nvidia.json` | best-effort; verify at NVIDIA Build |
| `xai` | — | not bundled in Phase 1 |
| `huggingface` | — | not bundled in Phase 1 |

## Override

Set `PARROT_PRICING_PATH` to a directory or use `ObservabilityConfig.pricing_override_path`
to deep-merge custom pricing over bundled values. Override wins per-model.

## Staleness Warning

`CostCalculator` logs a WARN at boot if any file's `pricing.last_updated` is
older than 90 days. Update the file and bump `last_updated` when pricing changes.

## Cache-creation tier (FEAT-783)

`cache_creation_per_1m` is the price of writing a prompt-cache entry. Anthropic publishes it as a
multiplier of the base input price (5-minute write = 1.25x), so every `anthropic.json` entry carries
`input_per_1m * 1.25`. OpenAI publishes a 30-minute write price only for the GPT-5.6/6.x rows, so only `gpt-5.6-sol`, `gpt-5.6-terra` and
`gpt-5.6-luna` carry it; older rows show `-` on the page.
Gemini bills context caching as storage per hour, so no cache-creation tier is published and none is set.

## dev-loop backend ids (FEAT-783)

sdd-coder attempts are keyed by dev-loop backend id. `PROVIDER_TO_GEN_AI_SYSTEM` maps `codex` -> `openai`
and `google-compat` -> `gemini` (and `nova` -> `aws.bedrock`), so those rows price against the files above.

## Sources and caveats (fetched 2026-11-01)

| File | Source | Notes |
|---|---|---|
| `anthropic.json` | https://platform.claude.com/docs/en/about-claude/pricing | All entries from Claude 4.5 up re-verified against the page. `claude-haiku-5-5` carries the **<= 100k-token prompt** rates; prompts over 100k cost 5x (not modelled, so those calls are under-priced). |
| `openai.json` | https://developers.openai.com/api/docs/pricing?latest-pricing-expanded=true | Added `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` (Standard tier, short context). The expanded view is embedded as script data (`TextTokenPricingTables`); columns are input, cached input, 30m write, output. All 20 existing text-model rows match the Standard table exactly, plus `gpt-5.3-codex` and `chat-latest`. `gpt-realtime-2`, `gpt-realtime-1.5`, `gpt-audio-1.5` and `gpt-image-2` are no longer listed at those rates and were left unchanged. `gpt-5.6-sol` pricing is flagged promotional on the page ("at least through 2026-11-21"). `gpt-5.3-codex-spark` is not published and stays unpriced. |
| `google.json` | https://ai.google.dev/gemini-api/docs/pricing | Only `gemini-3.8-flash` was added, as a dated list (price doubles on 2027-01-01). Older rows were not re-verified; `last_updated` was **not** bumped. `gemini-3.5-flash` (existing row) is no longer on the page. |
| `aws.bedrock.json` | https://aws.amazon.com/es/bedrock/pricing/ | US East (N. Virginia) on-demand Standard. The Qwen3 Coder 480B rate is not in the static HTML; it was read from the page's own pricing endpoint (`b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps`, per-1K x 1000). |
| `groq.json`, `nvidia.json`, `huggingface.json` | - | Not re-verified (no source supplied); dates unchanged. |

## Coverage evidence

Measured with `python -m scripts.sdd.price_coverage --rows-dir artifacts/logs/sdd-coder-usage` on 2026-11-01.

| Measure | Rows | Priced | Ratio |
|---|---|---|---|
| All attempt rows | 1133 | 694 | 61.3% |
| Real-model rows (placeholders excluded) | 703 | 694 | **98.7%** |

The 430 excluded rows are test fixtures written into `FEAT-549.jsonl` (the engine's own feature: synthetic
`TASK-0001` ids, seat `a`) before the hermetic-root fixture existed: `model-a` 166, `model-b` 135, `model-c` 75,
`qwen` 31, `mcp-strong` 16, `mistral` 7. They can never be priced. Reproduce with:

```bash
python -m scripts.sdd.price_coverage --rows-dir artifacts/logs/sdd-coder-usage --threshold 0.9 \
  --exclude-model model-a --exclude-model model-b --exclude-model model-c \
  --exclude-model qwen --exclude-model mcp-strong --exclude-model mistral
```

The only unpriced real model is `gpt-5.3-codex-spark` (9 rows, no published price). Row counts are the 2026-11-01
snapshot and grow with use.
