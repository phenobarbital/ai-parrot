# G1 — Token accounting (FEAT-746)

## Scope

This spike measures the token cost of a descriptor path vs inline JSON for a 10,000-row × 12-column pandas frame with mixed dtypes. The descriptor path is what the external LLM sees (HandleDescriptor with preview rows and summary character cap), while the inline path is what would be put in context today (df.to_dict(orient="records") serialized). The goal is to freeze caps for M6's HandleAffordanceToolkit and HandleDescriptor that keep the descriptor under 250 tokens on both tokenizers.

## Environment and API surface

- python: 3.12.7
- pandas: 3.0.6
- pyarrow: 26.0.0
- tiktoken: 0.14.0 (cl100k_base)
- numpy: 2.2.1

## Reproduction

```bash
python sdd/state/FEAT-746/spikes/G1-token-accounting/spike.py
PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g1_token_accounting.py -q
```

The script builds a deterministic 10,000 × 12 frame (seed 746) and sweeps
`preview_rows ∈ {1, 3, 5}`, `summary_chars ∈ {600, 1000}` and float rounding
(none / 3 decimals). Preview rows are dropped until the summary JSON fits
`summary_chars`; `kept` is the number of preview rows that actually survived.
`summary_chars` stops at 1000 because `HandleDescriptor` rejects larger
summaries (`MAX_SUMMARY_CHARS = 1000`).

## Results (re-measured 2026-10-30)

| path | summary_chars | preview kept | rounding | heuristic (len/4) | tiktoken cl100k |
|------|---------------|--------------|----------|-------------------|-----------------|
| inline | – | all 10,000 rows | – | 764,475 | 1,158,737 |
| descriptor | 600 | 0 | any | 141 | 145 |
| descriptor | 1000 | 1 | none | 209 | 238 |
| descriptor | 1000 | 1 | 3 decimals | 202 | 226 |

`preview_rows` 1, 3 and 5 give identical rows: for a 12-column frame the column
schema uses most of the 1000-character budget, so at most **one** preview row fits.
The earlier table's `summary_chars = 1500` rows (346 / 423 tokens) came from a
build before the descriptor cap existed and are no longer producible.

## Verdict

**PASS** against < 250 tokens on both tokenizers at the descriptor cap
(`MAX_SUMMARY_CHARS = 1000`): worst case 238 tiktoken tokens. The margin is
thin (12 tokens), so the cap must not be raised without re-measuring.

## Proposed amendment (spec §3 M6)

- The bound is the **summary character budget**, not a row count:
  `summary_chars = 1000` (already enforced as `MAX_SUMMARY_CHARS`).
- Preview rows are best-effort: include rows while the summary fits, rounding
  floats to 3 decimals; a wide frame may carry zero or one preview row, and
  callers must not promise a fixed number.
- `max_sample_rows` / `max_text_tokens` for the affordance tools were **not
  measured** by this spike and are left to M6.
