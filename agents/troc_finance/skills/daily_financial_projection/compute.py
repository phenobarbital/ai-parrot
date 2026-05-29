# compute.py — Financial Projection report builder (run verbatim in python_repl_pandas)
# Source dataset: `financial_projection` (table troc.financial_projection), daily snapshots.
# Granularity: one row per (division, project, projection_date). `inserted_at` is the
# morning the snapshot landed, i.e. display_date = projection_date + 1 day. The dashboard
# in the reference screenshot labels days by inserted_at, so we do the same.
#
# Produces (and leaves in the REPL namespace) these UNIQUE named DataFrames:
#   fp_daily               -> date, rev_total, ebitda_total, rev_dod, ebitda_dod
#   fp_chart_rev_dod       -> date, rev_dod            (bar chart #1, drops day 0)
#   fp_chart_ebitda_dod    -> date, ebitda_dod         (bar chart #2, drops day 0)
#   fp_chart_cumulative    -> date, rev_total          (line chart, all days)
#   fp_kpis                -> single-row KPI table (the 4 cards, raw + formatted)
# It also prints BLOCKS_JSON=<...> : a ready-to-paste `blocks` payload for
# infographic_render(template_name="financial_variance", ...).

import json
import pandas as pd

# 1) Resolve the source DataFrame from the REPL namespace ----------------------
_REQUIRED = {"master_revenue", "ebitda", "projection_date"}
src = None
for _name in ("financial_projection", "fp", "df1", "df"):
    _cand = locals().get(_name)
    if isinstance(_cand, pd.DataFrame) and _REQUIRED <= set(_cand.columns):
        src = _cand
        break
if src is None:  # last resort: any frame in scope with the required columns
    for _v in list(locals().values()):
        if isinstance(_v, pd.DataFrame) and _REQUIRED <= set(_v.columns):
            src = _v
            break
assert src is not None, (
    "financial_projection not loaded. Run fetch_dataset('financial_projection', "
    "sql='SELECT division, project, master_revenue, ebitda, projection_date, "
    "inserted_at FROM troc.financial_projection') first."
)

df = src.copy()
df["projection_date"] = pd.to_datetime(df["projection_date"])
# Display date convention: snapshot is reported the next morning.
df["date"] = (df["projection_date"] + pd.Timedelta(days=1)).dt.normalize()

# 2) Daily totals across all projects/divisions -------------------------------
fp_daily = (
    df.groupby("date", as_index=False)
      .agg(rev_total=("master_revenue", "sum"),
           ebitda_total=("ebitda", "sum"))
      .sort_values("date")
      .reset_index(drop=True)
)
fp_daily["rev_dod"] = fp_daily["rev_total"].diff()
fp_daily["ebitda_dod"] = fp_daily["ebitda_total"].diff()

# 3) Chart-ready frames (unique names) ----------------------------------------
fp_chart_rev_dod = fp_daily.iloc[1:][["date", "rev_dod"]].reset_index(drop=True)
fp_chart_ebitda_dod = fp_daily.iloc[1:][["date", "ebitda_dod"]].reset_index(drop=True)
fp_chart_cumulative = fp_daily[["date", "rev_total"]].copy()

# 4) KPI scalars (the 4 cards) ------------------------------------------------
cur, prev, start = fp_daily.iloc[-1], fp_daily.iloc[-2], fp_daily.iloc[0]
rev_cur, ebitda_cur = float(cur.rev_total), float(cur.ebitda_total)
rev_start, ebitda_start = float(start.rev_total), float(start.ebitda_total)
rev_dod_last, ebitda_dod_last = float(cur.rev_dod), float(cur.ebitda_dod)
period_var = rev_cur - rev_start
period_pct = (period_var / rev_start * 100.0) if rev_start else 0.0


def _money(v: float) -> str:
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e6:
        return f"{sign}${a/1e6:,.2f}M"
    if a >= 1e3:
        return f"{sign}${a/1e3:,.1f}K"
    return f"{sign}${a:,.0f}"


def _lbl(ts) -> str:
    return pd.Timestamp(ts).strftime("%b %-d")


cur_lbl, start_lbl = _lbl(cur.date), _lbl(start.date)
fp_kpis = pd.DataFrame([{
    "as_of": cur.date, "rev_current": rev_cur, "ebitda_current": ebitda_cur,
    "period_variance": period_var, "period_pct": period_pct,
    "rev_dod": rev_dod_last, "ebitda_dod": ebitda_dod_last,
    "rev_current_fmt": _money(rev_cur), "ebitda_current_fmt": _money(ebitda_cur),
    "period_variance_fmt": _money(period_var), "period_pct_fmt": f"{period_pct:+.1f}%",
    "rev_dod_fmt": _money(rev_dod_last), "ebitda_dod_fmt": _money(ebitda_dod_last),
}])

