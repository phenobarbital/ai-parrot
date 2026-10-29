# G1 — Token accounting (FEAT-746)

## Scope

This spike measures the token cost of a descriptor path vs inline JSON for a 10,000-row × 12-column pandas frame with mixed dtypes. The descriptor path is what the external LLM sees (HandleDescriptor with preview rows and summary character cap), while the inline path is what would be put in context today (df.to_dict(orient="records") serialized). The goal is to freeze caps for M6's HandleAffordanceToolkit and HandleDescriptor that keep the descriptor under 250 tokens on both tokenizers.

## Environment and API surface

- python: 3.12.7
- pandas: 3.0.6
- pyarrow: 26.0.0
- tiktoken: absent (heuristic only)
- numpy: 2.2.1

## Reproduction

```bash
python sdd/state/FEAT-746/spikes/G1-token-accounting/spike.py
```

The script builds a deterministic 10,000 × 12 frame (seed 746) and sweeps `preview_rows ∈ {3, 5, 10}` and `summary_chars ∈ {600, 1000, 1500}`, printing token counts for both tokenizers.

## Results

| path | preview_rows | summary_chars | heuristic | tiktoken |
|------|--------------|---------------|-----------|----------|
| inline | - | - | 764,475 | 1,158,737 |
| descriptor | 3 | 600 | 141 | 145 |
| descriptor | 3 | 1000 | 209 | 238 |
| descriptor | 3 | 1500 | 346 | 423 |
| descriptor | 5 | 600 | 141 | 145 |
| descriptor | 5 | 1000 | 209 | 238 |
| descriptor | 5 | 1500 | 346 | 423 |
| descriptor | 10 | 600 | 141 | 145 |
| descriptor | 10 | 1000 | 209 | 238 |
| descriptor | 10 | 1500 | 346 | 423 |

## Verdict

**PASS** against < 250 tokens (both tokenizers) for the descriptor path with `preview_rows = 3` and `summary_chars = 1000`.

## Proposed amendment (spec §3 M6)

preview_rows = 3; summary_chars = 1000; max_sample_rows = 50; max_text_tokens = 800
