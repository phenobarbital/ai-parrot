---
name: financial_projection_variance
description: Multi-dataset financial variance dashboard — 4 KPI cards + 2 DoD bar charts + 1 cumulative line chart.
triggers:
  - /financial_variance
source: authored
category: infographic
priority: 90
---

# Financial Projection Variance Infographic

This skill produces a **single-turn interactive HTML infographic** that visualises
daily revenue, EBITDA, and cumulative revenue for a given period.

## Step 1 — Compute the three DataFrames

Using `python_repl_pandas`, compute and store:

```python
# rev_daily: columns [day, revenue]
rev_daily = <your revenue-by-day DataFrame>

# ebitda_daily: columns [day, ebitda]
ebitda_daily = <your EBITDA-by-day DataFrame>

# rev_cumulative: columns [day, cumulative_revenue]
rev_cumulative = rev_daily.copy()
rev_cumulative["cumulative_revenue"] = rev_cumulative["revenue"].cumsum()
rev_cumulative = rev_cumulative[["day", "cumulative_revenue"]]
```

All three must be non-empty before proceeding.

## Step 2 — Build the four hero cards

Each card must have at least these fields: `label`, `value`, `trend` (optional).

Summarise:
1. **Total Revenue** for the period.
2. **Total EBITDA** for the period.
3. **EBITDA Margin** = Total EBITDA / Total Revenue (formatted as %).
4. **Largest Daily Revenue Swing** = max(|rev_daily - prev_day_rev|).

## Step 3 — Build the two DoD bar charts

- Chart 1: day-over-day revenue bar chart using `rev_daily`.
- Chart 2: day-over-day EBITDA bar chart using `ebitda_daily`.

## Step 4 — Build the cumulative line chart

- Chart 3: cumulative revenue line chart using `rev_cumulative`.

## Step 5 — Close the turn with infographic_render

Once all blocks are ready, call `infographic_render` as the **last and only
remaining tool call** for this turn.  Do NOT add any text after calling it —
its return value is the final answer.

```python
infographic_render(
    template_name="financial_projection_variance",
    theme="dark",
    mode="enhance",            # optional; use "deterministic" if enhance not needed
    blocks=[
        hero_card_block,       # position 0: 4 KPI hero cards
        chart_revenue_dod,     # position 1: DoD revenue bar
        chart_ebitda_dod,      # position 2: DoD EBITDA bar
        chart_rev_cumulative,  # position 3: cumulative line
    ],
    data_variables=["rev_daily", "ebitda_daily", "rev_cumulative"],
    enhance_brief="Add tooltips and hover interactivity using ECharts. "
                  "Make revenue and EBITDA bars interactive with click-to-filter.",
)
```

Use `infographic_list_templates` to confirm template names, and
`infographic_get_template_contract` / `infographic_validate_blocks` to verify the
positional block contract before rendering.

## Notes

- The template is `financial_projection_variance` (registered by FEAT-197).
- The `js_bundles` for this template declare ECharts from a CDN — the enhance
  pipeline will validate any added `<script>` tags against the SRI whitelist.
- If the enhance LLM call fails validation, the toolkit automatically falls back
  to the deterministic skeleton; the caller always gets a valid HTML artifact.
