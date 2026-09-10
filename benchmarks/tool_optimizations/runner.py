"""Execute benchmark scenarios and summarize them (FEAT-543).

Offline by default: the delegate is a scripted fake, so a run costs nothing
and is deterministic. ``--live`` swaps in a real client built from
``examples/tool-optimizations-mcp.yaml`` and is the only path that spends
money; it requires at least five runs per scenario, per the spec's
measurement protocol.

Correctness is measured separately from tokens and latency, and it is the
only thing the harness treats as pass/fail. A scenario that is faster and
cheaper but no longer passes its acceptance test has not been optimized.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .accounting import (
    ESTIMATE_METHOD,
    CostModel,
    UsageRecord,
    cost_usd,
    estimate_tokens,
    median,
    percentile,
    totals_by_kind,
)
from .scenarios import Scenario, build_git_repo, build_large_file_repo

__all__ = ("RunReport", "ScenarioSummary", "Summary", "run", "summarize", "write_reports")

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "bench",
    "GIT_AUTHOR_EMAIL": "bench@example.com",
    "GIT_COMMITTER_NAME": "bench",
    "GIT_COMMITTER_EMAIL": "bench@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "LC_ALL": "C",
}

#: Minimum runs required for a live comparison (spec §4).
MIN_LIVE_RUNS = 5


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command with the deterministic benchmark environment."""
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=True)


class RunReport(BaseModel):
    """The result of one scenario executed once in one mode.

    Attributes:
        scenario: The scenario name.
        mode: ``baseline`` or ``optimized``.
        run_index: 0-based index within the repetition set.
        warm: True for the second and later runs (cache/context warm).
        elapsed_ms: Wall-clock duration.
        usage: Accounted token usage.
        acceptance_passed: Real acceptance outcome, or None when the
            scenario has no executable acceptance test.
        retries: Repair/retry count reported by the tooling.
        model: The model identity involved, if any.
    """

    model_config = ConfigDict(extra="forbid")

    scenario: str
    mode: str
    run_index: int
    warm: bool
    elapsed_ms: int
    usage: list[UsageRecord] = Field(default_factory=list)
    acceptance_passed: Optional[bool] = None
    retries: int = 0
    model: Optional[str] = None


class ScenarioSummary(BaseModel):
    """Aggregated statistics for one scenario/mode pair."""

    model_config = ConfigDict(extra="forbid")

    primary_tokens: Optional[int] = None
    delegate_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_median_ms: Optional[float] = None
    latency_p95_ms: Optional[float] = None
    pass_rate: Optional[float] = None
    cost_usd: Optional[float] = None
    runs: int = 0
    sources: list[str] = Field(default_factory=list)


class Summary(BaseModel):
    """The full comparison across scenarios."""

    model_config = ConfigDict(extra="forbid")

    created_at: str
    live: bool
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Scenario execution
# --------------------------------------------------------------------------- #

#: Which toolkits a host must load to run each scenario's optimized path.
#: `decided_task` includes the reader because the workflow reviews the patch
#: through `source_read` before applying it.
_SCENARIO_TOOLKITS: dict[str, tuple[str, ...]] = {
    "git_fetch_preflight_prepare": ("git.LocalGitToolkit",),
    "targeted_read_large_file": ("reader.BoundedSourceToolkit",),
    "decided_create_modify_task": ("writer.TargetedWriterToolkit", "reader.BoundedSourceToolkit"),
}


def _schema_overhead(kind: str, repo_root: Path) -> UsageRecord:
    """Measure the tool-schema tokens the optimized path adds to every turn.

    This is the cost of the MCP tool definitions themselves sitting in the
    primary model's context. It is measured from the *real* definitions a
    host receives — `MCPToolAdapter.to_mcp_tool_definition()`, the same JSON
    the server emits from `tools/list` — not estimated from the source.

    Two accounting decisions, both deliberately conservative *against* the
    optimized side being flattered:

    * It is charged to the **primary** model, because that is whose context
      window holds it.
    * It is charged **once per run**, which is a floor. In reality the
      schemas are re-sent every turn, so a multi-turn task pays this
      repeatedly. Treat the reported figure as a lower bound.

    The baseline arm is charged zero: the host's own built-in tools are
    present in both arms and therefore cancel. What is measured here is the
    *marginal* overhead of adding these servers.

    Args:
        kind: The scenario kind.
        repo_root: A repository root to construct the toolkits against.

    Returns:
        A usage record for the ``tool_schema_overhead`` stage.
    """
    from parrot.mcp.adapter import MCPToolAdapter

    from parrot_tools.tool_optimizations import git as git_module
    from parrot_tools.tool_optimizations import reader as reader_module
    from parrot_tools.tool_optimizations import writer as writer_module

    modules = {"git": git_module, "reader": reader_module, "writer": writer_module}
    definitions: list[dict[str, Any]] = []
    for dotted in _SCENARIO_TOOLKITS.get(kind, ()):
        module_name, class_name = dotted.split(".")
        toolkit_cls = getattr(modules[module_name], class_name)
        toolkit = toolkit_cls(repo_root=repo_root)
        definitions.extend(MCPToolAdapter(tool).to_mcp_tool_definition() for tool in toolkit.get_tools())

    blob = json.dumps(definitions, ensure_ascii=False, separators=(",", ":"))
    return UsageRecord(
        stage="tool_schema_overhead",
        tokens=estimate_tokens(blob),
        source="estimate:chars_div_4 over real MCP tool definitions",
    )


