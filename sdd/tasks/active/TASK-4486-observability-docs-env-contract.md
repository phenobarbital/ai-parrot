# TASK-4486: Docs, env example and env contract for metrics fan-out and env switches

**Feature**: FEAT-705 — Observability — OTLP metrics fan-out and env-level trace/metric switches
**Spec**: `sdd/specs/observability-metrics-fanout-and-env-config.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4484, TASK-4485
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 plus the M5 env-contract tests, AC7, AC8, AC11. Four
documents still say the three fields are code-only and that metrics go to a
single endpoint. One of them, the architecture guide, actively recommends the
split routing that FEAT-705 breaks: "set `OTLP_TARGETS` to fan traces out to
OpenLIT while metrics keep going to Prometheus". After TASK-4484, nonempty
`OTLP_TARGETS` carries **both** signals and the single endpoint is ignored.

`test_env_contract.py` lives in this task, not a separate one: adding
`OBSERVABILITY_TRACES=false` to the example without extending
`RECOGNISED_ENV_VARS` turns `test_every_declared_key_is_read_by_from_env` red
(spec §7 "tripwire").

---

## Scope

- Rewrite the passages listed below in the four documents.
- Document the routing change and the collector migration of spec §2 in the README and the architecture guide; put a one-line pointer to it in the env example and the Grafana guide.
- Extend `RECOGNISED_ENV_VARS` with the three keys and add `test_docs_do_not_call_fields_code_only`.

**NOT in scope**:
- Any Python source change outside `test_env_contract.py`.
- Provisioning or shipping an OTel collector config (spec §2: operator prerequisite).
- Keeping `OBSERVABILITY_SAMPLING=0.0` in the Grafana `.env` block. Spec §8 Q4 is open, its default is "switch outright"; do that and record it in the Completion Note.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/README.md` | MODIFY | Env-key rows, fan-out of both signals, migration |
| `docs/architecture/10-observability.md` | MODIFY | Env block, OTLP_TARGETS paragraph, config table, migration |
| `env/.env.observability.example` | MODIFY | `OBSERVABILITY_TRACES=false`, commented examples, line 39 |
| `docker/grafana/README.md` | MODIFY | `.env` block and the sampling paragraph |
| `packages/ai-parrot/tests/unit/observability/test_env_contract.py` | MODIFY | Three keys + docs phrase test |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified on `dev` @ `89a052ec0` (2026-10-19). Every anchor below has occurrence count 1.

