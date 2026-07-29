# SPK-3 — LLM envelope fidelity spike (Claude + Gemini)

**Feature**: FEAT-273 (Module 0b) · **Date**: 2026-07-11 · **Author**: sdd-worker (Claude)

## Setup

- Prompt set: `prompts.json` — **22 prompts** across 6 display-UI categories (dashboard,
  comparison, kpi, table, map, report/infographic). Reproducible/committed.
- Path: EXISTING structured output —
  `client.ask(..., structured_output=StructuredOutputConfig(output_type=CreateSurface))`.
  No client code changed.
- Classification: parse-as-`CreateSurface` → catalog validation with
  **producer-origin = LLM** (so `requires_actions` and unknown components count as
  failures, matching v1 production rules). Taxonomy: `catalog_valid`,
  `raw_text_degradation`, `schema_violation`, `unknown_component`, `requires_actions`,
  `call_error`, `other`.
- Params: temperature 0.2, max_tokens 4096. Attempted models: `claude-3-5-sonnet-latest`,
  `gemini-1.5-pro`.

## Result — validity NOT measured in this environment (⚠ credential/model gap)

Both providers returned **HTTP 404 model-not-found** for every call in this environment
(Claude: `not_found_error` for the model; Gemini: `models/gemini-1.5-pro is not found for
API version v1beta`). `runs.jsonl` therefore contains **22 `call_error` rows per client**
and **zero genuine fidelity samples**. These are environment/model-availability failures,
NOT model fidelity — per the task's explicit instruction, **no validity numbers are
fabricated**.

| Client | First-shot parse % | Catalog-valid % | Notes |
|---|---|---|---|
| Claude | not measured | not measured | 404 model-not-found (model access unavailable) |
| Gemini | not measured | not measured | 404 model-not-found (`gemini-1.5-pro` unavailable) |

To obtain real numbers, run `spike_fidelity.py` in an environment with valid Anthropic +
Google GenAI credentials and model IDs available to the project (adjust `CLAUDE_MODEL` /
`GEMINI_MODEL` to accessible models). The harness + taxonomy are correct and ready.

## Retry-budget recommendation for TASK-1737 (Module 9)

**Recommended: `max_attempts = 3` (1 initial + 2 catalog-validate retries).**

Rationale (evidence-pending, grounded in the in-repo precedent): the existing
`OutputFormatter.format_with_retry` machinery ships `max_retries=2` as its default
(`formatter.py:35`, `:147`) for exactly this shape of problem (LLM output that must
conform to a structured contract), with `DEFAULT_RETRY_PROMPTS` re-prompting on the
error context. Catalog failures that ARE retry-recoverable (schema violations, unknown/
misnamed components, malformed bindings, an accidental `requires_actions` component) are
precisely the classes a bounded re-prompt with the validation error fixes; provider
refusal-to-JSON / raw-text degradation is NOT retry-recoverable and should short-circuit
to the plain-text degradation path rather than burn the budget. Two retries balances
recovery against latency/cost. **Revisit this number once live SPK-3 numbers exist**: if
first-shot catalog-valid rate is ≥ ~85% on both models, 2 retries is comfortably
sufficient; if a model shows a large *recoverable* schema-error tail, consider 3.