async def _run_git_scenario(mode: str, workdir: Path) -> tuple[list[UsageRecord], Optional[bool], int]:
    """Execute the Git scenario in one mode."""
    from parrot_tools.tool_optimizations.git import LocalGitToolkit

    repo, _remote = build_git_repo(workdir, _git)
    records: list[UsageRecord] = []

    if mode == "baseline":
        # What a host issues without the tools: three shell commands whose
        # full stdout lands in the context window.
        output = ""
        for args in (["fetch", "origin", "dev"], ["status", "--short"], ["diff", "--check"]):
            output += subprocess.run(["git", *args], cwd=repo, env=GIT_ENV, capture_output=True, text=True).stdout
        output += subprocess.run(
            ["git", "add", "--", "feature.py"], cwd=repo, env=GIT_ENV, capture_output=True, text=True
        ).stdout
        output += subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=repo, env=GIT_ENV, capture_output=True, text=True
        ).stdout
        records.append(UsageRecord(stage="primary_input", tokens=estimate_tokens(output), source=ESTIMATE_METHOD))
        return records, None, 0

    records.append(_schema_overhead("git_fetch_preflight_prepare", repo))
    toolkit = LocalGitToolkit(repo_root=repo)
    payload = ""
    for result in (
        await toolkit.git_fetch(remote="origin", branch="dev", recent=3),
        await toolkit.git_preflight(),
        await toolkit.git_prepare_files(["feature.py"]),
    ):
        payload += json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    records.append(UsageRecord(stage="primary_input", tokens=estimate_tokens(payload), source=ESTIMATE_METHOD))
    return records, None, 0


async def _run_read_scenario(mode: str, workdir: Path) -> tuple[list[UsageRecord], Optional[bool], int]:
    """Execute the bounded-read scenario in one mode."""
    from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit

    repo = build_large_file_repo(workdir)
    records: list[UsageRecord] = []

    if mode == "baseline":
        # The whole file enters the context window.
        text = (repo / "big_module.py").read_text()
        records.append(UsageRecord(stage="primary_input", tokens=estimate_tokens(text), source=ESTIMATE_METHOD))
        return records, None, 0

    records.append(_schema_overhead("targeted_read_large_file", repo))
    toolkit = BoundedSourceToolkit(repo_root=repo)
    info = await toolkit.source_info("big_module.py")
    chunk = await toolkit.source_read("big_module.py", 1, 350)
    payload = json.dumps(info.model_dump(mode="json"), ensure_ascii=False) + json.dumps(
        chunk.model_dump(mode="json"), ensure_ascii=False
    )
    records.append(UsageRecord(stage="primary_input", tokens=estimate_tokens(payload), source=ESTIMATE_METHOD))
    return records, None, 0


