# TASK-3112: Sync the observability docs to the Prometheus wiring

**Feature**: FEAT-548 — Observability — OTEL to Prometheus + Grafana usage/cost dashboard
**Spec**: `sdd/specs/observability-otel-grafana.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3107, TASK-3110
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6. Three documents currently give advice that
contradicts the new wiring — most damagingly
`docs/architecture/10-observability.md`, which tells readers to point
`OTEL_EXPORTER_OTLP_ENDPOINT` at `:4318` and to use
`OBSERVABILITY_BACKEND=prometheus` with the dashboards TASK-3111 just deleted.

> **Correction to the spec's §3 M6 skeleton**: it lists "NEW rows:
> `OBSERVABILITY_SAMPLING`" for the config table. That row **already exists**
> (verified `docs/architecture/10-observability.md:93`). It needs its *description*
> updated to explain the trace kill-switch role, not to be added.

---

## Scope

- `docs/architecture/10-observability.md`: repoint the quickstart, fix the
  Prometheus/Grafana paragraph, annotate the endpoint as a BASE url, expand the
  `OBSERVABILITY_SAMPLING` row, note that `enable_traces`/`enable_metrics` are
  code-only, and point at `env/.env.observability.example`.
- `packages/ai-parrot/src/parrot/observability/examples/README.md`: reframe so
  metrics go to Prometheus and OpenLIT is a trace destination only.
- `docker/grafana/README.md`: add an "AI-Parrot side" section mirroring the
  existing "Codex side" shape.

**NOT in scope**: `docs/dev_loop/telemetry-accounting.md` (unrelated flow-level
accounting); the spec or proposal.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/architecture/10-observability.md` | MODIFY | Quickstart, Prometheus paragraph, config table |
| `packages/ai-parrot/src/parrot/observability/examples/README.md` | MODIFY | Reframe the example stack |
| `docker/grafana/README.md` | MODIFY | New "AI-Parrot side" section |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```text
No code. Verified anchors and their occurrence counts:
  docs/architecture/10-observability.md
    'OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318'  -> 1 occurrence, line 66
    'OBSERVABILITY_BACKEND=prometheus'                   -> 1 occurrence, line 78
    'parrot-openlit-check'                               -> 1 occurrence, line 60
    OBSERVABILITY_SAMPLING table row                     -> line 93 (ALREADY EXISTS)
    OTEL_EXPORTER_OTLP_ENDPOINT table row                -> line 94
```

### Existing Signatures to Use

```python
# The facts the docs must state correctly.
# packages/ai-parrot/src/parrot/observability/config.py
    enable_traces: bool = True    # line 132  <- code-only, from_env never reads it
    enable_metrics: bool = True   # line 133  <- code-only
    sampling_ratio: float = 1.0   # line 206  <- OBSERVABILITY_SAMPLING
    metric_export_interval_ms: int = 60_000   # line 211 <- code-only, no env var
# packages/ai-parrot/src/parrot/observability/exporters.py
    endpoint = f"{config.otlp_endpoint.rstrip('/')}/v1/metrics"   # line 152
```

### Does NOT Exist

- ~~an env var for `enable_traces`~~ — the doc must say so explicitly; this is
  the single most surprising fact in the feature.
- ~~an env var for `metric_export_interval_ms`~~ — the 60 s delay is not tunable
  from `.env`.
- ~~the two deleted dashboards~~ — after TASK-3111, `parrot-overview.json` and
  `parrot-usage.json` no longer exist. Any surviving reference is a dangling link.

---

## Implementation Notes

### Key Constraints

- Do not delete the OpenLIT quickstart wholesale — OpenLIT remains a supported
  **trace** destination and the `ai-parrot-openlit-bridge` package still ships.
  Reframe, do not remove.
- Mirror the "Codex side" section's structure in `docker/grafana/README.md`:
  topology diagram, the exact config block, the caveat that bites, a deep link,
  and `curl` diagnostics. That section is the house style for this stack.

---

## Implementation Blueprint

### Steps (in order)

1. Take TASK-3111's dangling-reference list as the starting checklist — *why*: it
   is the authoritative set of doc lines pointing at now-deleted files.
2. Edit `10-observability.md` §10.2 quickstart and §10.3 table.
3. Edit the examples README.
4. Append the "AI-Parrot side" section to `docker/grafana/README.md`.
5. `git grep -n 'localhost:4318'` and confirm every survivor is deliberately
   about traces/OpenLIT — *why*: AC-15 is phrased as an absence, so it can only
   be checked by grep.

### `docs/architecture/10-observability.md` (MODIFY — quickstart)

