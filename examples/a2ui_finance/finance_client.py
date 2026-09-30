"""A2UI finance example client — open the dashboard, or run a headless check whose EXPECTED values come from the backend.

Run: ENV=prod python examples/a2ui_finance/finance_client.py --check --base-url http://localhost:5001
     python examples/a2ui_finance/finance_client.py --open --base-url http://localhost:5001

``--check`` logs in, fetches the (definition-only) envelope, verifies it ships no rows, replays exactly the requests the
browser lane sends (each source's own conditions, ``querylimit`` capped at 5000, the v2 services route) and compares
the answers with values computed IN-PROCESS through ``DatasetManager`` (``add_query`` + ``materialize`` over the same
slugs, aggregated with pandas). Finance data drifts daily, so nothing is hard-coded. It also exercises the grid's
server paging. Exit 0 only when every check passes. ``--no-expect`` prints the values without computing expectations
(no DatasetManager / QuerySource needed on the client side).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any

import aiohttp

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "a2ui"))

from client import (  # noqa: E402 - reused from the Polestar example
    CheckError,
    emit,
    env_setting,
    fetch_dashboard,
    lane_body,
    login,
    open_dashboard,
    page_bodies,
    post_query,
)
from finance_dashboard import GRID_KEY, LATEST_SLUG, SNAPSHOTS_SLUG, WIDGETS  # noqa: E402

logger = logging.getLogger("a2ui_finance.client")

DEFAULT_BASE_URL = "http://localhost:5001"
GRID_PAGE = 20
KPI_KEYS = ["kpi_rev_actual", "kpi_rev_budget", "kpi_rev_variance", "kpi_ebitda_variance"]
GROUP_KEYS = {"by_division": "division", "by_project": "project", "trend": "snapshot_date"}
EXPECTED_KEYS = [widget["key"] for widget in WIDGETS]
TREND_FIELDS = ["snapshot_date", "sum(rev_actual) AS rev_actual", "sum(rev_budget) AS rev_budget"]


def close(actual: Any, expected: Any) -> bool:
    """Money values compared with a tolerance (JSON floats vs pandas float64)."""
    try:
        return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=0.01)
    except (TypeError, ValueError):
        return False


def label(value: Any) -> str:
    """Normalise a group label (a date from JSON vs a Timestamp from pandas) to a comparable string."""
    if value is None:
        return ""
    text = str(value)
    return text[:10] if len(text) >= 10 and text[4] == "-" and text[7] == "-" else text


def _expected_from_frames(latest: Any, trend: Any) -> dict[str, Any]:
    """Aggregate the two DatasetManager frames into the values every widget must show."""
    rev_actual = float(latest["rev_actual"].sum())
    rev_budget = float(latest["rev_budget"].sum())
    ebitda_variance = float(latest["ebitda_actual"].sum() - latest["ebitda_budget"].sum())
    by_division = latest.groupby("division", dropna=False)[["rev_actual", "rev_budget"]].sum().sort_index()
    by_project = latest.groupby("project", dropna=False)[["rev_actual"]].sum().sort_index()
    return {
        "kpis": {
            "kpi_rev_actual": ("rev_actual", rev_actual),
            "kpi_rev_budget": ("rev_budget", rev_budget),
            "kpi_rev_variance": ("rev_variance", rev_actual - rev_budget),
            "kpi_ebitda_variance": ("ebitda_variance", ebitda_variance),
        },
        "groups": {
            "by_division": {
                label(name): {"rev_actual": float(row.rev_actual), "rev_budget": float(row.rev_budget)}
                for name, row in by_division.iterrows()
            },
            "by_project": {label(name): {"rev_actual": float(row.rev_actual)} for name, row in by_project.iterrows()},
            "trend": {
                label(row["snapshot_date"]): {
                    "rev_actual": float(row["rev_actual"]),
                    "rev_budget": float(row["rev_budget"]),
                }
                for _, row in trend.iterrows()
            },
        },
        "grid_total": int(len(latest)),
    }


async def expected_values(manager: Any | None = None) -> dict[str, Any]:
    """Compute the expected dashboard values through ``DatasetManager`` (``add_query`` + ``materialize``).

    Args:
        manager: A ``DatasetManager`` (or a stand-in exposing ``add_query`` / ``materialize``); built when omitted.

    Returns:
        ``{"kpis": {key: (column, value)}, "groups": {key: {label: {column: value}}}, "grid_total": int}``.
    """
    if manager is None:
        from parrot.tools.dataset_manager.tool import DatasetManager

        manager = DatasetManager(generate_guide=False)
    manager.add_query("latest", query_slug=LATEST_SLUG, description="latest finance snapshot")
    manager.add_query("snapshots", query_slug=SNAPSHOTS_SLUG, description="all finance snapshots")
    latest = await manager.materialize("latest")
    trend = await manager.materialize(
        "snapshots", fields=list(TREND_FIELDS), grouping=["snapshot_date"], ordering=["snapshot_date"]
    )
    if latest is None or len(latest) == 0:
        raise CheckError(f"DatasetManager returned no rows for {LATEST_SLUG}")
    return _expected_from_frames(latest, trend)


def evaluate(rows: dict[str, list[dict[str, Any]]], expected: dict[str, Any]) -> list[str]:
    """Compare the replayed lane answers with the DatasetManager expectations; one message per mismatch."""
    failures: list[str] = []
    for key, (column, value) in expected["kpis"].items():
        try:
            actual = rows[key][0][column]
        except (KeyError, IndexError, TypeError):
            failures.append(f"{key}: no '{column}' value")
            continue
        if not close(actual, value):
            failures.append(f"{key}: expected {value:.2f}, got {actual}")
    for key, column in GROUP_KEYS.items():
        want = expected["groups"][key]
        got = {label(row.get(column)): row for row in rows.get(key, [])}
        if set(got) != set(want):
            failures.append(f"{key}: expected groups {sorted(want)}, got {sorted(got)}")
            continue
        for name, values in want.items():
            for measure, value in values.items():
                if not close(got[name].get(measure), value):
                    failures.append(f"{key}[{name}].{measure}: expected {value:.2f}, got {got[name].get(measure)}")
    return failures


def print_values(rows: dict[str, list[dict[str, Any]]]) -> None:
    """Print the fetched values as a key | value table."""
    emit("key | value")
    emit("----|------")
    for key in KPI_KEYS:
        first = rows[key][0] if rows.get(key) else {}
        value = next(iter(first.values()), "(no data)") if first else "(no data)"
        emit(f"{key} | {value}")
    for key, column in GROUP_KEYS.items():
        emit(f"{key} | {len(rows.get(key, []))} groups")
        for row in rows.get(key, []):
            measures = ", ".join(f"{k}={v}" for k, v in row.items() if k != column)
            emit(f"{key} | {label(row.get(column)) or 'Unassigned'}: {measures}")


def assert_definition_only(envelope: dict[str, Any]) -> None:
    """The served envelope must ship no rows: the browser fetches them (no double execution)."""
    sources = envelope.get("metadata", {}).get("extensions", {}).get("parrot_data_sources", {})
    data_model = envelope.get("dataModel", {})
    baked = [key for key in sources if data_model.get(key, {}).get("rows")]
    stamped = [key for key, source in sources.items() if source.get("snapshot_at")]
    if baked or stamped:
        raise CheckError(f"envelope is not definition-only: rows in {baked}, snapshot_at in {stamped}")


async def check_grid(
    session: aiohttp.ClientSession, base_url: str, token: str, source: dict[str, Any], expected_total: int | None
) -> list[str]:
    """Exercise the grid's server paging: a page, stable ordering, the total, and a division filter."""
    failures: list[str] = []
    page, count = page_bodies(source, offset=0, limit=GRID_PAGE)
    rows = await post_query(session, base_url, token, source, page)
    counted = await post_query(session, base_url, token, source, count)
    total = int(counted[0]["total"]) if counted and "total" in counted[0] else -1
    emit(f"{GRID_KEY} | page 1: {len(rows)} rows, total {total}")
    if not rows:
        failures.append(f"{GRID_KEY}: the first page is empty")
    if not page.get("ordering"):
        failures.append(f"{GRID_KEY}: paging must send a stable ordering")
    if expected_total is not None and total != expected_total:
        failures.append(f"{GRID_KEY}: total {total} != DatasetManager row count {expected_total}")
    if total > GRID_PAGE:
        second_page, _ = page_bodies(source, offset=GRID_PAGE, limit=GRID_PAGE)
        second = await post_query(session, base_url, token, source, second_page)
        if rows and second and all(rows[-1].get(c) == second[0].get(c) for c in page["ordering"]):
            failures.append(f"{GRID_KEY}: page 2 repeats the last row of page 1 (unstable paging)")
    division = next((row.get("division") for row in rows if row.get("division")), None)
    if division:
        f_page, f_count = page_bodies(source, offset=0, limit=GRID_PAGE, filter_={"division": division})
        f_rows = await post_query(session, base_url, token, source, f_page)
        f_counted = await post_query(session, base_url, token, source, f_count)
        f_total = int(f_counted[0]["total"]) if f_counted and "total" in f_counted[0] else -1
        emit(f"{GRID_KEY} | filter division={division}: total {f_total}")
        if not 0 < f_total <= total:
            failures.append(f"{GRID_KEY}: filter division={division} gave total {f_total} (all: {total})")
        if any(row.get("division") != division for row in f_rows):
            failures.append(f"{GRID_KEY}: filtered page contains other divisions")
    else:
        failures.append(f"{GRID_KEY}: no division value to filter on")
    return failures


