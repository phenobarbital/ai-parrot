"""CLI entry point for the FEAT-543 benchmark harness.

Offline by default and free. ``--live`` is the only path that spends money
and it requires at least five runs per scenario, per the spec's measurement
protocol.

Exit code is driven by **correctness only**: an optimized scenario whose
acceptance test fails exits non-zero. Token and latency figures are
informational — this harness reports numbers, it does not claim savings.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from .accounting import CostModel
from .runner import MIN_LIVE_RUNS, RunReport, run, summarize, write_reports
from .scenarios import SCENARIOS

DEFAULT_OUT = Path("artifacts") / "tool-optimizations" / "benchmarks"


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse the harness command line."""
    parser = argparse.ArgumentParser(prog="benchmarks.tool_optimizations", description=__doc__)
    parser.add_argument("--scenario", default="all", help="Scenario name, or 'all'.")
    parser.add_argument("--runs", type=int, default=5, help="Repetitions per scenario and mode.")
    parser.add_argument("--live", action="store_true", help="Use a real provider (spends money).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Report output directory.")
    parser.add_argument("--stamp", default=None, help="Report file stem (defaults to a UTC timestamp).")
    return parser.parse_args(argv)


def _live_client_factory():
    """Build a real client from the shipped example configuration."""
    from parrot.clients.factory import LLMFactory
    from parrot.mcp.toolkit_config import load_toolkits_config

    example = Path("examples") / "tool-optimizations-mcp.yaml"
    config = load_toolkits_config(example.parent, config_path=example)
    section = config.toolkits["targeted-writer"]

    def factory():
        return LLMFactory.create(section.llm, **section.llm_kwargs)

    return factory


async def _main_async(args: argparse.Namespace) -> int:
    """Run the selected scenarios and write the reports."""
    selected = SCENARIOS if args.scenario == "all" else [s for s in SCENARIOS if s.name == args.scenario]
    if not selected:
        print(
            f"unknown scenario {args.scenario!r}; choose from: {', '.join(s.name for s in SCENARIOS)}", file=sys.stderr
        )
        return 2

    client_factory = _live_client_factory() if args.live else None
    reports: list[RunReport] = []
    for scenario in selected:
        for mode in ("baseline", "optimized"):
            reports.extend(await run(scenario, mode, runs=args.runs, client_factory=client_factory))

    summary = summarize(reports, live=args.live, prices=CostModel.load())
    json_path, md_path = write_reports(summary, args.out, stamp=args.stamp)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")

    # Correctness parity is mandatory; the numbers are informational.
    failures = [
        entry["name"]
        for entry in summary.scenarios
        if entry["optimized"]["pass_rate"] is not None and entry["optimized"]["pass_rate"] < 1.0
    ]
    if failures:
        print(f"acceptance FAILED for: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


def _preload_toolkits() -> None:
    """Import the toolkits BEFORE the event loop is created.

    Importing `parrot` installs uvloop's event-loop policy as a side effect.
    If that happens lazily *inside* a running stdlib loop, the loop and the
    policy disagree: `asyncio.create_subprocess_exec` then asks uvloop's
    policy for a child watcher, which it does not implement, and every git
    call dies with `NotImplementedError`. Importing up front makes
    `asyncio.run()` build a loop that matches whatever policy is installed.
    """
    import parrot_tools.tool_optimizations.git  # noqa: F401
    import parrot_tools.tool_optimizations.reader  # noqa: F401
    import parrot_tools.tool_optimizations.writer  # noqa: F401


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments.

    Returns:
        The process exit code.
    """
    args = _parse_args(argv)
    _preload_toolkits()
    if args.live and args.runs < MIN_LIVE_RUNS:
        print(
            f"--live requires --runs >= {MIN_LIVE_RUNS} (spec measurement protocol); got {args.runs}",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(_main_async(args))


if __name__ == "__main__":  # pragma: no cover — process entry point
    sys.exit(main())