```markdown
# occurrences: 1 (verified: grep -c 'OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318' docs/architecture/10-observability.md)
# REPLACE the line `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` (verified: docs/architecture/10-observability.md:66)
# Metrics -> the local Prometheus OTLP write receiver. BASE URL ONLY: the
# exporter appends /v1/metrics itself (exporters.py:152).
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9090/api/v1/otlp
# Prometheus 2.x serves no /v1/traces, and enable_traces is a code-only field
# (config.py:132) — so silence traces here rather than 404ing on every batch.
# Set OTLP_TARGETS instead if you want traces to keep reaching OpenLIT.
OBSERVABILITY_SAMPLING=0.0
```

**Why**: this is the single most-copied block in the doc; leaving `:4318` here
means every new reader wires it to the wrong backend. The two comments state the
non-obvious constraints inline, where they are actually read.

### `docs/architecture/10-observability.md` (MODIFY — Prometheus/Grafana paragraph)

```markdown
# occurrences: 1 (verified: grep -c 'OBSERVABILITY_BACKEND=prometheus' docs/architecture/10-observability.md)
# REPLACE the paragraph beginning `For Prometheus + Grafana, set` (verified: docs/architecture/10-observability.md:77-79)
For **Prometheus + Grafana**, keep `OBSERVABILITY_BACKEND=otel` and point
`OTEL_EXPORTER_OTLP_ENDPOINT` at the Prometheus OTLP write receiver (above). The
dashboard is provisioned automatically into the **AI-Parrot** folder from
`docker/grafana/provisioning/dashboards/parrot/` — see `docker/grafana/README.md`.

`OBSERVABILITY_BACKEND=prometheus` is a *different*, non-OTel path: it exposes
`parrot_llm_*` counters via `prometheus_client` on `:9464` for Prometheus to
scrape, carries only `(provider, model)` labels, and cannot answer "cost by
agent". Use it only if you specifically want that.
```

**Why**: the old paragraph conflated the two Prometheus paths, which is the root
of the `parrot_llm_*` dashboard confusion (TASK-3111). Naming the label
limitation is what stops someone choosing it and then wondering where the agent
dimension went.

### `docs/architecture/10-observability.md` (MODIFY — config table)

```markdown
# occurrences: 1 (verified: grep -c '| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector base URL' docs/architecture/10-observability.md)
# REPLACE the OTEL_EXPORTER_OTLP_ENDPOINT row and EXPAND the OBSERVABILITY_SAMPLING
# row directly above it (verified: docs/architecture/10-observability.md:93-94)
| `OBSERVABILITY_SAMPLING` | trace sampling ratio (0.0–1.0). **`0.0` is the only env-level way to switch traces off** — `enable_traces` is code-only (`config.py:132`) | `1.0` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP **base** URL — `/v1/metrics` and `/v1/traces` are appended by the exporter. Metrics use this endpoint *only*; `OTLP_TARGETS` redirects traces alone | `http://localhost:4318` |
```

**Why**: the sampling row already exists but reads as a tuning knob; its real
role here is a kill-switch. The endpoint row must say "base" or people paste the
full path and get a doubled URL.

### `docs/architecture/10-observability.md` (MODIFY — new note)

```markdown
# AFTER — insert below the config-reference table (verified: docs/architecture/10-observability.md:96)

> **Not settable from the environment.** `enable_traces` / `enable_metrics`
> (`config.py:132-133`) and `metric_export_interval_ms` (`config.py:211`,
> default 60 s) are code-only fields — `from_env()` never reads them. To turn
> traces off from `.env`, set `OBSERVABILITY_SAMPLING=0.0`. Expect up to a
> minute before the first metrics appear.
>
> A ready-to-copy block lives at `env/.env.observability.example`.
```

**Why**: these three absences cost real debugging time — an empty dashboard for
60 s reads as a broken pipeline, and looking for `OBSERVABILITY_TRACES` finds
nothing. Stating them as an explicit "does not exist" note is the fix.

### `packages/ai-parrot/src/parrot/observability/examples/README.md` (MODIFY)

```markdown
# FILL IN: disambiguate — this file's §1/§4 both discuss the stack; quote 2-3
# surrounding lines to anchor uniquely. Reframe so that:
#   - metrics go to parrot-prometheus (:9090 OTLP write receiver)
#   - OpenLIT remains a TRACE destination, reached via OTLP_TARGETS
#   - the "Load the Grafana dashboard (optional)" step points at the provisioned
#     dashboard, not the deleted parrot-overview.json / parrot-usage.json
```

**Why**: the README still frames the whole example around OpenLIT and links the
two dashboards TASK-3111 deletes. Left alone it becomes a dangling link.

### `docker/grafana/README.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c '^## Grafana side' docker/grafana/README.md)
# BEFORE — insert above `## Grafana side`

## AI-Parrot side

```text
parrot --OTLP/http--> Prometheus <--query-- Grafana
        :9090/api/v1/otlp   :9090            :3001
```

No collector: Prometheus runs with `--enable-feature=otlp-write-receiver` and
takes the push directly. Put this in `env/.env` (full copy at
`env/.env.observability.example`):

