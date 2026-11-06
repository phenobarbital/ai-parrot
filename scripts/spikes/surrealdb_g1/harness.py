"""FEAT-824 Phase 1 — SurrealDB G1 spike harness.

Runs the G1 check list against a pinned SurrealDB server and SDK and writes a Markdown report
with a GO / NO-GO verdict. Not shipped in any wheel.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from pydantic import BaseModel, Field
from typing_extensions import Literal

logger = logging.getLogger("parrot.spikes.surrealdb_g1")


class CheckResult(BaseModel):
    """Outcome of one G1 check."""

    check_id: str
    title: str
    blocking: bool
    status: Literal["pass", "fail", "skipped"]
    evidence: str
    measurements: dict[str, float] = Field(default_factory=dict)
    fallback: str | None = None


CheckResult.model_rebuild()


class SpikeContext(BaseModel):
    """Connection settings and pinned versions for one run."""

    url: str
    username: str
    password: str
    server_image: str
    sdk_version: str


Check = Callable[[SpikeContext], Awaitable[CheckResult]]


def verdict(results: Sequence[CheckResult]) -> Literal["GO", "NO-GO"]:
    """GO only when every blocking check has status 'pass'."""
    for result in results:
        if result.blocking and result.status != "pass":
            return "NO-GO"
    return "GO" if results else "NO-GO"


def render_report(ctx: SpikeContext, results: Sequence[CheckResult]) -> str:
    """Render the Markdown report: versions, one row per check, measurements, verdict."""
    lines = []
    lines.append("# SurrealDB G1 Spike Report")
    lines.append("")
    lines.append(f"- **Server Image**: `{ctx.server_image}`")
    lines.append(f"- **SDK Version**: `{ctx.sdk_version}`")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("| ID | Check | Blocking | Status | Fallback | Evidence |")
    lines.append("|----|-------|----------|--------|----------|----------|")
    for result in results:
        lines.append(
            f"| {result.check_id} | {result.title} | {'Yes' if result.blocking else 'No'} | "
            f"{result.status} | {result.fallback or ''} | {result.evidence} |"
        )
    lines.append("")
    lines.append("## Measurements")
    lines.append("")
    for result in results:
        if result.measurements:
            lines.append(f"### {result.check_id}: {result.title}")
            for key, value in result.measurements.items():
                lines.append(f"- **{key}**: {value}")
    lines.append("")
    verdict_value = verdict(results)
    lines.append(f"**Verdict: {verdict_value}**")
    return "\n".join(lines)


async def run(ctx: SpikeContext, checks: Sequence[Check]) -> list[CheckResult]:
    """Run every check in order; a check that raises is recorded as 'fail' with the error."""
    results: list[CheckResult] = []
    for check in checks:
        try:
            results.append(await check(ctx))
        except Exception as exc:  # noqa: BLE001 — a crashing check is a failed check
            check_id = getattr(check, "check_id", getattr(check, "__name__", "unknown"))
            title = getattr(check, "title", "Unknown Check")
            blocking = getattr(check, "blocking", False)
            results.append(
                CheckResult(
                    check_id=check_id,
                    title=title,
                    blocking=blocking,
                    status="fail",
                    evidence=f"Exception: {type(exc).__name__}: {exc}",
                    fallback=None,
                )
            )
    return results


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: run all checks, write the report, exit 0 on GO and 1 on NO-GO."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="SurrealDB server URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--username",
        default="root",
        help="SurrealDB username (default: root)",
    )
    parser.add_argument(
        "--password",
        default="root",
        help="SurrealDB password (default: root)",
    )
    parser.add_argument(
        "--server-image",
        required=True,
        help="Pinned SurrealDB server image (e.g., surrealdb/surrealdb@sha256:...)",
    )
    parser.add_argument(
        "--sdk-version",
        required=True,
        help="Pinned SurrealDB SDK version (e.g., 2.0.0)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to write the Markdown report",
    )
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from checks import ALL_CHECKS  # created by TASK-5249

    ctx = SpikeContext(
        url=args.url,
        username=args.username,
        password=args.password,
        server_image=args.server_image,
        sdk_version=args.sdk_version,
    )
    results = asyncio.run(run(ctx, ALL_CHECKS))
    report = render_report(ctx, results)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report)
    logger.info("Verdict: %s", verdict(results))
    return 0 if verdict(results) == "GO" else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
