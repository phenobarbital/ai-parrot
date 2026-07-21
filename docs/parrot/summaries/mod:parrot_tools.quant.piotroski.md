---
type: Wiki Summary
title: parrot_tools.quant.piotroski
id: mod:parrot_tools.quant.piotroski
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Piotroski F-Score Calculator for QuantToolkit.
relates_to:
- concept: func:parrot_tools.quant.piotroski.batch_piotroski_scores
  rel: defines
- concept: func:parrot_tools.quant.piotroski.calculate_piotroski_score
  rel: defines
- concept: func:parrot_tools.quant.piotroski.get_fscore_summary
  rel: defines
- concept: func:parrot_tools.quant.piotroski.rank_by_fscore
  rel: defines
- concept: mod:parrot_tools.quant.models
  rel: references
---

# `parrot_tools.quant.piotroski`

Piotroski F-Score Calculator for QuantToolkit.

The Piotroski F-Score is a fundamental quality scoring system that evaluates
company financial health using 9 binary accounting criteria:

Profitability (4 points):
1. Positive Net Income
2. Positive ROA (Return on Assets)
3. Positive Operating Cash Flow
4. Cash Flow > Net Income (quality of earnings)

Leverage/Liquidity/Source of Funds (3 points):
5. Lower Long-Term Debt (YoY)
6. Higher Current Ratio (YoY)
7. No New Shares Issued

Operating Efficiency (2 points):
8. Higher Gross Margin (YoY)
9. Higher Asset Turnover (YoY)

Score Interpretation:
- 8-9: Excellent (strong buy signal)
- 6-7: Good (positive outlook)
- 4-5: Fair (neutral)
- 0-3: Poor (avoid or sell)

## Functions

- `def calculate_piotroski_score(input_data: PiotroskiInput) -> dict` — Calculate Piotroski F-Score (0-9) for fundamental quality.
- `def batch_piotroski_scores(symbols_data: dict[str, PiotroskiInput]) -> dict[str, dict]` — Calculate F-Scores for multiple symbols.
- `def get_fscore_summary(result: dict) -> str` — Generate a human-readable summary of the F-Score result.
- `def rank_by_fscore(symbols_data: dict[str, PiotroskiInput]) -> list[tuple[str, int, str]]` — Rank symbols by F-Score descending.
