# TASK-3110: Author the AI-Parrot usage & cost Grafana dashboard

**Feature**: FEAT-548 — Observability — OTEL to Prometheus + Grafana usage/cost dashboard
**Spec**: `sdd/specs/observability-otel-grafana.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3108, TASK-3109
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4 — the deliverable the whole feature exists for.
Renders usage total, by agent, by LLM model, by provider, and cost.

The **by-agent** dimension is the one that has never existed in any shipped
dashboard, even though `parrot.agent.name` has been on every LLM metric since
FEAT-228.

---

## Scope

- Create `docker/grafana/provisioning/dashboards/parrot/parrot-usage-cost.json`
  with the panel inventory below.
- Write every PromQL expression using the **verbatim** names from
  TASK-3108's `series-names.md`.
- Add `agent` / `model` / `provider` template variables.

**NOT in scope**: the package example dashboards (TASK-3111); the regression
tests (TASK-3113); docs (TASK-3112); changing any instrument (out of scope for
the whole feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docker/grafana/provisioning/dashboards/parrot/parrot-usage-cost.json` | CREATE | The dashboard |
| `docker/grafana/provisioning/dashboards/parrot/.gitkeep` | DELETE | No longer needed once a real file exists |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```text
NAME SOURCE OF TRUTH: sdd/state/FEAT-548/verification/series-names.md
                      (produced by TASK-3108 — read it FIRST)
Datasource uid:       claudestats-prometheus
                      (verified: docker/grafana/provisioning/datasources/prometheus.yml)
Provisioning path:    /etc/grafana/provisioning/dashboards/parrot
                      (verified: docker/grafana/provisioning/dashboards/dashboards.yml, TASK-3109)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
# OTel instrument names + their label sets. Prometheus renderings come from
# TASK-3108; these are the OTel-side originals.
"gen_ai.client.request.count"   # counter,   line 97   gen_ai.system, gen_ai.provider.name, gen_ai.request.model, parrot.agent.name
"gen_ai.client.error.count"     # counter,   line 101  + error.type
"gen_ai.client.cost.total"      # counter,   line 105  unit="USD", + gen_ai.response.model
"gen_ai.client.operation.duration"  # histogram, line 129  unit="s", + gen_ai.operation.name="chat"
"gen_ai.client.token.usage"     # histogram, line 134  unit="tokens", + gen_ai.token.type in {input,output}
"parrot.client.round.token.usage"   # histogram, line 143  SEPARATE instrument — never summed with the above
"parrot.agent.invoke.duration"  # histogram, line 158  parrot.agent.name, parrot.invoke.method
```

### Does NOT Exist

- ~~`gen_ai_client_token_usage_total`~~ — token usage is a **histogram**. Totals
  come from its `_sum`. The current `parrot-overview.json` queries this
  non-existent counter; do not repeat that mistake.
- ~~`gen_ai_client_cost_usd_total`~~, ~~`gen_ai_client_error_total`~~,
  ~~`gen_ai_client_operation_total`~~ — none exist under any backend.
- ~~bare labels `model` / `provider`~~ — those belong to the `parrot_llm_*`
  `PrometheusUsageRecorder` path, not this one.
- ~~labels `user_id` / `session_id`~~ — span-only by design
  (`attributes.py:126-133`). **No per-user panel is possible.** Do not add one.
- ~~`parrot_llm_*` anything~~ — different backend entirely.

---

## Implementation Notes

### Key Constraints

1. **Token totals come from `_sum`**, never a `_total` counter.
2. **Never add `parrot.client.round.token.usage` to `gen_ai.client.token.usage`** —
   FEAT-397 kept them separate precisely to avoid double-counting every token
   (rounds + total). See the comment at `metrics.py:139-151`.
3. **Group by the translated label names** from `series-names.md`, not bare
   `model`/`provider`.
4. **Reference the datasource by uid** `claudestats-prometheus`.
5. **Stable `uid`** on the dashboard: `parrot-usage-cost`. The existing
   `parrot-usage.json` has none, so it cannot be deep-linked — do not repeat that.
