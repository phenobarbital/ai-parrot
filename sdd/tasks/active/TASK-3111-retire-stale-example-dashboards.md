# TASK-3111: Retire the two stale package example dashboards

**Feature**: FEAT-548 — Observability — OTEL to Prometheus + Grafana usage/cost dashboard
**Spec**: `sdd/specs/observability-otel-grafana.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3110
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5. `ai-parrot` currently ships two example dashboards
that query metric names **nothing emits**:

- `parrot-overview.json` — `gen_ai_client_token_usage_total`,
  `gen_ai_client_cost_usd_total`, `gen_ai_client_error_total`,
  `gen_ai_client_operation_total`. None of these have ever existed. Token usage
  is a histogram, so a `_total` counter for it cannot exist.
- `parrot-usage.json` — `parrot_llm_*`, which are the `prometheus_client` names
  from the **non-OTel** `PrometheusUsageRecorder` on port 9464. Under
  `OBSERVABILITY_BACKEND=otel` those series never appear.

Neither has a by-agent panel. Anyone importing them gets empty panels and no
indication why.

---

## Scope

- Copy TASK-3110's dashboard to the package examples directory.
- Delete `parrot-overview.json` and `parrot-usage.json`.

**NOT in scope**: authoring dashboard content (TASK-3110); the README that points
at this directory (TASK-3112); the `PrometheusUsageRecorder` itself, which stays
exactly as-is.

> **Open question §8 Q3 gates the second deletion.** The spec's default is to
> delete `parrot-usage.json` outright. If the owner decides to keep a
> recorder-path dashboard, it must be **renamed** to name its backend
> (`parrot-usage-prometheus-recorder.json`) so it can never again be mistaken for
> the OTel dashboard. Confirm before deleting.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-usage-cost.json` | CREATE | Copy of TASK-3110's dashboard |
| `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-overview.json` | DELETE | Queries metrics that do not exist |
| `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-usage.json` | DELETE | Queries the 9464 recorder path (pending Q3) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```text
Source of the replacement:
  docker/grafana/provisioning/dashboards/parrot/parrot-usage-cost.json  (TASK-3110)
Target directory (verified to exist):
  packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/
```

### Existing Signatures to Use

```text
# The expressions being retired — verified verbatim from the current files.
# parrot-overview.json  (uid: parrot-observability-overview, 4 panels)
  sum by (model) (rate(gen_ai_client_token_usage_total[5m]))
  sum by (model) (increase(gen_ai_client_cost_usd_total[1h]))
  histogram_quantile(0.95, sum by (le, model) (rate(gen_ai_client_operation_duration_bucket[5m])))
  sum by (model) (rate(gen_ai_client_error_total[5m])) / sum by (model) (rate(gen_ai_client_operation_total[5m]))

# parrot-usage.json  (NO uid set, 6 panels)
  sum(parrot_llm_cost_usd_total)
  sum(rate(parrot_llm_requests_total[5m]))
  sum by (provider, model) (rate(parrot_llm_cost_usd_total[5m]))
  sum by (provider, model) (rate(parrot_llm_input_tokens_total[5m]))
  histogram_quantile(0.50, sum by (le) (rate(parrot_llm_request_duration_seconds_bucket[5m])))
  sum by (provider, model) (parrot_llm_cost_usd_total)

# packages/ai-parrot/src/parrot/observability/recorders/prometheus_recorder.py:44-80
#   labelnames = ("provider", "model")   <- why the bare labels above exist there
#   parrot_llm_requests_total / _input_tokens_total / _output_tokens_total /
#   _cost_usd_total / parrot_llm_request_duration_seconds / parrot_llm_tokens
```

### Does NOT Exist

- ~~`gen_ai_client_token_usage_total`~~, ~~`gen_ai_client_cost_usd_total`~~,
  ~~`gen_ai_client_error_total`~~, ~~`gen_ai_client_operation_total`~~ — the
  four names `parrot-overview.json` queries. Confirm with the live TSDB before
  anyone argues to keep the file.
- ~~a third example dashboard~~ — the directory holds exactly these two files.

---

## Implementation Notes

### Key Constraints

- The copy must be **byte-identical** to TASK-3110's file, so the two never drift.
  TASK-3113's regression test scans both locations.
- Deleting is the point: leaving a broken dashboard "for reference" is what
  produced this task.

---

## Implementation Blueprint

### Steps (in order)

1. Confirm Q3's answer with the owner — *why*: it decides whether
   `parrot-usage.json` is deleted or renamed, and a wrong guess either destroys a
   wanted artifact or leaves the confusing one in place.
2. Copy the dashboard:
   `cp docker/grafana/provisioning/dashboards/parrot/parrot-usage-cost.json packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/`
   — *why*: byte-identical, so the shipped example and the provisioned one cannot
   diverge.
3. `git rm` the stale file(s) — *why*: `git rm` (not `rm`) keeps the deletion in
   the index and avoids leaving an untracked orphan.
4. Confirm nothing else references the deleted filenames:
   `git grep -n 'parrot-overview\|parrot-usage\.json'` — *why*: the examples
   README and the architecture doc both point into this directory; dangling
   references are TASK-3112's input.

### Commands (this task has no code blocks — it is a copy and two deletions)

```bash
DEST=packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards
cp docker/grafana/provisioning/dashboards/parrot/parrot-usage-cost.json "$DEST"/
git add "$DEST"/parrot-usage-cost.json
git rm "$DEST"/parrot-overview.json
# Only after Q3 is answered "delete":
git rm "$DEST"/parrot-usage.json
# If Q3 is answered "keep":
#   git mv "$DEST"/parrot-usage.json "$DEST"/parrot-usage-prometheus-recorder.json
#   ...and add a "title" making the backend explicit inside the JSON.
git grep -n 'parrot-overview\|parrot-usage\.json' || echo "no dangling references"
```

**Why this shape**: `cp` + `git rm` keeps the operation reviewable as one diff:
one file added, one or two removed. Step 4's grep hands TASK-3112 the exact list
of doc lines that must change.

### FILL IN checklist

- [ ] Q3's answer (delete vs rename) — bounded by §8 Q3; record it in the
      completion note.
- [ ] If renamed: the `title` inside the JSON must name its backend, bounded by
      "can never again be mistaken for the OTel dashboard".
- [ ] The dangling-reference list from step 4 — hand to TASK-3112.

---

## Acceptance Criteria

- [ ] **AC-11** `grafana-dashboards/` contains no query for a metric name the
      emitter does not produce.
- [ ] `parrot-usage-cost.json` in the examples dir is byte-identical to the
      provisioned one (`diff` reports nothing).
- [ ] `parrot-overview.json` is deleted.
- [ ] `parrot-usage.json` is deleted or renamed per Q3 — not left as-is.
- [ ] `git grep 'parrot_llm_'` returns only `prometheus_recorder.py` and its
      tests (i.e. no dashboard still queries those names), unless Q3 chose rename.

---

## Test Specification

Covered by TASK-3113's `test_shipped_dashboards_reference_real_metrics`, whose
fixture globs **both** dashboard directories. That test failing is the signal
this task was done wrong.

---

## Agent Instructions

Standard SDD task flow. **Stop and ask if §8 Q3 is unanswered** — do not choose
between deleting and renaming on your own.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
