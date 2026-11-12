"""``parrot finance`` — validate and explain accounting models (FEAT-713 M8)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from .errors import ModelValidationError, Problem
from .loader import load_model
from .models import AccountingModel, ChartSnapshot
from .snapshot import snapshot_from_manifest

if TYPE_CHECKING:
    from .live import ModelLiveStatus


def _interval_label(interval: tuple[date | None, date | None] | None) -> str:
    """Human-readable label of a problem interval (``None`` = not interval-specific)."""
    if interval is None:
        return "all intervals"
    start = interval[0].isoformat() if interval[0] is not None else "-inf"
    end = interval[1].isoformat() if interval[1] is not None else "+inf"
    return f"interval [{start} .. {end})"


def _interval_sort_key(interval: tuple[date | None, date | None] | None) -> tuple[int, date, date]:
    """Order: interval-independent problems first, then intervals by start then end (open ends outermost)."""
    if interval is None:
        return (0, date.min, date.min)
    return (1, interval[0] or date.min, interval[1] or date.max)


def _echo_problems(problems: list[Problem]) -> None:
    """Print every problem, grouped by interval."""
    groups: dict[tuple[date | None, date | None] | None, list[Problem]] = {}
    for problem in problems:
        groups.setdefault(problem.interval, []).append(problem)
    click.echo(f"{len(problems)} model validation problem(s):", err=True)
    for interval in sorted(groups, key=_interval_sort_key):
        click.echo(f"{_interval_label(interval)}:", err=True)
        for problem in groups[interval]:
            accounts = f" (accounts: {', '.join(problem.accounts)})" if problem.accounts else ""
            click.echo(f"  - [{problem.code}] {problem.message}{accounts}", err=True)


def _read_snapshot(snapshot_path: Path) -> ChartSnapshot:
    """Read the explicit chart manifest; malformed manifests become a usage error naming the option."""
    try:
        return snapshot_from_manifest(snapshot_path)
    except (ValueError, OSError) as exc:
        raise click.BadParameter(str(exc), param_hint="'--snapshot'") from exc


def _load_or_exit(path: Path, snapshot: ChartSnapshot) -> AccountingModel:
    """Structural load (no journal columns); print every problem and exit 1 on failure."""
    try:
        return load_model(path, snapshot)
    except ModelValidationError as exc:
        _echo_problems(exc.problems)
        raise SystemExit(1) from exc


def _arrow_frame_provider(journal_arrow: Path) -> Any:
    """Async frame provider serving the Arrow IPC file (file or stream format), read once off the event loop."""
    cache: dict[str, Any] = {}

    def _read() -> Any:
        import pyarrow as pa

        try:
            with pa.memory_map(str(journal_arrow), "r") as source:
                return pa.ipc.open_file(source).read_all()
        except pa.ArrowInvalid:
            with pa.memory_map(str(journal_arrow), "r") as source:
                return pa.ipc.open_stream(source).read_all()

    async def provider(name: str) -> Any:
        if "table" not in cache:
            cache["table"] = await asyncio.to_thread(_read)
        return cache["table"]

    return provider


async def _run_live(
    model: AccountingModel, models_dir: Path, snapshot_path: Path, journal_arrow: Path | None, today: date
) -> "ModelLiveStatus":
    """Build a toolkit over *models_dir* with the explicit manifest and validate the selected model live."""
    from .live import _validate_one
    from .toolkit import AccountingToolkit

    tenant, name = model.spec.tenant, model.spec.model
    toolkit = AccountingToolkit(
        models_dir=models_dir,
        snapshot_manifests={tenant: {name: snapshot_path}},
        frame_provider=_arrow_frame_provider(journal_arrow) if journal_arrow is not None else None,
    )
    try:
        return await _validate_one(toolkit, tenant, name, today=today)
    finally:
        if toolkit._engine is not None:
            await toolkit._engine.close()


def _echo_live(status: "ModelLiveStatus") -> bool:
    """Print a live status; return True when it is clean (no error, no drift, no failed assertion)."""
    if status.error is not None:
        click.echo(f"live validation failed for {status.tenant}/{status.model}: {status.error}", err=True)
        return False
    clean = True
    if status.drift_accounts:
        clean = False
        click.echo(f"chart drift: {len(status.drift_accounts)} unmapped account(s): {', '.join(status.drift_accounts)}")
    else:
        click.echo("chart drift: none")
    for result in status.assertion_results:
        if result.status == "failed":
            clean = False
        sides = f"lhs={result.lhs} rhs={result.rhs} tolerance={result.tolerance}"
        click.echo(
            f"assertion [{result.status}] {result.expr} ({sides}; "
            f"{result.period.from_.isoformat()} .. {result.period.to.isoformat()})"
        )
    if status.blocked:
        click.echo("model is BLOCKED by a failed 'block' assertion", err=True)
    return clean


@click.group("finance")
def finance() -> None:
    """Accounting metrics layer commands."""


@finance.command("validate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--snapshot", "snapshot_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--live", is_flag=True, help="Refresh the snapshot and run last-closed-month assertions plus drift.")
@click.option("--models-dir", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--journal-arrow", type=click.Path(exists=True, path_type=Path), default=None)
def validate(path: Path, snapshot_path: Path, live: bool, models_dir: Path | None, journal_arrow: Path | None) -> None:
    """Exit 1 on any Problem; prints the full problem list, grouped by interval."""
    model = _load_or_exit(path, _read_snapshot(snapshot_path))
    click.echo("structural validation passed; live column checks skipped")
    if not live:
        return
    if model.spec.chart_of_accounts.source.dataframe is not None and journal_arrow is None:
        raise click.UsageError(
            f"model {model.spec.model!r} reads its journal from the dataframe "
            f"{model.spec.chart_of_accounts.source.dataframe!r}; pass --journal-arrow <Arrow IPC file> for --live"
        )
    status = asyncio.run(
        _run_live(
            model,
            models_dir if models_dir is not None else path.parent.parent,
            snapshot_path,
            journal_arrow,
            datetime.now(timezone.utc).date(),
        )
    )
    if not _echo_live(status):
        raise SystemExit(1)
    click.echo("live validation passed")


@finance.command("explain")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("metric")
@click.option("--snapshot", "snapshot_path", required=True, type=click.Path(exists=True, path_type=Path))
def explain(path: Path, metric: str, snapshot_path: Path) -> None:
    """Print the formula, resolved accounts per set, and covering assertions."""
    from .grammar import parse_assertion, parse_expr, references
    from .toolkit import _metric_closure, _render

    model = _load_or_exit(path, _read_snapshot(snapshot_path))
    metrics = model.spec.metrics
    if metric not in metrics:
        known = ", ".join(sorted(metrics)) or "(none)"
        raise click.BadParameter(f"unknown metric {metric!r}; known metrics: {known}", param_hint="'METRIC'")
    definition = metrics[metric]
    inlined_text = _render(parse_expr(definition.expr), metrics, inline=True)
    set_names = sorted(references(parse_expr(inlined_text))[0])
    related = _metric_closure(metrics, frozenset({metric}))
    covering: list[str] = []
    for assertion in model.spec.assertions:
        left, right = parse_assertion(assertion.expr)
        if _metric_closure(metrics, references(left)[1] | references(right)[1]) & related:
            covering.append(assertion.expr)

    lines = [f"Metric: {metric} (model {model.spec.model}, tenant {model.spec.tenant})"]
    if definition.description:
        lines.append(f"Description: {definition.description}")
    if definition.unit:
        lines.append(f"Unit: {definition.unit}")
    lines.append(f"Formula: {definition.expr}")
    lines.append(f"Inlined formula: {inlined_text}")
    lines.append("Account sets:")
    for name in set_names:
        resolved_set = model.sets.get(name)
        if resolved_set is None:
            continue
        window = ""
        if resolved_set.valid_from is not None or resolved_set.valid_to is not None:
            start = resolved_set.valid_from.isoformat() if resolved_set.valid_from else "-inf"
            end = resolved_set.valid_to.isoformat() if resolved_set.valid_to else "+inf"
            window = f" [valid {start} .. {end})"
        lines.append(f"  - {name}{window}: {', '.join(resolved_set.accounts) or '(none)'}")
    lines.append("Covering assertions:")
    lines.extend(f"  - {expr}" for expr in covering)
    if not covering:
        lines.append("  (none)")
    click.echo("\n".join(lines))
