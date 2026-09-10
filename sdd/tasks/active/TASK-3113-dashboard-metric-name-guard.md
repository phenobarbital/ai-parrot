# TASK-3113: Regression guard — shipped dashboards must query real metrics

**Feature**: FEAT-548 — Observability — OTEL to Prometheus + Grafana usage/cost dashboard
**Spec**: `sdd/specs/observability-otel-grafana.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3110, TASK-3111
**Assigned-to**: unassigned

---

## Context

Implements spec goal **G6** and the first four rows of spec §4 Unit Tests. This
is the task that stops the defect from coming back.

Two dashboards shipped for months querying metric names that no code path emits,
and nothing caught it — because a wrong PromQL expression renders as an empty
panel, not an error. This adds the test that turns that silent failure into a
red build.

---

## Scope

- Create `packages/ai-parrot/tests/unit/observability/test_dashboard_contract.py`.
- Assert every shipped dashboard's metric names map to a real instrument.
- Assert every grouping label is one the emitter actually attaches.
- Assert each dashboard declares a stable `uid` and a resolvable datasource.
- Assert no panel sums per-round and per-call token instruments together.

**NOT in scope**: authoring dashboards (TASK-3110/3111); the env-contract and
exporter tests (TASK-3114); querying a live Prometheus — this test must run in CI
with no docker.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/unit/observability/test_dashboard_contract.py` | CREATE | The G6 regression guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import json
from pathlib import Path
import pytest
# Deliberately NO opentelemetry import — see Key Constraints.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
# The authoritative instrument list this test encodes (verified line numbers):
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

# Attribute keys attached to metrics (verified: metrics.py:204-220, 273-306)
"gen_ai.system", "gen_ai.provider.name", "gen_ai.request.model",
"gen_ai.response.model", "parrot.agent.name", "gen_ai.token.type",
"gen_ai.operation.name", "error.type", "parrot.round.number",
"parrot.tool.name", "parrot.invoke.method"