### Verified passages (current text)
```text
README.md:101-103   "For **multiple** OTLP destinations at once (e.g. OpenLIT + Grafana Tempo),
                     set `OTLP_TARGETS` instead of the single `OTEL_EXPORTER_OTLP_ENDPOINT` — one
                     `BatchSpanProcessor` is attached per target on the shared `TracerProvider`:"
README.md:201-202   `enable_traces` / `enable_metrics` field rows
README.md:211       `metric_export_interval_ms` field row
README.md:219-233   "## navconfig / env-var keys" table; last OBSERVABILITY row is
                     "| `OBSERVABILITY_SAMPLING` | `config.sampling_ratio` | Float string `"0.1"` → 10% sampling. |" (line 232)
README.md:235-240   "Note: `setup_telemetry` itself only auto-reads `PARROT_PRICING_PATH`. ..."
                     ends "... `OBSERVABILITY_PROM_PORT`, and `OBSERVABILITY_PROM_ADDR` (see ...)."

10-observability.md:68-71   "# Prometheus 2.x serves no /v1/traces, and enable_traces is a code-only field
                             # (config.py:132) — so silence traces here rather than 404ing on every batch.
                             # Set OTLP_TARGETS instead if you want traces to keep reaching OpenLIT.
                             OBSERVABILITY_SAMPLING=0.0"
10-observability.md:81-87   "For **traces**, OpenLIT remains a supported destination ... set `OTLP_TARGETS` ...
                             to fan traces out to OpenLIT while metrics keep going to Prometheus — one
                             `BatchSpanProcessor` is attached per target ..."   ← contradicts AC11, must be rewritten
10-observability.md:101     `OTLP_TARGETS` table row
10-observability.md:107     `OBSERVABILITY_SAMPLING` row ("**`0.0` is the only env-level way to switch traces off**")
10-observability.md:108     `OTEL_EXPORTER_OTLP_ENDPOINT` row ("Metrics use this endpoint *only*; `OTLP_TARGETS` redirects traces alone")
10-observability.md:112-117 "> **Not settable from the environment.** ..." blockquote

env/.env.observability.example:28-32  sampling comment + "OBSERVABILITY_SAMPLING=0.0"
env/.env.observability.example:39     "#   OTLP_TARGETS            - multi-endpoint export; traces only, not metrics"

docker/grafana/README.md:116-124  ```ini block with OBSERVABILITY_SAMPLING=0.0
docker/grafana/README.md:126-130  "The endpoint is a **base URL** ... `enable_traces` is not settable from the environment
                                   (`config.py:132`). Metrics export every 60 s and that interval has no env var, ..."
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/unit/observability/test_env_contract.py
REPO_ROOT = Path(__file__).resolve().parents[5]          # line 17 — the repo root
EXAMPLE = REPO_ROOT / "env/.env.observability.example"   # line 18
RECOGNISED_ENV_VARS: frozenset[str] = frozenset({ ... })  # lines 21-29; last row (line 28):
#   "OBSERVABILITY_OPENLIT_RECORDER", "OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT",
def test_every_declared_key_is_read_by_from_env()        # line 70 — must stay green
```

The keys read by `from_env()` after TASK-4485: `OBSERVABILITY_TRACES`,
`OBSERVABILITY_METRICS`, `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS`.

### Does NOT Exist
- ~~Per-target signal selection~~ (e.g. "metrics only to Prometheus") — `OtlpTarget` has only `name`/`endpoint`/`headers`. Never document it.
- ~~`OBSERVABILITY_ENABLE_TRACES` / `OBSERVABILITY_METRIC_INTERVAL`~~ — wrong names.
- ~~An env var for `histogram_buckets` / `otlp_protocol` / `otlp_headers`~~ — still code-only; do not claim otherwise.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/observability/README.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/architecture/10-observability.md",
      "action": "MODIFY"
    },
    {
      "path": "env/.env.observability.example",
      "action": "MODIFY"
    },
    {
      "path": "docker/grafana/README.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_env_contract.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Register: short, table-first, as the current docs are. Line references to code only where the docs already have them; refresh any `config.py:NNN` you touch.
- Required facts, stated once per document where relevant:
  1. `OTLP_TARGETS` fans out **traces and metrics**: one span processor and one metric reader per target.
  2. Nonempty `OTLP_TARGETS` **replaces** `OTEL_EXPORTER_OTLP_ENDPOINT` for both signals; the endpoint is only the single implicit target.
  3. `OBSERVABILITY_TRACES=false` is how to silence traces; `OBSERVABILITY_SAMPLING` is a sampling ratio (`0.0` still works).
  4. `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` shortens the 60 s wait for first metrics.
  5. **Breaking change / migration** (README and architecture guide in full): the old "endpoint = Prometheus, targets = OpenLIT" split now sends both signals to OpenLIT and no metrics to Prometheus. To keep metrics → Prometheus and traces → OpenLIT, run an OTLP collector with separate signal pipelines, point `OTEL_EXPORTER_OTLP_ENDPOINT` at it, leave `OTLP_TARGETS` unset, and set both switches true with nonzero sampling. Listing Prometheus and OpenLIT together is not equivalent: Prometheus rejects `/v1/traces`.
  6. README only: each target adds one reader thread and one collection per interval (spec §7 risk); duplicate entries in `OTLP_TARGETS` push twice.
- Never keep advice that the fallback endpoint still receives metrics when explicit targets are set (AC11).

---

## Implementation Blueprint

### Steps (in order)
1. Edit `test_env_contract.py` first — *why*: the tripwire then tells you immediately if the example declares an unread key.
2. Edit `env/.env.observability.example` — *why*: smallest file; its wording is reused below.
3. Edit `docker/grafana/README.md`.
4. Edit `docs/architecture/10-observability.md`, including the 81-87 paragraph — *why*: AC11.
5. Edit the package README.
6. Run the Validation Commands and `grep -in` the four banned phrases across the four files.

### `packages/ai-parrot/tests/unit/observability/test_env_contract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"OBSERVABILITY_OPENLIT_RECORDER", "OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT",' test_env_contract.py)
# AFTER — insert below line 28, inside the frozenset:
    # FEAT-705 — signal switches and metric export interval.
    "OBSERVABILITY_TRACES", "OBSERVABILITY_METRICS", "OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS",

