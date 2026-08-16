# SPK-3 — LLM envelope fidelity spike (Claude + Gemini)

**Feature**: FEAT-273 (Module 0b) · **Date**: 2026-07-11 (harness) / 2026-08-16 (re-run with
live credentials) · **Author**: sdd-worker (Claude)

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
- Params: temperature 0.2, max_tokens 4096. Models: `claude-sonnet-4-5` (Anthropic's
  current default/flagship chat model), `gemini-3.1-pro-preview` (Google GenAI's current
  flagship pro model). The originally-attempted `claude-3-5-sonnet-latest` /
  `gemini-1.5-pro` IDs were unavailable in this environment (HTTP 404) on the first pass
  (2026-07-11) and were swapped for the models above — no other harness change.

## Result — measured (2026-08-16 re-run, real credentials + accessible models)

Both providers returned live responses for all 44 calls (22 prompts × 2 clients). Zero
`call_error` rows.

| Client | First-shot parse % | Catalog-valid % | Notes |
|---|---|---|---|
| Claude (`claude-sonnet-4-5`) | 22/22 (100%) | **20/22 (90.9%)** | 2 `unknown_component` failures: invented `Column` (prompt `cmp-03`) and `Section` (prompt `inf-02`) — neither is in the registered catalog (Card, Chart, DataTable, Form, Infographic, KPICard, Map, Report, Timeline). |
| Gemini (`gemini-3.1-pro-preview`) | 22/22 (100%) | **22/22 (100%)** | No failures of any class. |

**Failure taxonomy histogram** (44 total rows): `catalog_valid`=42, `unknown_component`=2,
all other classes (`raw_text_degradation`, `schema_violation`, `requires_actions`,
`call_error`, `other`)=0.

Raw per-run rows: `runs.jsonl` (44 lines, no secrets, no fabricated data).

## Retry-budget recommendation for TASK-1737 (Module 9)

**Recommended (confirmed): `max_attempts = 3` (1 initial + 2 catalog-validate retries).**

This was the evidence-pending recommendation from the 2026-07-11 harness commit, grounded
in the in-repo `OutputFormatter.format_with_retry` precedent (`max_retries=2` default,
`formatter.py:35`/`:147`). The 2026-08-16 live re-run **confirms** it: first-shot
catalog-valid rate is 90.9% (Claude) and 100% (Gemini) — both comfortably above the ~85%
threshold the original rationale set as the "2 retries is sufficient" bar. The only
observed failure class in 44 calls (`unknown_component`, 2/44 = 4.5%) is exactly the kind
of error a bounded re-prompt with the catalog allowlist in the error context recovers from
(the model named a plausible-but-unregistered component instead of one that exists);
provider refusal-to-JSON / raw-text degradation — the NOT-retry-recoverable class — did
not occur at all in this run. No change to the retry budget is warranted from this
evidence; Module 9 (TASK-1737) should implement `max_attempts = 3` as specified.