# Existing test-suite conventions to match:
# packages/ai-parrot/tests/unit/observability/conftest.py
# packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py
```

### Does NOT Exist

- ~~a machine-readable export of the instrument list~~ — `MetricsSubscriber`
  builds instruments inside `__init__` against a live meter, so there is no
  module-level registry to import. The list must be encoded in the test.
- ~~`user_id` / `session_id` metric labels~~ — span-only (`attributes.py:126-133`).
  The test asserts their **absence** from dashboards.
- ~~`parrot_llm_*` on the OTel path~~ — those belong to
  `prometheus_recorder.py:44-80`. After TASK-3111 no shipped dashboard should
  reference them (unless §8 Q3 chose the rename, which the test must then allow
  for that one file by name).

---

## Implementation Notes

### Key Constraints

- **No `opentelemetry` import.** The `observability` extra may not be installed
  in the CI environment running unit tests; importing the SDK would make this
  guard skip exactly where it matters. Encode the catalog as data.
- **Match on the Prometheus-translated form.** Dashboards contain
  `gen_ai_client_request_count_total`, not `gen_ai.client.request.count`. Compare
  by normalizing: dots→underscores, then allow the known suffixes
  (`_total`, `_sum`, `_count`, `_bucket`, and a unit segment).
- Be tolerant of Grafana macros (`$__rate_interval`, `$agent`) and of template
  variables inside expressions — extract identifiers, do not parse PromQL fully.
- The fixture must glob **both** dashboard directories so a fix in one place and
  drift in the other is still caught.

---

## Implementation Blueprint

### Steps (in order)

1. Encode the instrument catalog and label set as module-level frozensets —
   *why*: no importable registry exists, and hard-coding is what makes the test
   independent of the optional SDK.
2. Write the metric-name extractor with a regex over each `expr` — *why*: full
   PromQL parsing is overkill; identifiers are enough to catch a wrong name.
3. Parametrize over every shipped dashboard so failures name the file.
4. Run against the CURRENT tree before TASK-3110/3111 land — *why*: it must FAIL
   on the two stale dashboards. A guard that passes on the known-bad input is not
   a guard.

### `packages/ai-parrot/tests/unit/observability/test_dashboard_contract.py` (CREATE)

```python
"""Shipped Grafana dashboards must only query metrics the emitter produces.

FEAT-548 goal G6. Both dashboards shipped before this test queried metric names
that no code path emits (``gen_ai_client_token_usage_total`` never existed;
``parrot_llm_*`` belongs to the non-OTel PrometheusUsageRecorder). A wrong PromQL
name renders as an empty panel rather than an error, so nothing caught it.

Deliberately imports no ``opentelemetry`` symbol: the ``observability`` extra may
be absent in CI, and a skipped guard is worse than none.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

DASHBOARD_DIRS = (
    REPO_ROOT / "packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards",
    REPO_ROOT / "docker/grafana/provisioning/dashboards/parrot",
)

# Verified against subscribers/metrics.py:96-160 (see the task's Codebase Contract).
INSTRUMENTS: frozenset[str] = frozenset({
    "gen_ai.client.request.count",
    "gen_ai.client.error.count",
    "gen_ai.client.cost.total",
    "gen_ai.client.operation.duration",
    "gen_ai.client.token.usage",
    "parrot.client.rounds",
    "parrot.client.round.token.usage",
    "parrot.tool.execution.duration",
    "parrot.tool.failure.count",
    "parrot.agent.invoke.duration",
    "parrot.agent.invoke.failure.count",
})

# Verified against metrics.py:204-220, 273-306.
METRIC_LABELS: frozenset[str] = frozenset({
    "gen_ai.system", "gen_ai.provider.name", "gen_ai.request.model",
    "gen_ai.response.model", "parrot.agent.name", "gen_ai.token.type",
    "gen_ai.operation.name", "error.type", "parrot.round.number",
    "parrot.tool.name", "parrot.invoke.method",
})

# Span-only attributes — must NEVER appear as a dashboard grouping label.
FORBIDDEN_LABELS: frozenset[str] = frozenset({"user_id", "session_id"})

_PROM_SUFFIXES = ("_total", "_sum", "_count", "_bucket")


def _prom_prefixes() -> frozenset[str]:
    """Prometheus-side prefixes for every instrument (dots -> underscores)."""
    return frozenset(name.replace(".", "_") for name in INSTRUMENTS)


def _iter_exprs(dashboard: dict):
    """Yield every PromQL expression in a dashboard (panels + templating)."""
    for panel in dashboard.get("panels", []):
        for target in panel.get("targets", []):
            if "expr" in target:
                yield panel.get("title", "<untitled>"), target["expr"]
    for var in dashboard.get("templating", {}).get("list", []):
        query = var.get("query")
        if isinstance(query, str):
            yield f"templating:{var.get('name')}", query


def _metric_names(expr: str) -> set[str]:
    """Extract candidate metric identifiers from a PromQL expression."""
    # FILL IN: exclude PromQL keywords/functions and Grafana macros ($__rate_interval,
    # $agent, le, by, on, and, ...) — bounded by "must not flag a function name as a
    # missing metric". Start from: re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr)
    raise NotImplementedError


def _dashboards() -> list[Path]:
    return sorted(p for d in DASHBOARD_DIRS if d.is_dir() for p in d.glob("*.json"))


@pytest.fixture(params=_dashboards(), ids=lambda p: p.name)
def dashboard(request) -> tuple[Path, dict]:
    path = request.param
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_shipped_dashboards_reference_real_metrics(dashboard):
    """Every gen_ai_*/parrot_* metric queried maps to a real instrument."""
    path, doc = dashboard
    prefixes = _prom_prefixes()
    for title, expr in _iter_exprs(doc):
        for name in _metric_names(expr):
            if not name.startswith(("gen_ai_", "parrot_")):
                continue
            base = name
            for suffix in _PROM_SUFFIXES:
                base = base.removesuffix(suffix)
            # FILL IN: also tolerate the unit segment the OTLP receiver may insert
            # (e.g. ..._tokens_bucket, ..._USD_total) — bounded by the real names
            # recorded in sdd/state/FEAT-548/verification/series-names.md
            assert any(base.startswith(p) for p in prefixes), (
                f"{path.name} panel {title!r} queries {name!r}, "
                f"which no MetricsSubscriber instrument emits"
            )


def test_shipped_dashboards_reference_real_labels(dashboard):
    """Grouping labels are ones the emitter actually attaches."""
    path, doc = dashboard
    allowed = {lbl.replace(".", "_") for lbl in METRIC_LABELS} | {"le"}
    for title, expr in _iter_exprs(doc):
        for group in re.findall(r"\bby\s*\(([^)]*)\)", expr):
            for label in (x.strip() for x in group.split(",") if x.strip()):
                if label.startswith("$"):
                    continue  # Grafana template variable
                assert label in allowed, (
                    f"{path.name} panel {title!r} groups by {label!r}, "
                    f"not a label the emitter attaches"
                )


def test_no_span_only_labels(dashboard):
    """user_id/session_id are span attributes and can never appear in metrics."""
    path, doc = dashboard
    for title, expr in _iter_exprs(doc):
        for forbidden in FORBIDDEN_LABELS:
            assert forbidden not in expr, (
                f"{path.name} panel {title!r} uses {forbidden!r}, which is a span "
                f"attribute deliberately excluded from metric labels (cardinality)"
            )


def test_no_round_token_double_count(dashboard):
    """Per-round and per-call token instruments are never summed together."""
    path, doc = dashboard
    for title, expr in _iter_exprs(doc):
        has_round = "parrot_client_round_token_usage" in expr
        has_call = "gen_ai_client_token_usage" in expr
        assert not (has_round and has_call), (
            f"{path.name} panel {title!r} combines per-round and per-call token "
            f"instruments — FEAT-397 keeps them separate to avoid double counting"
        )


def test_dashboard_json_is_valid_and_has_uid(dashboard):
    """Each dashboard declares a stable uid and a resolvable datasource."""
    path, doc = dashboard
    assert doc.get("uid"), f"{path.name} has no uid — it cannot be deep-linked"
    assert doc.get("title"), f"{path.name} has no title"
```

**Why this shape**: the catalog is data, not an import, so the guard runs
wherever pytest runs — that is the whole point, since the optional
`observability` extra is exactly what would make it skip in CI. Parametrizing per
file makes a failure name the offending dashboard. `_metric_names` is left as a
`FILL IN` because the keyword/macro exclusion list is a judgement call that
depends on which Grafana macros TASK-3110 actually uses.

### FILL IN checklist

- [ ] `_metric_names` — exclude PromQL functions/keywords and Grafana macros;
      bounded by "must not flag a function name as a missing metric".
- [ ] Unit-segment tolerance in `test_shipped_dashboards_reference_real_metrics`
      — bounded by the verbatim names in
      `sdd/state/FEAT-548/verification/series-names.md` (TASK-3108).
- [ ] If §8 Q3 kept a renamed recorder dashboard, allow `parrot_llm_*` for that
      one filename only; bounded by "must still reject it in any other file".

---

## Acceptance Criteria

- [ ] **AC-12** `pytest packages/ai-parrot/tests/unit/observability/test_dashboard_contract.py -v` passes.
- [ ] The test **fails** when pointed at the pre-TASK-3111 `parrot-overview.json`
      (verify by stashing the deletion, or with a temporary fixture copy).
      A guard that never fails on the known-bad input is not a guard.
- [ ] No `opentelemetry` import — the test runs without the `observability` extra.
- [ ] **AC-14** The existing suite still passes:
      `pytest packages/ai-parrot/tests/unit/observability/ -q`

---

## Test Specification

This task *is* the test. Its own meta-criterion is the second bullet above:
prove it catches the historical defect before you call it done.

---

## Agent Instructions

Standard SDD task flow. Write the test first and run it against the stale
dashboards to watch it fail; only then let TASK-3110/3111's outputs make it pass.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