# APPEND at end of file:
# FEAT-705 AC8 — phrases that described the pre-FEAT-705 limitations.
_STALE_PHRASES = (
    "code-only field",
    "not settable from the environment",
    "traces only, not metrics",
    "only env-level way",
)
_FEAT_705_DOCS = (
    "packages/ai-parrot/src/parrot/observability/README.md",
    "docs/architecture/10-observability.md",
    "env/.env.observability.example",
    "docker/grafana/README.md",
)


def test_docs_do_not_call_fields_code_only():
    """None of the four docs may still describe the FEAT-705 gaps."""
    # FILL IN: for each path in _FEAT_705_DOCS read (REPO_ROOT / path).read_text(encoding="utf-8").lower();
    #          collect (path, phrase) for every phrase found; assert the list is empty with a message
    #          naming each offender — case-insensitive, because arch :112 starts "Not settable"
```

### `env/.env.observability.example` (MODIFY)
```ini
# occurrences: 1 (verified: grep -c '^OBSERVABILITY_SAMPLING=0.0$' env/.env.observability.example)
# REPLACE lines 28-32 with:
# Trace subscriber switch. The endpoint above is Prometheus, which serves no
# /v1/traces, so traces are off. Turn them back on (and give them a
# trace-capable destination) to export spans.
OBSERVABILITY_TRACES=false

# Optional knobs (defaults shown):
# OBSERVABILITY_METRICS=true
# OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS=60000   # lower it to see metrics sooner
# OBSERVABILITY_SAMPLING=1.0                      # trace sampling ratio, 0.0-1.0

# occurrences: 1 (verified: grep -c 'traces only, not metrics' env/.env.observability.example)
# REPLACE line 39 with (FILL IN: keep the column alignment of line 38):
#   OTLP_TARGETS            - multi-endpoint export of traces AND metrics; when set
#                             it replaces OTEL_EXPORTER_OTLP_ENDPOINT for both signals
#                             (see docs/architecture/10-observability.md, migration)
```

### `docker/grafana/README.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^OBSERVABILITY_SAMPLING=0.0$' docker/grafana/README.md)
# In the ```ini block (lines 116-124) REPLACE `OBSERVABILITY_SAMPLING=0.0` with `OBSERVABILITY_TRACES=false`.