async def check(base_url: str, user: str, password: str, *, expect: bool = True, manager: Any | None = None) -> int:
    """Run the headless check; return 0 only if login, envelope shape, values and grid paging all pass."""
    try:
        expected = await expected_values(manager) if expect else None
        async with aiohttp.ClientSession() as session:
            token = await login(session, base_url, user, password)
            envelope = await fetch_dashboard(session, base_url, token)
            sources = envelope.get("metadata", {}).get("extensions", {}).get("parrot_data_sources", {})
            missing = [key for key in EXPECTED_KEYS if key not in sources]
            if missing:
                raise CheckError(f"dashboard envelope is missing sources: {', '.join(missing)}")
            assert_definition_only(envelope)
            rows: dict[str, list[dict[str, Any]]] = {}
            for key in EXPECTED_KEYS:
                if key == GRID_KEY:
                    continue
                rows[key] = await post_query(session, base_url, token, sources[key], lane_body(sources[key]))
            print_values(rows)
            failures = evaluate(rows, expected) if expected is not None else []
            expected_total = expected["grid_total"] if expected is not None else None
            failures += await check_grid(session, base_url, token, sources[GRID_KEY], expected_total)
    except (CheckError, aiohttp.ClientError) as exc:
        logger.error("check failed: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - DatasetManager/QuerySource failures are reported, never a traceback
        logger.error("check failed while computing expectations: %s", exc)
        return 1
    for failure in failures:
        logger.error("MISMATCH %s", failure)
    if failures:
        return 1
    emit("OK: all checks passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"example server (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--open", action="store_true", help="open the dashboard in the default browser")
    parser.add_argument("--check", action="store_true", help="run the headless check against the server")
    parser.add_argument("--no-expect", action="store_true", help="print values without DatasetManager expectations")
    parser.add_argument("--user", default=None, help="username (default: A2UI_USER_USERNAME, else admin)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.open and args.check:
        logger.error("--open and --check are mutually exclusive")
        return 1
    if not args.open and not args.check:
        logger.error("specify either --open or --check")
        return 1
    if args.open:
        open_dashboard(args.base_url)
        return 0
    user = args.user or env_setting("A2UI_USER_USERNAME") or "admin"
    password = os.environ.get("A2UI_DEMO_PASSWORD") or env_setting("A2UI_USER_PASSWORD")
    if not password:
        logger.error("set A2UI_USER_PASSWORD (env/<ENV>/.env) or A2UI_DEMO_PASSWORD")
        return 1
    return asyncio.run(check(args.base_url, user, password, expect=not args.no_expect))


if __name__ == "__main__":
    sys.exit(main())
