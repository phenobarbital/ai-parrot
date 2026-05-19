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
      "cached_input_per_1m": <float>,  // USD per 1M cached input tokens (optional)
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