async def _run_task_scenario(mode: str, workdir: Path, client_factory) -> tuple[list[UsageRecord], Optional[bool], int]:
    """Execute the decided-TASK scenario in one mode."""
    sys.path.insert(0, str(_repo_root() / "packages" / "ai-parrot-tools" / "tests"))
    from tool_optimizations.fixtures import GOOD_PATCH, make_repo_with_target, make_valid_task

    from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit
    from parrot_tools.tool_optimizations.writer import TargetedWriterToolkit

    repo = make_repo_with_target(workdir)
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_greeter.py").write_text(
        "from pkg.greeter import greet\n\n\ndef test_greet():\n    assert greet('world') == 'hello world'\n"
    )
    # `writer_apply` re-checks that no target is already staged, so it needs a
    # real repository — the same precondition a host would have in practice.
    _git(repo, "init", "-q", "-b", "dev")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    task = make_valid_task(repo)
    task_path = task.relative_to(repo).as_posix()
    records: list[UsageRecord] = []

    if mode == "baseline":
        # The primary model reads the TASK and writes both files itself.
        prompt = task.read_text()
        records.append(UsageRecord(stage="primary_input", tokens=estimate_tokens(prompt), source=ESTIMATE_METHOD))
        records.append(UsageRecord(stage="primary_output", tokens=estimate_tokens(GOOD_PATCH), source=ESTIMATE_METHOD))
        # Simulate the same end state so the acceptance test is comparable.
        (repo / "pkg" / "greeter.py").write_text(
            'def greet(name: str) -> str:\n    """Return a greeting."""\n    return f"hello {name}"\n'
        )
        passed = _run_acceptance(repo)
        return records, passed, 0

    records.append(_schema_overhead("decided_create_modify_task", repo))
    client = client_factory()
    writer = TargetedWriterToolkit(repo_root=repo, llm_client=client)
    generated = await writer.writer_generate(task_path)
    if generated.status != "ok":
        return records, False, 0

    # Planning + the delegate's own usage, kept apart.
    records.append(
        UsageRecord(stage="planning_packet", tokens=estimate_tokens(task.read_text()), source=ESTIMATE_METHOD)
    )
    usage = generated.data.get("usage") or {}
    records.append(UsageRecord(stage="delegate_input", tokens=usage.get("prompt_tokens"), source="provider_usage"))
    records.append(UsageRecord(stage="delegate_output", tokens=usage.get("completion_tokens"), source="provider_usage"))

    # The primary model reviews every hunk through the bounded reader.
    reader = BoundedSourceToolkit(repo_root=repo)
    reviewed = ""
    cursor = 1
    while cursor is not None:
        chunk = await reader.source_read(generated.data["patch_path"], cursor, cursor + 349)
        if getattr(chunk, "content", None) is None:
            break
        reviewed += chunk.content
        cursor = chunk.next_line
    records.append(UsageRecord(stage="review", tokens=estimate_tokens(reviewed), source=ESTIMATE_METHOD))

    applied = await writer.writer_apply(generated.data["artifact_id"], generated.data["patch_sha256"])
    if applied.status != "ok":
        return records, False, int(generated.data.get("repairs", 0))

    passed = _run_acceptance(repo)
    return records, passed, int(generated.data.get("repairs", 0))


def _repo_root() -> Path:
    """Return the repository root (this file lives at benchmarks/<pkg>/)."""
    return Path(__file__).resolve().parents[2]


def _run_acceptance(repo: Path) -> bool:
    """Run the scenario's real acceptance test and report its exit code."""
    env = dict(os.environ)
    root = _repo_root()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(root / "packages" / "ai-parrot" / "src"),
            str(root / "packages" / "ai-parrot-tools" / "src"),
            env.get("PYTHONPATH", ""),
        ]
    ).rstrip(os.pathsep)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_greeter.py", "-q"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    return completed.returncode == 0


def _default_client_factory():
    """Return the offline scripted delegate."""
    sys.path.insert(0, str(_repo_root() / "packages" / "ai-parrot-tools" / "tests"))
    from tool_optimizations.fixtures import GOOD_PATCH
    from tool_optimizations.test_writer import FakeClient

    return FakeClient([GOOD_PATCH])


async def run(
    scenario: Scenario,
    mode: str,
    *,
    runs: int = 5,
    workdir: Optional[Path] = None,
    client_factory=None,
) -> list[RunReport]:
    """Execute one scenario in one mode, ``runs`` times.

    Args:
        scenario: The scenario to execute.
        mode: ``baseline`` or ``optimized``.
        runs: Repetitions.
        workdir: Directory for scratch repositories.
        client_factory: Callable returning the delegate client.

    Returns:
        One :class:`RunReport` per repetition.
    """
    import tempfile

    factory = client_factory or _default_client_factory
    base = Path(workdir or tempfile.mkdtemp())
    reports: list[RunReport] = []

    for index in range(runs):
        attempt_dir = base / f"{scenario.name}-{mode}-{index}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()

        if scenario.kind == "git_fetch_preflight_prepare":
            records, passed, retries = await _run_git_scenario(mode, attempt_dir)
        elif scenario.kind == "targeted_read_large_file":
            records, passed, retries = await _run_read_scenario(mode, attempt_dir)
        else:
            records, passed, retries = await _run_task_scenario(mode, attempt_dir, factory)

        reports.append(
            RunReport(
                scenario=scenario.name,
                mode=mode,
                run_index=index,
                warm=index > 0,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                usage=records,
                acceptance_passed=passed,
                retries=retries,
                model=None,
            )
        )
    return reports


