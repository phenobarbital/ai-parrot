---
id: F005
query_id: Q015
type: read
intent: "Quantify the existing per-attempt telemetry dataset: real coverage per backend, and which counters are actually populated."
executed_at: 2026-10-30T22:42:30Z
duration_ms: 900
parent_id: FC-004
depth: 1
lane: codebase
merged_from: ['FC-005']
---

# F005 — The dataset is live (1090 attempts, 55 features) but the codex seat reports ~zero tokens and no cache/cost counter exists

## Summary

`artifacts/logs/sdd-coder-usage/` holds **55 per-feature JSONL files, 2216 rows
(1090 `attempt` + 1126 `outcome`) across 55 features**, plus 191 per-execution
directories. Totals: **148,736,915 provider input tokens** and 826,533 output tokens
already recorded. Coverage is deeply uneven and the unevenness is the real finding:

| backend | attempt rows | rows with provider tokens | rows with ledger tokens | rows with execution_id | Σ input tokens |
|---|---:|---:|---:|---:|---:|
| `codex` | 660 | 91 | **0** | 531 | **910** |
| `nova` | 326 | 232 | 101 | 179 | 134,715,670 |
| `google-compat` | 104 | 61 | 13 | 48 | 14,020,335 |

The codex seat is **60% of all attempts and 0.0006% of all recorded tokens** — its 910
total input tokens come from `model-b`/`model-c` test fixtures, not real runs. This is
empirical confirmation, from this repo's own data, of the source's Spike S3 premise: the
codex backend produces no usable token counts today. Separately, a key scan over all
1090 rows finds **no field whose name contains `cache`, `cost` or `usd`** — the four-counter
model (cache_read / cache_creation) and any pricing are genuinely absent, as the source claims.

## Citations

- path: `artifacts/logs/sdd-coder-usage/`
  lines: n/a
  symbol: `dataset inventory`
  excerpt: |
    55 *.jsonl files; 2216 rows total (1090 attempt / 1126 outcome); 55 distinct feature_id
    191 subdirectories under executions/ (plus executions/background)
    largest file: FEAT-549.jsonl (524,892 bytes); oldest row 2026-09-21

- path: `artifacts/logs/sdd-coder-usage/FEAT-720.jsonl`
  lines: n/a
  symbol: `largest attempt row`
  excerpt: |
    feature_id=FEAT-720 task_id=TASK-4591 backend=nova
    configured_model=zai.glm-4.7-flash resolved_model=zai.glm-4.7-flash
    provider_input_tokens=5927150 provider_output_tokens=8848
    ledger_input_tokens=5927150 turns=98
    execution_id=8a47d1e2-5c3b-4f60-b9d4-720a1c0de721

- path: `artifacts/logs/sdd-coder-usage/*.jsonl`
  lines: n/a
  symbol: `full key set of attempt rows`
  excerpt: |
    attempt, attempt_uid, backend, calibration_eligible, configured_model,
    declared_files, declared_files_known, duration_s, enforcement, error_class,
    execution_id, feature_id, job_id, kind, ledger_accounting_complete,
    ledger_counting_methods, ledger_input_tokens, ledger_output_tokens,
    ledger_overrun_tokens, ledger_released_estimate_tokens,
    ledger_settled_estimate_input_tokens, ledger_uncertain_tokens,
    provider_input_tokens, provider_output_tokens, resolved_model, seat_label,
    task_id, terminal, ts, turn_series, turns, turns_with_unknown_usage
    -- no key contains "cache", "cost" or "usd"

## Notes

- Models actually seen: `gpt-5.6-terra` (422) and `gpt-5.6-sol` (103) on codex;
  `model-a` (166), `zai.glm-4.7-flash` (51), `qwen` (31), `minimax.minimax-m2.5` (24) on nova;
  `gemini-3.5-flash` (13) on google-compat. A price table would need entries per
  `resolved_model`, and `resolved_model` is empty on many older rows (it falls back to
  `configured_model` — telemetry.py:226).
- `execution_id` is empty on 332/1090 attempt rows: the field was added by FEAT-559 and is
  documented as "Empty for historical records" (telemetry.py:75). Any join on
  `execution_id` must tolerate the gap.
- Rows are **per attempt**, not per request. The source's `usage.recorded` design is
  per-request with a `(seat, source_ref)` dedup key — a strictly finer grain than anything
  recorded today, and the one that drives the log-volume concern in FC-002.
- The 148.7M input tokens are dominated by cache-heavy long-context runs (one attempt alone
  is 5.9M input / 8.8K output). Without a cache_read counter those numbers cannot be priced:
  billing input and cache-read input differ by roughly an order of magnitude in list price.