6. **Cost silently under-reports.** `cost_usd()` returns `None` for a model
   absent from the pricing tables and that call adds nothing to the counter. The
   "Requests without cost" panel exists to make that visible rather than letting
   spend quietly vanish.
7. `parrot.round.number` multiplies series count by round depth — prefer per-call
   instruments in the default views.

### References in Codebase

- `docker/grafana/provisioning/dashboards/codex-overview.json` — a working
  provisioned dashboard on this exact stack: copy its structural conventions
  (schema version, templating shape, datasource references).

---

## Implementation Blueprint

### Steps (in order)

1. **Read `sdd/state/FEAT-548/verification/series-names.md` first** — *why*: every
   expression below is a template with `<>` placeholders; filling them from
   memory instead of that file reproduces the exact defect this feature fixes.
2. Copy `codex-overview.json`'s outer structure as the starting skeleton —
   *why*: it is known to provision correctly here, so schema/version quirks are
   already solved.
3. Add the three template variables, then the panels row by row.
4. Reload (30 s) and confirm every panel renders non-empty data.

### `docker/grafana/provisioning/dashboards/parrot/parrot-usage-cost.json` (CREATE)

```jsonc
{
  "uid": "parrot-usage-cost",
  "title": "AI-Parrot — LLM Usage & Cost",
  "tags": ["ai-parrot", "llm", "cost"],
  "timezone": "browser",
  "refresh": "1m",
  "time": { "from": "now-24h", "to": "now" },
  "templating": { "list": [
    { "name": "agent",    "type": "query", "includeAll": true, "multi": true,
      "datasource": { "type": "prometheus", "uid": "claudestats-prometheus" },
      "query": "label_values(<request_count_series>, <agent_label>)" },
    { "name": "model",    "type": "query", "includeAll": true, "multi": true,
      "query": "label_values(<request_count_series>, <request_model_label>)" },
    { "name": "provider", "type": "query", "includeAll": true, "multi": true,
      "query": "label_values(<request_count_series>, <provider_label>)" }
  ]},
  "panels": [
    // ---- Row: Totals ----------------------------------------------------
    { "type": "stat", "title": "Total cost (USD)",
      "targets": [{ "expr": "sum(<cost_total_series>)" }] },
    { "type": "stat", "title": "Total requests",
      "targets": [{ "expr": "sum(<request_count_series>)" }] },
    { "type": "stat", "title": "Total tokens",
      "targets": [{ "expr": "sum(<token_usage_sum_series>)" }] },
    { "type": "stat", "title": "Requests without cost",
      // Unpriced models: requests exist but contribute nothing to cost.
      "targets": [{ "expr": "sum(<request_count_series>) - sum(<request_count_series> and on(<model_label>) <cost_total_series>)" }] },

    // ---- Row: By agent (the dimension no shipped dashboard ever had) -----
    { "type": "timeseries", "title": "Cost rate by agent (USD/h)",
      "targets": [{ "expr": "sum by (<agent_label>) (increase(<cost_total_series>[1h]))" }] },
    { "type": "timeseries", "title": "Tokens/s by agent",
      "targets": [{ "expr": "sum by (<agent_label>, <token_type_label>) (rate(<token_usage_sum_series>[5m]))" }] },
    { "type": "table", "title": "Cumulative cost by agent",
      "targets": [{ "expr": "sum by (<agent_label>) (<cost_total_series>)", "format": "table", "instant": true }] },

    // ---- Row: By model / provider ---------------------------------------
    { "type": "timeseries", "title": "Cost rate by model (USD/h)",
      "targets": [{ "expr": "sum by (<response_model_label>) (increase(<cost_total_series>[1h]))" }] },
    { "type": "timeseries", "title": "Tokens/s by model",
      "targets": [{ "expr": "sum by (<response_model_label>, <token_type_label>) (rate(<token_usage_sum_series>[5m]))" }] },
    { "type": "table", "title": "Cumulative cost by model + provider",
      "targets": [{ "expr": "sum by (<response_model_label>, <provider_label>) (<cost_total_series>)", "format": "table", "instant": true }] },

    // ---- Row: Health -----------------------------------------------------
    { "type": "timeseries", "title": "Request rate by agent",
      "targets": [{ "expr": "sum by (<agent_label>) (rate(<request_count_series>[5m]))" }] },
    { "type": "timeseries", "title": "Error rate by agent",
      "targets": [{ "expr": "sum by (<agent_label>) (rate(<error_count_series>[5m])) / sum by (<agent_label>) (rate(<request_count_series>[5m]))" }] },
    { "type": "timeseries", "title": "p50 / p95 latency (s)",
      "targets": [
        { "expr": "histogram_quantile(0.50, sum by (le) (rate(<op_duration_bucket_series>[5m])))" },
        { "expr": "histogram_quantile(0.95, sum by (le) (rate(<op_duration_bucket_series>[5m])))" }
      ]}
  ]
}
```

