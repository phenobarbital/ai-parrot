---
type: Concept
title: calculate_piotroski_score()
id: func:parrot_tools.quant.piotroski.calculate_piotroski_score
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Calculate Piotroski F-Score (0-9) for fundamental quality.
---

# calculate_piotroski_score

```python
def calculate_piotroski_score(input_data: PiotroskiInput) -> dict
```

Calculate Piotroski F-Score (0-9) for fundamental quality.

The F-Score measures financial strength using 9 binary criteria
across three categories:
- Profitability (4 points)
- Leverage/Liquidity/Source of Funds (3 points)
- Operating Efficiency (2 points)

Args:
    input_data: PiotroskiInput with quarterly and prior year financials.

Returns:
    Dictionary with:
    - total_score: int (0-9)
    - criteria: dict with details for each criterion
    - data_completeness_pct: float (0-100)
    - interpretation: str (Excellent/Good/Fair/Poor)
    - category_scores: dict with profitability, leverage_liquidity, operating_efficiency
