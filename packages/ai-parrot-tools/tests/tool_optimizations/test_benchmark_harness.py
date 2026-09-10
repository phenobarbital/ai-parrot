"""Tests for the benchmark harness and the docs it backs (TASK-3092, FEAT-543)."""

import json
import re
import sys
from pathlib import Path

import pytest

#: tests/tool_optimizations -> tests -> ai-parrot-tools -> packages -> repo root
ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.tool_optimizations.accounting import (  # noqa: E402
    CostModel,
    UsageRecord,
    cost_usd,
    totals_by_kind,
)
from benchmarks.tool_optimizations.runner import run, summarize, write_reports  # noqa: E402
from benchmarks.tool_optimizations.scenarios import SCENARIOS  # noqa: E402
from parrot_tools.tool_optimizations.hooks import coverage_matrix  # noqa: E402

DOC = ROOT / "docs" / "tool-optimizations.md"
REPORT_DIR = ROOT / "artifacts" / "tool-optimizations" / "benchmarks"


# --------------------------------------------------------------------------- #
# Accounting rules
# --------------------------------------------------------------------------- #
def test_unknown_usage_never_becomes_zero():
    """A provider that reports nothing must not flatter the results."""
    records = [
        UsageRecord(stage="primary_input", tokens=100, source="estimate:chars_div_4"),
        UsageRecord(stage="delegate_output", tokens=None, source="provider_usage"),
    ]
    totals = totals_by_kind(records)
    assert totals["primary_tokens"] == 100
    assert totals["delegate_tokens"] is None
    assert totals["total_tokens"] is None
    assert cost_usd(records, "any-model", CostModel.load()) is None


def test_prices_ship_empty_so_cost_is_unknown():
    """An invented price would be worse than no price."""
    assert CostModel.load().rows == {}


def test_primary_and_delegate_are_accounted_separately():
    """Work moved to the delegate must not vanish from the total."""
    records = [
        UsageRecord(stage="primary_input", tokens=10, source="estimate:chars_div_4"),
        UsageRecord(stage="review", tokens=5, source="estimate:chars_div_4"),
        UsageRecord(stage="delegate_input", tokens=50, source="provider_usage"),
        UsageRecord(stage="delegate_output", tokens=20, source="provider_usage"),
    ]
    totals = totals_by_kind(records)
    assert totals["primary_tokens"] == 15
    assert totals["delegate_tokens"] == 70
    assert totals["total_tokens"] == 85


# --------------------------------------------------------------------------- #
# Offline harness
# --------------------------------------------------------------------------- #
async def test_offline_harness_all_scenarios(tmp_path):
    """Every scenario runs offline, and the report schema is complete."""
    reports = []
    for scenario in SCENARIOS:
        for mode in ("baseline", "optimized"):
            reports.extend(await run(scenario, mode, runs=1, workdir=tmp_path))

    summary = summarize(reports)
    json_path, md_path = write_reports(summary, REPORT_DIR, stamp="pytest")
    data = json.loads(json_path.read_text())
    markdown = md_path.read_text()

    required = {
        "primary_tokens",
        "delegate_tokens",
        "total_tokens",
        "latency_median_ms",
        "latency_p95_ms",
        "pass_rate",
        "cost_usd",
    }
    for entry in data["scenarios"]:
        assert required <= set(entry["optimized"])
        assert required <= set(entry["baseline"])
        # Unknown, not zero, while prices.yaml is empty.
        assert entry["optimized"]["cost_usd"] is None

    # Correctness parity: any scenario with an executable acceptance test passed.
    assert all(entry["optimized"]["pass_rate"] in (1.0, None) for entry in data["scenarios"])

    # Primary vs total must both be visible — the report may never conflate them.
    assert "primary tokens" in markdown
    assert "total tokens" in markdown
    assert "p95" in markdown
    assert "NOT fewer total tokens" in markdown
    assert "No savings percentage is claimed" in markdown


async def test_decided_task_scenario_runs_a_real_acceptance_test(tmp_path):
    """The task scenario's pass rate reflects an executed pytest, not a claim."""
    scenario = next(item for item in SCENARIOS if item.name == "decided_task")
    reports = await run(scenario, "optimized", runs=1, workdir=tmp_path)
    assert reports[0].acceptance_passed is True

    sources = {record.source for record in reports[0].usage}
    assert "provider_usage" in sources, "delegate usage must be attributed to the provider"


def test_live_mode_requires_five_runs():
    """The measurement protocol's minimum is enforced before anything spends money."""
    from benchmarks.tool_optimizations.__main__ import main

    assert main(["--live", "--runs", "1"]) == 2


def test_unknown_scenario_is_rejected():
    """A typo must not silently benchmark nothing."""
    from benchmarks.tool_optimizations.__main__ import main

    assert main(["--scenario", "does-not-exist", "--runs", "1"]) == 2


# --------------------------------------------------------------------------- #
# Documentation
# --------------------------------------------------------------------------- #
def test_docs_coverage_matrix_in_sync():
    """The published matrix must match the code that implements it."""
    doc = DOC.read_text()
    block = re.search(r"<!-- coverage-matrix:begin -->(.*?)<!-- coverage-matrix:end -->", doc, re.S)
    assert block is not None, "coverage matrix markers are missing"
    body = block.group(1)

    for row in coverage_matrix():
        line = next((item for item in body.splitlines() if f"`{row['form']}`" in item), None)
        assert line is not None, f"{row['form']} missing from the documented matrix"
        expected = "yes" if row["covered"] else "no"
        assert f"| {expected} |" in line, f"{row['form']} documented as the wrong coverage"


