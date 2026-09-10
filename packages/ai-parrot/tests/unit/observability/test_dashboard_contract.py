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

# NOTE: TASK-3113's blueprint specified parents[4]; verified against this
# file's actual location (packages/ai-parrot/tests/unit/observability/)
# that resolves to `packages/`, not the repo root. parents[5] is correct —
# the same stale off-by-one already caught and fixed in TASK-3109's and
# TASK-3114's test files.
REPO_ROOT = Path(__file__).resolve().parents[5]

DASHBOARD_DIRS = (
    REPO_ROOT / "packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards",
    # NOTE: TASK-3113's blueprint specified .../dashboards/parrot — the
    # nested path TASK-3109 found (live-verified) caused Grafana's
    # claudestats provider to silently claim and misfile dashboards placed
    # there. Fixed to the sibling mount actually used by dashboards.yml /
    # docker-compose.yml (see TASK-3109's and TASK-3110's completion notes).
    REPO_ROOT / "docker/grafana/provisioning/dashboards-parrot",
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

# Verified verbatim renderings from sdd/state/FEAT-548/verification/series-names.md
# (TASK-3108, live TSDB capture). The OTel->Prometheus unit-insertion (e.g. the
# USD/seconds/tokens segment) is not re-derived algorithmically here — these
# are the real, empirically confirmed base names (before the
# _total/_sum/_count/_bucket suffix is appended/stripped).
CONFIRMED_PROM_BASES: frozenset[str] = frozenset({
    "gen_ai_client_request_count",                # gen_ai.client.request.count
    "gen_ai_client_cost_USD",                      # gen_ai.client.cost.total, unit USD
    "gen_ai_client_operation_duration_seconds",    # gen_ai.client.operation.duration, unit s
    "gen_ai_client_token_usage_tokens",             # gen_ai.client.token.usage, unit tokens
})

# The dotted instrument names CONFIRMED_PROM_BASES has an entry for. For
# these, ONLY the confirmed exact base is valid — code review (post-merge)
# correctly flagged that the generic dotted-to-underscore prefix fallback
# below would otherwise still accept a name that merely shares the prefix
# but omits the unit segment: e.g. the historical F009 defect string
# ``gen_ai_client_token_usage_total`` shares the prefix
# ``gen_ai_client_token_usage`` with the real, confirmed
# ``gen_ai_client_token_usage_tokens`` and would pass a plain
# ``startswith`` check even though it is exactly the wrong name this
# feature exists to stop shipping again.
_CONFIRMED_INSTRUMENTS: frozenset[str] = frozenset({
    "gen_ai.client.request.count",
    "gen_ai.client.cost.total",
    "gen_ai.client.operation.duration",
    "gen_ai.client.token.usage",
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

# PromQL functions/aggregators/keywords — never metric or label names.
_PROMQL_KEYWORDS: frozenset[str] = frozenset({
    "sum", "avg", "min", "max", "count", "topk", "bottomk", "stddev", "stdvar",
    "by", "without", "on", "ignoring", "group_left", "group_right",
    "and", "or", "unless", "bool", "offset",
    "rate", "irate", "increase", "delta", "idelta", "deriv", "predict_linear",
    "histogram_quantile", "label_replace", "label_join", "absent", "absent_over_time",
    "clamp", "clamp_min", "clamp_max", "round", "abs", "ceil", "floor",
    "instant", "vector", "scalar", "time",
})

# {label_name}(=~|!~|!=|=) — a label matcher key, never a metric name.
_LABEL_MATCH_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=~|!~|!=|=)")
# by(...) / without(...) / on(...) / ignoring(...) / group_left(...) / group_right(...)
# argument lists — contain only label names, never metric names.
_LABEL_LIST_MODIFIER_RE = re.compile(
    r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)"
)


def _prom_prefixes() -> frozenset[str]:
    """Best-effort dotted-to-underscore prefixes for UNCONFIRMED instruments only.

    Deliberately excludes every instrument in ``_CONFIRMED_INSTRUMENTS`` —
    those must match their ``CONFIRMED_PROM_BASES`` entry exactly. This
    fallback exists only for instruments TASK-3108's live verification
    never observed (``gen_ai.client.error.count``, the ``parrot.*``
    agent/tool instruments), where no better data is available yet.
    """
    return frozenset(
        name.replace(".", "_")
        for name in INSTRUMENTS
        if name not in _CONFIRMED_INSTRUMENTS
    )


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
    """Extract candidate metric identifiers from a PromQL expression.

    Strategy (identifiers only, not a full PromQL parse — sufficient to
    catch a wrong metric name):

    1. Strip quoted string literals — label values and label_replace's
       quoted label-name/regex arguments are never metric names.
    2. Collapse Grafana's (non-PromQL) ``label_values(metric, label)``
       template-variable helper to just its first argument — the second
       argument is a bare, unquoted label name by convention, not a metric.
    3. Strip ``{...}`` label-matcher blocks entirely — their contents are
       label names, never metric names (the metric name itself, if any,
       sits *before* the brace and survives this step).
    4. Strip ``by(...)``/``on(...)``/``without(...)``/``ignoring(...)``/
       ``group_left(...)``/``group_right(...)`` argument lists — these
       contain only label names (e.g. ``label_replace``'s first two extra
       args are already gone via step 1's quote strip; this step handles
       the aggregation/join modifiers).
    5. Whatever bare identifiers remain are candidates; drop PromQL
       keywords/functions and any leftover ``label=`` matcher keys
       (defensive, should already be empty after step 3).
    """
    stripped = re.sub(r'"[^"]*"', '""', expr)
    stripped = re.sub(r"\blabel_values\(\s*([^,()]+)\s*,[^)]*\)", r"\1", stripped)
    stripped = re.sub(r"\{[^}]*\}", "", stripped)
    stripped = _LABEL_LIST_MODIFIER_RE.sub("", stripped)

    candidates = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", stripped))
    candidates -= _PROMQL_KEYWORDS
    candidates -= {m.group(1) for m in _LABEL_MATCH_RE.finditer(stripped)}
    candidates = {c for c in candidates if not c.startswith("$") and not c.isdigit()}
    return candidates


def _dashboards() -> list[Path]:
    return sorted(p for d in DASHBOARD_DIRS if d.is_dir() for p in d.glob("*.json"))


@pytest.fixture(params=_dashboards(), ids=lambda p: p.name)
def dashboard(request) -> tuple[Path, dict]:
    path = request.param
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_dashboard_dirs_actually_contain_dashboards():
    """Canary: this guard is only a guard if it collects something.

    ``_dashboards()`` feeds ``pytest.fixture(params=...)`` at COLLECTION
    time — if both ``DASHBOARD_DIRS`` entries ever go stale (this exact
    class of drift already happened once mid-feature: the Grafana
    provisioning path moved from a nested ``dashboards/parrot/`` to the
    sibling ``dashboards-parrot/``, TASK-3109), every parametrized test
    above silently collects ZERO instances and the guard vanishes from a
    green test run instead of failing loudly. This test fails loudly.
    """
    found = _dashboards()
    assert found, (
        f"No dashboards found under any of {DASHBOARD_DIRS} — "
        "the G6 regression guard is not actually guarding anything. "
        "A DASHBOARD_DIRS path has gone stale."
    )
    assert len(found) >= 2, (
        f"Expected at least 2 shipped dashboards (parrot-usage-cost.json in "
        f"each of the two DASHBOARD_DIRS — the package example and the live "
        f"Grafana provisioning copy), found {len(found)}: "
        f"{[p.name for p in found]}"
    )


def test_shipped_dashboards_reference_real_metrics(dashboard):
    """Every gen_ai_*/parrot_* metric queried maps to a real instrument."""
    path, doc = dashboard
    prefixes = _prom_prefixes()
    for title, expr in _iter_exprs(doc):
        for name in _metric_names(expr):
            if not name.startswith(("gen_ai_", "parrot_")):
                continue
            # Strip exactly ONE trailing Prometheus suffix, not all of them
            # cumulatively — "gen_ai_client_request_count_total" legitimately
            # ends in "_count_total", and an unconditional loop over every
            # suffix would also strip "_count" afterwards, corrupting the base.
            base = name
            for suffix in _PROM_SUFFIXES:
                if base.endswith(suffix):
                    base = base[: -len(suffix)]
                    break
            assert base in CONFIRMED_PROM_BASES or any(base.startswith(p) for p in prefixes), (
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
