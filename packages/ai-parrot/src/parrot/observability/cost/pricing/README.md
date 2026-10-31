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
`input_per_1m * 1.25`. OpenAI publishes a 30-minute write price; only `gpt-5.6-sol` carries it so far.
Gemini bills context caching as storage per hour, so no cache-creation tier is published and none is set.

## dev-loop backend ids (FEAT-783)

sdd-coder attempts are keyed by dev-loop backend id. `PROVIDER_TO_GEN_AI_SYSTEM` maps `codex` -> `openai`
and `google-compat` -> `gemini` (and `nova` -> `aws.bedrock`), so those rows price against the files above.

## Sources and caveats (fetched 2026-11-01)

| File | Source | Notes |
|---|---|---|
| `anthropic.json` | https://platform.claude.com/docs/en/about-claude/pricing | All entries from Claude 4.5 up re-verified against the page. `claude-haiku-5-5` carries the **<= 100k-token prompt** rates; prompts over 100k cost 5x (not modelled, so those calls are under-priced). |
| `openai.json` | https://developers.openai.com/api/docs/pricing | Only `gpt-5.6-sol` was added; it is listed under *Cyber models* at promotional pricing "at least through 2026-11-21". The page no longer lists the older `gpt-5.x` rows, so they were **not** re-verified and the file's `last_updated` was **not** bumped. `gpt-5.6-terra` and `gpt-5.3-codex-spark` have no published price and stay out. |
| `google.json` | https://ai.google.dev/gemini-api/docs/pricing | Only `gemini-3.8-flash` was added, as a dated list (price doubles on 2027-01-01). Older rows were not re-verified; `last_updated` was **not** bumped. `gemini-3.5-flash` (existing row) is no longer on the page. |
| `aws.bedrock.json` | https://aws.amazon.com/es/bedrock/pricing/ | US East (N. Virginia) on-demand Standard. The Qwen3 Coder 480B rate is not in the static HTML; it was read from the page's own pricing endpoint (`b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps`, per-1K x 1000). |
| `groq.json`, `nvidia.json`, `huggingface.json` | - | Not re-verified (no source supplied); dates unchanged. |

## Coverage evidence

Measured with `python -m scripts.sdd.price_coverage --rows-dir artifacts/logs/sdd-coder-usage` on 2026-11-01.
See the task Completion Note for the current ratio and the unpriced pairs.