def test_docs_have_release_gate_and_traceability():
    """The release gate and AC traceability must be stated, not implied."""
    doc = DOC.read_text()
    # Collapse wrapping so the assertions describe meaning, not line breaks.
    flat = " ".join(doc.split())
    assert "owner decision" in flat
    assert "No percentage saving is claimed anywhere" in flat
    for index in range(1, 16):
        assert f"AC{index}" in doc, f"AC{index} missing from the traceability table"


def test_docs_record_tested_host_versions_and_bypasses():
    """Coverage claims must be scoped to the versions actually tested."""
    doc = DOC.read_text()
    assert "2.1.267" in doc
    assert "0.154.0" in doc
    assert "Re-test after a host" in doc
    for bypass in ("write_stdin", "heredocs", "interpreters"):
        assert bypass in doc


def test_docs_are_linked_from_the_mcp_page():
    """The new page must be discoverable from the existing one."""
    assert "tool-optimizations.md" in (ROOT / "docs" / "mcp-local-toolkits.md").read_text()


def test_docs_state_the_codex_release_blocker():
    """The unverified Codex hooks format must be visible in the checklist."""
    doc = DOC.read_text()
    assert "Codex guard installation verified end to end" in doc
    assert "eventName" in doc


# --------------------------------------------------------------------------- #
# Tool-schema overhead
# --------------------------------------------------------------------------- #
def test_schema_overhead_is_measured_from_real_mcp_definitions(tmp_path):
    """The overhead must come from the definitions a host actually receives.

    Estimating it from source text, or omitting it, silently flatters the
    optimized arm: the schemas sit in the primary model's context on every
    turn and exist only because these servers were added.
    """
    import json as _json

    from parrot.mcp.adapter import MCPToolAdapter
    from parrot_tools.tool_optimizations.git import LocalGitToolkit

    from benchmarks.tool_optimizations.runner import _schema_overhead

    record = _schema_overhead("git_fetch_preflight_prepare", tmp_path)
    assert record.stage == "tool_schema_overhead"
    assert "real MCP tool definitions" in record.source
    assert record.tokens is not None and record.tokens > 0

    # It matches the definitions the MCP server would emit from tools/list.
    definitions = [
        MCPToolAdapter(tool).to_mcp_tool_definition() for tool in LocalGitToolkit(repo_root=tmp_path).get_tools()
    ]
    blob = _json.dumps(definitions, ensure_ascii=False, separators=(",", ":"))
    assert record.tokens == len(blob) // 4
    assert len(definitions) == 6


def test_schema_overhead_is_charged_to_primary_not_delegate():
    """The schemas live in the PRIMARY model's context window."""
    from benchmarks.tool_optimizations.accounting import DELEGATE_STAGES

    assert "tool_schema_overhead" not in DELEGATE_STAGES

    records = [
        UsageRecord(stage="tool_schema_overhead", tokens=1000, source="x"),
        UsageRecord(stage="delegate_output", tokens=10, source="provider_usage"),
    ]
    totals = totals_by_kind(records)
    assert totals["primary_tokens"] == 1000
    assert totals["delegate_tokens"] == 10


async def test_optimized_arm_pays_schema_overhead_and_baseline_does_not(tmp_path):
    """Only the optimized arm is charged; host built-ins cancel across arms."""
    scenario = next(item for item in SCENARIOS if item.name == "targeted_read")

    optimized = await run(scenario, "optimized", runs=1, workdir=tmp_path / "opt")
    baseline = await run(scenario, "baseline", runs=1, workdir=tmp_path / "base")

    optimized_stages = {record.stage for record in optimized[0].usage}
    baseline_stages = {record.stage for record in baseline[0].usage}

    assert "tool_schema_overhead" in optimized_stages
    assert "tool_schema_overhead" not in baseline_stages

    overhead = next(r for r in optimized[0].usage if r.stage == "tool_schema_overhead")
    assert overhead.tokens > 100, "a real schema is not a rounding error"


async def test_schema_overhead_changes_the_reported_totals(tmp_path):
    """The overhead must actually reach `primary_tokens`, not just be recorded.

    Regression guard: an accounting stage that is collected but dropped from
    the totals is indistinguishable from not measuring it at all.
    """
    scenario = next(item for item in SCENARIOS if item.name == "targeted_read")
    reports = await run(scenario, "optimized", runs=1, workdir=tmp_path)
    summary = summarize(reports)

    entry = summary.scenarios[0]["optimized"]
    overhead = next(r for r in reports[0].usage if r.stage == "tool_schema_overhead")
    payload = sum(r.tokens for r in reports[0].usage if r.stage != "tool_schema_overhead")

    assert entry["primary_tokens"] == overhead.tokens + payload
    assert entry["total_tokens"] == entry["primary_tokens"] + entry["delegate_tokens"]


def test_report_discloses_the_schema_overhead_accounting(tmp_path):
    """The report must state that the figure is marginal and a per-run floor."""
    from benchmarks.tool_optimizations.runner import render_markdown

    summary = summarize([])
    notes = " ".join(summary.notes)
    assert "MARGINAL cost" in notes
    assert "ONCE PER RUN" in notes
    assert "lower bound" in notes
    assert "cancel out" in notes
    assert "tool_schema_overhead" in render_markdown(summary) or "tool_schema_overhead" in notes