# occurrences: 1 (verified: grep -c 'is not settable from the environment' docker/grafana/README.md)
# REPLACE the paragraph at lines 126-130 with:
The endpoint is a **base URL** — the exporter appends `/v1/metrics`. Traces are
off (`OBSERVABILITY_TRACES=false`) because that endpoint is Prometheus, which
serves no `/v1/traces`. Metrics export every 60 s by default; set
`OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` lower to see them sooner. Before
adding `OTLP_TARGETS`, read the migration note in
`docs/architecture/10-observability.md`: explicit targets replace this endpoint
for both signals.
```

### `docs/architecture/10-observability.md` (MODIFY)
```markdown
# occurrences: 1 each (verified with grep -c on each anchor quoted in the Codebase Contract)
# lines 68-71 → comment + switch:
#   # Prometheus 2.x serves no /v1/traces, so switch the trace subscriber off.
#   OBSERVABILITY_TRACES=false
#   # Optional: OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS=10000 to see metrics sooner than 60 s.
# lines 81-87 → FILL IN: rewrite. Traces to OpenLIT: point OTEL_EXPORTER_OTLP_ENDPOINT at OpenLIT, or list
#   OpenLIT in OTLP_TARGETS — and either way metrics go there too. Then a "### Migrating split routing
#   (FEAT-705)" subsection carrying spec §2's before/after table and the collector recipe — Required fact 5.
# line 101 (OTLP_TARGETS row) → "multi-endpoint OTLP export of traces **and** metrics (JSON list);
#   replaces OTEL_EXPORTER_OTLP_ENDPOINT when nonempty"
# line 107 (SAMPLING row) → "trace sampling ratio (0.0–1.0)" — drop the "only env-level way" clause
# line 108 (ENDPOINT row) → OTLP base URL; the single implicit target for both signals when
#   OTLP_TARGETS is empty; ignored when it is set
# NEW rows after line 108: OBSERVABILITY_TRACES (`true`), OBSERVABILITY_METRICS (`true`),
#   OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS (`60000`)
# lines 112-115 → FILL IN: replace the "Not settable from the environment" blockquote with one line:
#   expect up to OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS (60 s by default) before the first metrics.
#   Keep the "> A ready-to-copy block lives at ..." line (117).
```

### `packages/ai-parrot/src/parrot/observability/README.md` (MODIFY)
```markdown
# lines 101-103 → "set `OTLP_TARGETS` instead of ... — one `BatchSpanProcessor` **and** one
#   `PeriodicExportingMetricReader` are attached per target. When set, it replaces
#   `OTEL_EXPORTER_OTLP_ENDPOINT` for both signals." + Required fact 6 + migration (fact 5),
#   pointing to the architecture guide's subsection for the full table.
# lines 201-202, 211 → append "Env: `OBSERVABILITY_TRACES`." / "Env: `OBSERVABILITY_METRICS`." /
#   "Env: `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` (positive int)."
# AFTER line 232 (occurrences 1) → three env-table rows, same column shape:
| `OBSERVABILITY_TRACES` | `config.enable_traces` | FEAT-705: `"false"` skips the trace subscriber. |
| `OBSERVABILITY_METRICS` | `config.enable_metrics` | FEAT-705: `"false"` skips the metrics subscriber. |
| `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` | `config.metric_export_interval_ms` | FEAT-705: positive int; invalid values log a warning and keep `60000`. |
# lines 235-240 → FILL IN: add the three keys to the "auto-boot additionally reads" list.
```

### FILL IN checklist
- [ ] `test_docs_do_not_call_fields_code_only` body — AC8, case-insensitive
- [ ] env example line 39 alignment
- [ ] architecture guide 81-87 rewrite + migration subsection — AC11
- [ ] architecture guide blockquote 112-115
- [ ] README auto-boot note 235-240

---

## Acceptance Criteria

- [ ] `env/.env.observability.example` uses `OBSERVABILITY_TRACES=false` instead of `OBSERVABILITY_SAMPLING=0.0` and documents the other two keys (spec AC7).
- [ ] `test_env_contract.py` passes, including the new `test_docs_do_not_call_fields_code_only` (AC7, AC8).
- [ ] No doc recommends keeping Prometheus solely on the fallback endpoint to preserve its metrics; README and architecture guide carry the migration (AC11).
- [ ] The four banned phrases no longer appear in any of the four documents (`grep -in` returns nothing).
- [ ] `ruff check` clean on `test_env_contract.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_env_contract.py -q`

---

## Test Specification

See the `test_env_contract.py` blueprint block; the test name is fixed by spec §4.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug observability-metrics-fanout-and-env-config --feature-id FEAT-705`).
2. **Check dependencies**: TASK-4484 and TASK-4485 must be `done` (the docs describe their behaviour; `RECOGNISED_ENV_VARS` may only list keys `from_env()` actually reads).
3. **Verify** each quoted passage still matches before editing.
4. **Update status** → `"in-progress"` in `sdd/tasks/index/observability-metrics-fanout-and-env-config.json`.
5. **Implement**; complete every `FILL IN`.
6. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. **Commit** only the five listed files.
8. **Close** with `scripts/sdd/close_task.sh TASK-4486 observability-metrics-fanout-and-env-config verified`.
9. **Fill in** the Completion Note (record the §8 Q4 choice) and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