# 5) Register the computed frames in the catalog (optional but requested) ------
for _n, _desc in (
    ("fp_daily", "Daily revenue/EBITDA totals with day-over-day deltas"),
    ("fp_chart_rev_dod", "Daily revenue DoD change (bar)"),
    ("fp_chart_ebitda_dod", "Daily EBITDA DoD change (bar)"),
    ("fp_chart_cumulative", "Daily total revenue (line)"),
    ("fp_kpis", "Financial-variance KPI cards"),
):
    try:
        store_dataframe(_n, _desc)  # provided by DatasetManager in this REPL  # noqa: F821
    except Exception:
        pass  # store_dataframe may be unavailable; locals registration is enough

# 6) Build candidate blocks for the `financial_variance` template --------------
same_month = start.date.month == cur.date.month and start.date.year == cur.date.year
date_range = (f"{start_lbl} – {pd.Timestamp(cur.date).strftime('%-d')}, {cur.date.year}"
              if same_month else f"{start_lbl} – {cur_lbl}, {cur.date.year}")
rev_trend = "up" if period_var >= 0 else "down"
ebd_trend = "up" if ebitda_dod_last >= 0 else "down"
bar_lbls = [_lbl(d) for d in fp_chart_rev_dod["date"]]
line_lbls = [_lbl(d) for d in fp_chart_cumulative["date"]]

blocks = [
    # slot 0 — title
    {"type": "title", "title": "Financial Projection Variance",
     "subtitle": "Daily revenue & EBITDA tracking", "date": date_range},
    # slots 1-4 — four flat hero_card blocks (one per KPI), matching the flat
    # financial_variance template contract (FEAT-206 / TASK-1385).
    {"type": "hero_card", "label": f"Revenue ({cur_lbl})", "value": _money(rev_cur),
     "icon": "money", "comparison_period": "Total across all projects"},
    {"type": "hero_card", "label": f"Revenue change ({start_lbl}→{cur_lbl})",
     "value": _money(period_var), "icon": "chart",
     "trend": rev_trend, "trend_value": f"{period_pct:+.1f}% period variance"},
    {"type": "hero_card", "label": f"EBITDA ({cur_lbl})", "value": _money(ebitda_cur),
     "icon": "money",
     "trend": "up" if ebitda_cur >= ebitda_start else "down",
     "comparison_period": f"vs {_money(ebitda_start)} on {start_lbl}"},
    {"type": "hero_card", "label": f"Today's DoD ({cur_lbl})",
     "value": f"{_money(rev_dod_last)} rev",
     "icon": "time", "trend": ebd_trend,
     "trend_value": f"{_money(ebitda_dod_last)} EBITDA DoD"},
    # slots 5-6 — two half-width bar charts
    {"type": "chart", "chart_type": "bar", "layout": "half",
     "title": "Daily total revenue — day-over-day change ($)",
     "labels": bar_lbls, "y_axis_label": "$ change",
     "series": [{"name": "Revenue DoD", "values": [round(v, 2) for v in fp_chart_rev_dod["rev_dod"]]}]},
    {"type": "chart", "chart_type": "bar", "layout": "half",
     "title": "Daily EBITDA — day-over-day change ($)",
     "labels": bar_lbls, "y_axis_label": "$ change",
     "series": [{"name": "EBITDA DoD", "values": [round(v, 2) for v in fp_chart_ebitda_dod["ebitda_dod"]]}]},
    # slot 7 — full-width cumulative line chart
    {"type": "chart", "chart_type": "line", "layout": "full",
     "title": "Cumulative total revenue by day ($)",
     "labels": line_lbls, "y_axis_label": "Total revenue ($)",
     "series": [{"name": "Total revenue", "values": [round(v, 2) for v in fp_chart_cumulative["rev_total"]]}]},
    # slot 8 — executive summary
    {"type": "summary",
     "content": (f"Total revenue reached {_money(rev_cur)} on {cur_lbl}, "
                 f"{_money(period_var)} ({period_pct:+.1f}%) above the {start_lbl} baseline. "
                 f"Day-over-day, revenue moved {_money(rev_dod_last)} and EBITDA {_money(ebitda_dod_last)}, "
                 f"with EBITDA closing the period at {_money(ebitda_cur)}.")},
]

fp_blocks = blocks  # also kept in the namespace
print("BLOCKS_JSON=" + json.dumps(blocks))
print("DATA_VARIABLES=" + json.dumps(
    ["fp_chart_rev_dod", "fp_chart_ebitda_dod", "fp_chart_cumulative", "fp_daily"]))
print(fp_kpis.to_string(index=False))
