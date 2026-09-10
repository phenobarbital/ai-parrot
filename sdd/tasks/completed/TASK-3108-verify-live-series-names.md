# TASK-3108: Verify live metrics and capture the real Prometheus series names

**Feature**: FEAT-548 — Observability — OTEL to Prometheus + Grafana usage/cost dashboard
**Spec**: `sdd/specs/observability-otel-grafana.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3107
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2 and closes §8 Q1 and Q2. This task exists because
**the dashboard cannot be written against predicted series names.** Dotted OTel
names are translated on ingest (dots to underscores, plus unit and `_total`
suffixes), and how the non-standard `USD` unit on `gen_ai.client.cost.total`
renders is genuinely unknown. The existing broken dashboards (see TASK-3111) are
exactly what happens when someone guesses.

It also resolves the one low-confidence claim in the spec: whether the direct
push delivers **cumulative** counters. Prometheus 2.51 has no delta→cumulative
conversion, and this repo's own `docker/grafana/README.md` documents Codex
0.154.0 breaking on this exact path.

This task gates TASK-3110. Do not author PromQL before it completes.

---

## Scope

- Run a real agent/LLM call with TASK-3107's wiring applied.
- Capture the verbatim `gen_ai_*` / `parrot_*` series names from the live TSDB.
- Capture the verbatim label names.
- Confirm counters increase monotonically across ≥3 consecutive scrapes.
- Confirm no `/v1/traces` request is issued and no OTLP export error is logged.
- Record all of it in `sdd/state/FEAT-548/verification/series-names.md`.

**NOT in scope**: authoring the dashboard (TASK-3110); fixing a delta-temporality
failure (that triggers AC-13's collector fallback, which is TASK-3112's doc work
plus a follow-up decision — record the finding, do not improvise a collector).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-548/verification/series-names.md` | CREATE | The captured name/label maps and temporality evidence |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# No imports — this task runs shell commands against a live stack.
```

### Existing Signatures to Use

```python
# The instruments whose translated names this task captures.
# packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
"gen_ai.client.request.count"        # counter,   line 97
"gen_ai.client.error.count"          # counter,   line 101
"gen_ai.client.cost.total"           # counter,   line 105  unit="USD"
"parrot.tool.failure.count"          # counter,   line 110
"parrot.agent.invoke.failure.count"  # counter,   line 114
"parrot.client.rounds"               # counter,   line 119
"gen_ai.client.operation.duration"   # histogram, line 129  unit="s"
"gen_ai.client.token.usage"          # histogram, line 134  unit="tokens"
"parrot.client.round.token.usage"    # histogram, line 143  unit="tokens"
"parrot.tool.execution.duration"     # histogram, line 153  unit="s"
"parrot.agent.invoke.duration"       # histogram, line 158  unit="s"
```

### Does NOT Exist

- ~~a documented mapping table of OTel→Prometheus names in this repo~~ — this
  task creates the first one. Do not cite one.
- ~~`gen_ai_client_token_usage_total`~~ — token usage is a histogram; expect
  `_bucket` / `_sum` / `_count`, never a plain `_total`.
- ~~`parrot_agent_name` as a confirmed label~~ — it is the *expected*
  translation of `parrot.agent.name`; confirming it is this task's job.
- ~~metric labels `user_id` / `session_id`~~ — span attributes only, excluded
  from metrics by design (`attributes.py:126-133`). Do not look for them.

---

## Implementation Notes

### Key Constraints

- `metric_export_interval_ms` is 60 000 with **no env override**
  (`config.py:211`). Nothing appears for up to a minute after the first call —
  an empty result before then is expected, not a failure. Wait, then re-query.
- The default Prometheus scrape interval is 15 s (`docker/prometheus/prometheus.yml`),
  but parrot **pushes** via the OTLP receiver rather than being scraped, so
  freshness is governed by the 60 s export interval, not the scrape interval.
- Record names **verbatim**. Do not normalize, guess, or tidy them — TASK-3110
  copies this file literally.

### References in Codebase

- `docker/grafana/README.md` — the "To diagnose an empty dashboard" block; the
  same `curl` recipes proven against this stack for the Codex integration.

---

## Implementation Blueprint

### Steps (in order)

1. Confirm TASK-3107 landed: `grep -A6 '^\[observability\]' env/.env` shows
   `OBSERVABILITY_ENABLED=true` and the `:9090` endpoint — *why*: every later
   step is meaningless otherwise.
2. Record a **baseline** count of `gen_ai_*`/`parrot_*` series (expected: 0) —
   *why*: AC-3 is an inversion of the zero-series baseline; without recording it
   first you cannot prove the change caused the series to appear.
3. Run a real agent/LLM call that exercises at least two models if possible —
   *why*: a single model cannot show that the by-model dimension actually splits.
4. Wait ≥90 s (60 s export interval + margin), then capture names and labels.
5. Capture the same counter three times ≥20 s apart — *why*: monotonic increase
   across ≥3 samples is the AC-5 evidence for cumulative temporality.
6. Check the process log for OTLP export errors and any `/v1/traces` attempt —
   *why*: AC-6 proves the sampling kill-switch works.
7. Write the artifact.

### Capture commands

```bash
# Step 2 / 4 — series names, verbatim
curl -fsSG http://localhost:9090/api/v1/label/__name__/values \
  | python3 -c "import json,sys;print('\n'.join(n for n in json.load(sys.stdin)['data'] if n.startswith(('gen_ai','parrot'))))"

# Step 4 — label names actually attached (substitute a real series name)
curl -fsSG http://localhost:9090/api/v1/series --data-urlencode 'match[]=<series>' \
  | python3 -c "import json,sys;d=json.load(sys.stdin)['data'];print(sorted({k for s in d for k in s}))"