**Why this shape**: totals-first, then the by-agent row (the feature's headline),
then model/provider, then health — so the question "what is this costing me and
which agent is spending it" is answered above the fold. Cost uses `increase(...[1h])`
rather than `rate()` so the unit reads as USD/hour rather than USD/second.
`instant: true` on the tables gives a cumulative snapshot, not a series. The
`uid` and `folder` are fixed by AC-9 — do not change them. Every `<...>`
placeholder is filled from `series-names.md`, never guessed.

### FILL IN checklist

- [ ] Every `<..._series>` and `<..._label>` placeholder — from
      `sdd/state/FEAT-548/verification/series-names.md`; bounded by AC-8/AC-10.
- [ ] "Requests without cost" expression — the join above is a starting point;
      adjust to the real label set, bounded by constraint 6 (unpriced models must
      be visible, not hidden).
- [ ] Panel `gridPos` layout (rows of 3-4) — cosmetic, bounded by "must be
      readable at 1080p".
- [ ] Units per panel: `currencyUSD` for cost, `short` for tokens, `s` for
      latency, `percentunit` for error rate.
- [ ] Delete `parrot/.gitkeep` once this file exists.

---

## Acceptance Criteria

- [ ] **AC-9** Dashboard appears in Grafana in the **AI-Parrot** folder,
      provisioned exactly once.
- [ ] **AC-10** Every panel renders non-empty data after a real agent run,
      including ≥1 panel by agent, ≥1 by model, and ≥1 showing cost.
- [ ] Dashboard JSON parses and declares `uid: parrot-usage-cost`.
- [ ] No expression references a metric or label absent from `series-names.md`.
- [ ] No expression sums round-token and per-call-token instruments together.
- [ ] No panel groups by `user_id` or `session_id`.

---

## Test Specification

Automated coverage lives in TASK-3113. Manual check here:

```bash
python3 -c "import json;d=json.load(open('docker/grafana/provisioning/dashboards/parrot/parrot-usage-cost.json'));print(d['uid'],len(d['panels']),'panels')"
# Every expression must resolve against the live TSDB:
python3 - <<'PY'
import json, re, urllib.parse, urllib.request
d = json.load(open("docker/grafana/provisioning/dashboards/parrot/parrot-usage-cost.json"))
for p in d["panels"]:
    for t in p.get("targets", []):
        q = urllib.parse.urlencode({"query": t["expr"]})
        with urllib.request.urlopen(f"http://localhost:9090/api/v1/query?{q}") as r:
            res = json.load(r)
        n = len(res["data"]["result"])
        print(("OK  " if n else "EMPTY"), p["title"], "->", n, "series")
PY
```

---

## Agent Instructions

Standard SDD task flow. **Do not start before TASK-3108's artifact exists** — its
`<exact>` cells are this task's inputs. If any cell still reads `<exact>` or
`absent`, stop: the dashboard cannot be authored against unknown names.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