```ini
[observability]
OBSERVABILITY_ENABLED=true
OBSERVABILITY_BACKEND=otel
OBSERVABILITY_SERVICE_NAME=parrot
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9090/api/v1/otlp
OBSERVABILITY_SAMPLING=0.0
OBSERVABILITY_COST=True
```

The endpoint is a **base URL** — the exporter appends `/v1/metrics`. Sampling is
`0.0` because that endpoint carries both signals, Prometheus 2.x serves no
`/v1/traces`, and `enable_traces` is not settable from the environment
(`config.py:132`). Metrics export every 60 s and that interval has no env var, so
allow a minute after the first LLM call before calling the dashboard broken.

Open [AI-Parrot — LLM Usage & Cost](http://localhost:3001/d/parrot-usage-cost/).

To diagnose an empty dashboard:

```bash
curl -fsSG http://localhost:9090/api/v1/query --data-urlencode 'query=count by (__name__) ({__name__=~"gen_ai_.*|parrot_.*"})'
docker compose -f docker/prometheus/docker-compose.yml ps
```

Real `gen_ai_*` series confirm parrot has exported. A dashboard alone cannot
create them.
```

**Why**: mirrors the "Codex side" section key-for-key — same diagram shape, same
config-block placement, same diagnostics — so the two producers read as one
documented system. The 60 s note pre-empts the most likely false bug report.

### FILL IN checklist

- [ ] `examples/README.md` anchors — bounded by "must disambiguate with 2-3 lines
      of context" (§1 and §4 both discuss the stack).
- [ ] Confirm the deep link path `/d/parrot-usage-cost/` matches TASK-3110's
      actual `uid`; bounded by AC-9.
- [ ] Step 5 grep result — every surviving `localhost:4318` must be deliberately
      about traces/OpenLIT; bounded by AC-15.

---

## Acceptance Criteria

- [ ] **AC-15** `docs/architecture/10-observability.md` contains no remaining
      instruction to point `OTEL_EXPORTER_OTLP_ENDPOINT` at `:4318` for metrics.
- [ ] No doc links to `parrot-overview.json` or `parrot-usage.json`
      (`git grep` returns nothing after TASK-3111).
- [ ] `docker/grafana/README.md` has an "AI-Parrot side" section with a topology
      diagram, the env block, and diagnostics.
- [ ] The config table documents `OTEL_EXPORTER_OTLP_ENDPOINT` as a **base** URL.
- [ ] The code-only fields note is present.

---

## Test Specification

Docs — no pytest. Verification is by grep:

```bash
git grep -n 'localhost:4318' -- docs/ packages/ai-parrot/src/parrot/observability/ docker/
# every hit must be about traces/OpenLIT, never metrics
git grep -n 'parrot-overview\|parrot-usage\.json'   # expect: no output
git grep -n 'parrot-usage-cost'                     # expect: docs + both dashboard dirs
```

---

## Agent Instructions

Standard SDD task flow. Run TASK-3111 first: this task's grep checks assume the
stale dashboards are already gone.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-09-10
**Notes**:
- All three listed files edited per the blueprint's exact anchors (all
  verified present at their stated line numbers before editing).
- **Files-to-Modify table was incomplete**: `packages/ai-parrot/src/parrot/
  observability/README.md` (the module README, distinct from
  `examples/README.md`) had two dangling links to the dashboards TASK-3111
  deleted. Not listed in this task's own file table, but TASK-3111's own
  dangling-reference grep step explicitly named it as "TASK-3112's input,"
  and this task's own AC ("No doc links to parrot-overview.json or
  parrot-usage.json") is phrased as a general absence, not scoped to 3
  files. Fixed both links (minimal, targeted edits — not a full rewrite of
  that file's OpenLIT-centric framing, which stays out of scope).
- §10.2's quickstart reframe went further than a literal one-line swap
  (the blueprint showed replacing just the endpoint line) because the
  surrounding steps 1-2 setting up an OpenLIT collector would have become
  incoherent next to a Prometheus-pointed step 3. Reframed the whole
  section coherently: Prometheus+Grafana as the primary path, OpenLIT
  explicitly retained as a trace destination via `OTLP_TARGETS` (per this
  task's own "reframe, do not remove" constraint).
- AC-15 and the dangling-link check both verified via `git grep` after the
  edits — see the code commit message for the exact commands and results.
- Deep link `/d/parrot-usage-cost/` confirmed to match TASK-3110's actual
  `uid` (`parrot-usage-cost`) by reading the dashboard JSON directly.

**Deviations from spec**: one file added beyond the task's own table
(`packages/ai-parrot/src/parrot/observability/README.md`) — justified
above as completing the task's own stated inputs/ACs, not scope creep.
§10.2 rewritten more broadly than the blueprint's literal single-line diff
to keep the section internally coherent — same net requirement (no
:4318-for-metrics instruction, OpenLIT reframed not removed), different
edit size.