# --------------------------------------------------------------------------- #
# Summarizing and reporting
# --------------------------------------------------------------------------- #
def _summarize_mode(reports: list[RunReport], prices: CostModel) -> ScenarioSummary:
    """Aggregate the repetitions of one scenario/mode pair."""
    if not reports:
        return ScenarioSummary()

    records = [record for report in reports for record in report.usage]
    latencies = [float(report.elapsed_ms) for report in reports]
    outcomes = [report.acceptance_passed for report in reports if report.acceptance_passed is not None]

    totals = totals_by_kind(records)
    return ScenarioSummary(
        **totals,
        latency_median_ms=median(latencies),
        latency_p95_ms=percentile(latencies, 0.95),
        pass_rate=(sum(1 for value in outcomes if value) / len(outcomes)) if outcomes else None,
        cost_usd=cost_usd(records, reports[0].model or "", prices),
        runs=len(reports),
        sources=sorted({record.source for record in records}),
    )


def summarize(reports: list[RunReport], *, live: bool = False, prices: Optional[CostModel] = None) -> Summary:
    """Build the comparison summary from raw run reports.

    Args:
        reports: All run reports, any scenario and mode.
        live: Whether a real provider was used.
        prices: The price table; loaded from disk when omitted.

    Returns:
        The populated summary.
    """
    table = prices or CostModel.load()
    names = []
    for report in reports:
        if report.scenario not in names:
            names.append(report.scenario)

    scenarios: list[dict[str, Any]] = []
    for name in names:
        entry: dict[str, Any] = {"name": name}
        for mode in ("baseline", "optimized"):
            subset = [report for report in reports if report.scenario == name and report.mode == mode]
            entry[mode] = _summarize_mode(subset, table).model_dump(mode="json")
        scenarios.append(entry)

    notes = [
        "Baseline token counts are estimates (estimate:chars_div_4), not provider measurements.",
        "Delegate token counts come from provider usage; `null` means the provider reported nothing "
        "— it never means zero.",
        "Cost is `unknown` until benchmarks/tool_optimizations/prices.yaml is filled in with sourced prices.",
        "Primary and total tokens are reported separately: fewer primary tokens is NOT fewer total tokens.",
        "tool_schema_overhead is the MARGINAL cost of adding these MCP servers, measured from the real "
        "tool definitions a host receives. It is charged to the primary model (whose context holds it) and "
        "ONCE PER RUN — schemas are re-sent every turn, so this is a lower bound on a multi-turn task.",
        "The baseline arm is charged no schema overhead: the host's own built-in tools exist in both arms "
        "and cancel out.",
        "No savings percentage is claimed. Numeric targets are an owner decision (spec section 8).",
    ]
    if not live:
        notes.append("Offline run: the delegate was a scripted fake, so delegate latency is not representative.")
    return Summary(created_at=datetime.now(timezone.utc).isoformat(), live=live, scenarios=scenarios, notes=notes)


def _fmt(value: Any) -> str:
    """Render a possibly-unknown number for the Markdown table."""
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def render_markdown(summary: Summary) -> str:
    """Render the summary as a Markdown report.

    Args:
        summary: The summary to render.

    Returns:
        The Markdown text.
    """
    lines = [
        "# Tool optimizations benchmark",
        "",
        f"- Generated: {summary.created_at}",
        f"- Mode: {'LIVE (real provider)' if summary.live else 'offline (scripted delegate)'}",
        "",
        "| Scenario | Mode | primary tokens | delegate tokens | total tokens | latency median ms | latency p95 ms "
        "| pass rate | cost USD | sources |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in summary.scenarios:
        for mode in ("baseline", "optimized"):
            data = entry[mode]
            lines.append(
                f"| {entry['name']} | {mode} | {_fmt(data['primary_tokens'])} | {_fmt(data['delegate_tokens'])} "
                f"| {_fmt(data['total_tokens'])} | {_fmt(data['latency_median_ms'])} | {_fmt(data['latency_p95_ms'])} "
                f"| {_fmt(data['pass_rate'])} | {_fmt(data['cost_usd'])} | {', '.join(data['sources']) or 'n/a'} |"
            )
    lines += ["", "## Notes", ""]
    lines += [f"- {note}" for note in summary.notes]
    return "\n".join(lines) + "\n"


def write_reports(summary: Summary, directory: Path, *, stamp: Optional[str] = None) -> tuple[Path, Path]:
    """Write the JSON and Markdown reports side by side.

    Args:
        summary: The summary to persist.
        directory: Output directory (created if needed).
        stamp: File stem; defaults to a UTC timestamp.

    Returns:
        A ``(json_path, markdown_path)`` tuple.
    """
    directory.mkdir(parents=True, exist_ok=True)
    name = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = directory / f"{name}.json"
    md_path = directory / f"{name}.md"
    json_path.write_text(json.dumps(summary.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    return json_path, md_path