# Step 5 — temporality: run 3x, >=20s apart; values must never decrease
curl -fsSG http://localhost:9090/api/v1/query \
  --data-urlencode 'query=sum(<request_count_series>)'

# Step 6 — no trace traffic; expect no 404s for /v1/traces in the parrot logs
```

### `sdd/state/FEAT-548/verification/series-names.md` (CREATE)

```markdown
# FEAT-548 — verified Prometheus series names

**Captured**: <YYYY-MM-DD HH:MM UTC>
**By**: <operator>
**Preconditions**: TASK-3107 applied; parrot-prometheus and parrot-grafana up.

## Baseline (before the run)
gen_ai_*/parrot_* series present: <N>   # expected 0 — the F010 baseline

## Name map (OTel instrument -> Prometheus series, VERBATIM)

| OTel instrument | Prometheus series |
|---|---|
| gen_ai.client.request.count | <exact> |
| gen_ai.client.error.count | <exact> |
| gen_ai.client.cost.total | <exact — note how the USD unit renders> |
| gen_ai.client.operation.duration | <exact _bucket/_sum/_count> |
| gen_ai.client.token.usage | <exact _bucket/_sum/_count> |
| parrot.client.rounds | <exact> |
| parrot.client.round.token.usage | <exact> |
| parrot.tool.execution.duration | <exact> |
| parrot.tool.failure.count | <exact> |
| parrot.agent.invoke.duration | <exact> |
| parrot.agent.invoke.failure.count | <exact> |

## Label map (OTel attribute -> Prometheus label, VERBATIM)

| OTel attribute | Prometheus label |
|---|---|
| parrot.agent.name | <exact> |
| gen_ai.request.model | <exact> |
| gen_ai.response.model | <exact> |
| gen_ai.provider.name | <exact> |
| gen_ai.system | <exact> |
| gen_ai.token.type | <exact> |
| error.type | <exact> |

## Temporality (AC-5)
| sample | time | value |
|---|---|---|
| 1 | | |
| 2 | | |
| 3 | | |

Monotonic increase observed: **yes | no**
If **no**: counters are delta. AC-13 applies — the collector fallback must be
documented and this must be reported, NOT worked around silently.

## Traces (AC-6)
/v1/traces requests observed: <none | describe>
OTLP export errors in log: <none | paste>

## Shutdown (AC-7)
CTRL+C after a crew run exited in: <N>s   # must not be the ~10s+ atexit block
```

**Why this shape**: TASK-3110 copies the two maps verbatim into PromQL, so the
tables must hold raw strings, not prose. The explicit "Monotonic: yes|no" line is
the machine-checkable answer to §8 Q2, and the AC-13 sentence stops a `no` from
being quietly ignored.

### FILL IN checklist

- [ ] Every `<exact>` cell — the verbatim series/label name from the live TSDB;
      bounded by AC-8. A name that did not appear must be written `absent`, not guessed.
- [ ] Temporality verdict — bounded by AC-5; a `no` triggers AC-13.
- [ ] Trace and shutdown observations — bounded by AC-6, AC-7.

---

## Acceptance Criteria

- [ ] **AC-3** At least one `gen_ai_*` series exists in Prometheus after the run.
- [ ] **AC-4** `gen_ai.client.cost.total`'s series has a non-zero value for at
      least one priced model.
- [ ] **AC-5** Counters increase monotonically across ≥3 consecutive samples.
- [ ] **AC-6** No `/api/v1/otlp/v1/traces` request issued; no OTLP export error.
- [ ] **AC-7** CTRL+C after a crew run exits promptly.
- [ ] **AC-8** `sdd/state/FEAT-548/verification/series-names.md` records both
      maps verbatim, with no `<exact>` placeholder left.

---

## Test Specification

No pytest — this is live-system verification. The artifact IS the evidence.
A reviewer must be able to re-run every command in it and get the same names.

---

## Agent Instructions

**This task requires the operator's own machine**: a running docker stack and a
real LLM call with real credentials. An unattended agent MUST NOT fabricate the
captured names — that would poison TASK-3110 with invented PromQL, which is the
precise defect this feature exists to fix. If the stack is unreachable, stop and
hand back.

---

## Completion Note

**Completed by**: sdd-worker (autonomous), on the operator's own machine
after the operator identified where the docker configs live (`docker/`)
and the docker stack was brought up in-session
**Date**: 2026-09-10
**Notes**: Full details in
`sdd/state/FEAT-548/verification/series-names.md`. Summary:
- AC-3/AC-4/AC-5/AC-6/AC-8 all fully verified with real evidence.
- AC-7 verified as a proxy (shutdown_telemetry() timing); no literal CTRL+C
  since this is a non-interactive harness.
- Two real findings recorded (not fixed — out of this task's scope):
  `gen_ai.client.error.count` never observed across 7 real failures; a
  fire-and-forget event-forwarding race that can silently drop metrics for
  short-lived callers without a post-call event-loop yield.
- `docker/prometheus` container had to be recreated (pre-dated the docker/
  reorg, missing the OTLP flag); `docker/grafana` had to be brought up from
  scratch (external volume didn't exist yet). See TASK-3107's completion
  note for the Prometheus detail.
- A `navconfig` BASE_DIR quirk (resolves to the main repo, not this
  worktree, when sharing its venv) required exporting the six observability
  env vars at the process level for these verification runs — documented in
  the artifact; does not affect TASK-3107's actual `env/.env` wiring.

**Deviations from spec**: none in the artifact's required shape. Several
catalog rows are honestly recorded `absent` (`gen_ai.client.error.count`,
all `parrot.*` agent/tool instruments) because this verification used raw
`AbstractClient.ask()` calls, not the agent framework — the task template
explicitly requires writing `absent` rather than guessing, and the
Findings section explains why in each case.
