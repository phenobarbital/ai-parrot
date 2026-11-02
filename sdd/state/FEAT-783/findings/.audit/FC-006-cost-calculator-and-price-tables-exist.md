---
id: FC-006
query_id: Q018
type: read
intent: "Confirm whether a normalised Usage/TokenUsage model already exists anywhere in parrot."
executed_at: 2026-10-30T22:45:00Z
duration_ms: 1100
parent_id: null
depth: 1
---

# FC-006 — REFUTED: a versioned price table and a shared CostCalculator already ship in parrot — but they price only 13 of 1090 real sdd-coder attempts

## Summary

The source claims "a price table (model × token type → USD) owned by ai-parrot" does not
exist and proposes a new `usage/prices.yaml`. **It already exists** and is older and better
specified than the proposal: `parrot/observability/cost/` (FEAT-177) bundles six JSON
price files — `anthropic.json` (19 models), `openai.json` (24), `google.json` (15),
`groq.json` (12), `nvidia.json` (5), `huggingface.json` (0, deliberately null-priced) —
**75 priced models** in the exact shape the source proposes: `input_per_1m`,
`output_per_1m`, `cached_input_per_1m`, `valid_from`, plus a per-file
`pricing.last_updated` / `source` / `currency` metadata block. `CostCalculator.cost_usd()`
applies them with an explicit cached-tier split, returns `None` (never a guess) for an
unpriced `(provider, model)`, warns once per unknown pair, and emits a boot WARN for any
provider file older than `stale_warn_days=90`. Overrides come from
`ObservabilityConfig.pricing_override_path` / `PARROT_PRICING_PATH`, deep-merged per model.

The real gap is coverage, and it is severe: **13 of 1090 recorded attempt rows (1.2%) use a
model that appears in any price table.** `gpt-5.6-terra` (422 rows), `model-a` (166),
`gpt-5.6-sol` (103), `zai.glm-4.7-flash` (51), `qwen` (31), `minimax.minimax-m2.5` (24),
`mistral.devstral-2-123b` (15) are all unpriced. The bundled files were last updated
**2026-06-10 — 142 days before today**, well past their own 90-day staleness threshold.
A second gap: entries have **no cache-*write*/creation tier**, only `cached_input_per_1m`
(a read discount), so Anthropic-style cache-creation billing cannot be expressed.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 792-814
  symbol: `AbstractClient._compute_call_cost`
  excerpt: |
    def _compute_call_cost(self, client_name, model, input_tokens, output_tokens) -> "Optional[float]":
        """FEAT-710: one cost computation per call, with the shared calculator. Never raises."""
        calc = get_shared_cost_calculator()
        if calc is None:
            return None
        try:
            from parrot.observability.attributes import resolve_gen_ai_system
            return calc.cost_usd(provider=resolve_gen_ai_system(client_name), model=model or "", ...)

- path: `packages/ai-parrot/src/parrot/observability/cost/calculator.py`
  lines: 1-12
  symbol: `module docstring`
  excerpt: |
    """CostCalculator — stateless USD cost estimation for LLM API calls.

    FEAT-177 TASK-1232.

    Pricing tables are loaded from bundled JSON files once at first
    ``CostCalculator()`` construction and cached at module level. No filesystem
    I/O occurs in the hot path (``cost_usd``).

    Override path: ``ObservabilityConfig.pricing_override_path`` or
    ``PARROT_PRICING_PATH`` env var (resolved by ``setup_telemetry``).

- path: `packages/ai-parrot/src/parrot/observability/cost/calculator.py`
  lines: 190-212
  symbol: `CostCalculator.cost_usd`
  excerpt: |
    def cost_usd(self, *, provider: str, model: str, input_tokens: int,
                 output_tokens: int, cached_input_tokens: int = 0) -> Optional[float]:
        """Compute USD cost for a single LLM API call.
        Returns:
            USD cost as a float rounded to 6 decimal places, or ``None`` if
            the ``(provider, model)`` pair is not found in any pricing table.
        """

- path: `packages/ai-parrot/src/parrot/observability/cost/calculator.py`
  lines: 227-238
  symbol: `CostCalculator.cost_usd`
  excerpt: |
    input_per_1m: float = price["input_per_1m"]
    output_per_1m: float = price["output_per_1m"]
    cached_per_1m: float = price.get("cached_input_per_1m", input_per_1m)
    non_cached = max(0, input_tokens - cached_input_tokens)
    input_cost = non_cached * input_per_1m / 1_000_000
    output_cost = output_tokens * output_per_1m / 1_000_000
    cached_cost = cached_input_tokens * cached_per_1m / 1_000_000
    total = input_cost + output_cost + cached_cost
    return round(total, 6)

- path: `packages/ai-parrot/src/parrot/observability/cost/pricing/anthropic.json`
  lines: 1-15
  symbol: `price entry shape`
  excerpt: |
    {
      "pricing": {
        "last_updated": "2026-06-10",
        "source": "https://www.anthropic.com/pricing",
        "currency": "USD"
      },
      "models": {
        "claude-3-5-sonnet-20241022": {
          "input_per_1m": 3.00, "output_per_1m": 15.00,
          "cached_input_per_1m": 0.30, "valid_from": "2024-10-22" }

- path: `packages/ai-parrot/src/parrot/observability/cost/calculator.py`
  lines: 150-156
  symbol: `CostCalculator.__init__`
  excerpt: |
    def __init__(self, *, override_path: Optional[str] = None,
                 stale_warn_days: int = 90, today: Optional[date] = None) -> None:

- path: `packages/ai-parrot/src/parrot/observability/cost/pricing/`
  lines: n/a
  symbol: `price-table coverage vs. observed models`
  excerpt: |
    75 priced models across 6 provider files (anthropic 19, openai 24, google 15,
    groq 12, nvidia 5, huggingface 0).
    Models actually run by sdd-coder and their pricing status:
      gpt-5.6-terra  422 rows  NO     model-a  166 rows  NO
      gpt-5.6-sol    103 rows  NO     zai.glm-4.7-flash 51 rows NO
      qwen            31 rows  NO     minimax.minimax-m2.5 24 rows NO
      gemini-3.5-flash 13 rows YES  <- the ONLY priced model in the dataset
    coverage: 13/1090 attempt rows (1.2%)

## Notes

- `get_shared_cost_calculator()` returning `None` makes `cost_usd` `None`, so cost is already
  optional-by-design throughout the client layer. The source's three-way policy
  (`billed`/`subscription`/`estimate`) has no counterpart here — the calculator has exactly
  one notion of price (list price) and no concept of a subscription seat.
- `last_call_cost.set(cost_usd)` (base.py:789) publishes the per-call cost on a ContextVar —
  an existing, zero-cost read point for anything that wants the last call's USD.
- The "90-day stale" warning fires at construction; with `last_updated: 2026-06-10` every
  provider file is currently stale, so any run that constructs a calculator is already
  emitting that WARN.
- Building a second price table at `usage/prices.yaml`, as the source proposes, would create
  two sources of truth for the same number. The cheaper path is to extend these files
  (add the local/self-hosted models, add a cache-creation tier) and version them by content
  hash there.
