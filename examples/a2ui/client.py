"""FEAT-610 — open the dashboard or run a headless check against a running example server.

Run: A2UI_DEMO_PASSWORD=... python examples/a2ui/client.py --check --user admin
     python examples/a2ui/client.py --open

``--check`` logs in, fetches the dashboard envelope, replays exactly the requests the browser lane sends (each source's
own conditions, ``querylimit`` capped at 5000), prints the values and ASSERTS them against the spec's verified map
(AC7). It also exercises the grid's server paging (page, stable ordering, column filter, total). Exit 0 only when every
check passes; any failure (login, 404, wrong value, missing source) exits 1. ``--no-expect`` prints without asserting
values, for data that has legitimately drifted since the map was verified.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import webbrowser
from typing import Any

import aiohttp

logger = logging.getLogger("a2ui.client")

DEFAULT_BASE_URL = "http://localhost:5000"
MAX_FETCH_ROWS = 5000
GRID_KEY = "graduates"
GRID_PAGE = 20

# Verified against production on 2026-09-28 (spec §2). KPIs count people; the pie counts diplomas.
EXPECTED_KPIS: dict[str, tuple[str, int]] = {
    "kpi_total": ("total", 17572),
    "kpi_studio": ("total", 9191),
    "kpi_mat": ("total", 6245),
    "kpi_multi": ("multi_graduates", 2884),
}
EXPECTED_GROUPS: dict[str, int] = {"by_country": 95, "by_licensee": 23}
EXPECTED_SLICES: dict[str, int] = {"Pilates Studio": 9204, "Pilates Mat": 6247, "Rehab": 3300, "Reformer": 2048}
EXPECTED_KEYS = [*EXPECTED_KPIS, *EXPECTED_GROUPS, "by_course", GRID_KEY]


class CheckError(RuntimeError):
    """A request failed in a way the check must not paper over (login, 404, non-200, unusable payload)."""


def emit(line: str = "") -> None:
    """Write one line of CLI output."""
    sys.stdout.write(line + "\n")


def query_url(base_url: str, slug: str, tenant: str | None) -> str:
    """Build the QuerySource URL with the same rule as linked.js (v3 without a tenant, v1 with one)."""
    base = base_url.rstrip("/")
    return f"{base}/api/v1/{tenant}/queries/{slug}" if tenant else f"{base}/api/v3/queries/{slug}"


async def login(session: aiohttp.ClientSession, base_url: str, user: str, password: str) -> str:
    """Login the same way the browser does (POST JSON) and return the bearer token."""
    async with session.post(
        f"{base_url}/api/v1/login",
        json={"username": user, "password": password},
        headers={"X-Auth-Method": "BasicAuth"},
    ) as resp:
        if resp.status != 200:
            raise CheckError(f"login failed: HTTP {resp.status}")
        data = await resp.json()
    token = data.get("token")
    if not token:
        raise CheckError("login returned no token")
    return str(token)


async def fetch_dashboard(session: aiohttp.ClientSession, base_url: str, token: str) -> dict[str, Any]:
    """Fetch the dashboard envelope."""
    async with session.get(f"{base_url}/api/a2ui/dashboard", headers={"Authorization": f"Bearer {token}"}) as resp:
        if resp.status != 200:
            raise CheckError(f"dashboard fetch failed: HTTP {resp.status}")
        return await resp.json()


def select_frame(payload: Any, source: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise a QuerySource payload to one row list (same rule as linked.js ``selectFrame``)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        multi_output = source.get("multi_output")
        if multi_output and multi_output in payload:
            selected = payload[multi_output]
        elif "result" in payload:
            selected = payload["result"]
        elif len(payload) == 1:
            selected = next(iter(payload.values()))
        else:
            selected = []
        return selected if isinstance(selected, list) else []
    return []


def lane_body(source: dict[str, Any]) -> dict[str, Any]:
    """The body the lane sends for a source: its own derived conditions plus the capped ``querylimit``."""
    request = source.get("request") or {}
    limit = request.get("limit")
    return {**source.get("conditions", {}), "querylimit": min(limit if limit else MAX_FETCH_ROWS, MAX_FETCH_ROWS)}


def page_bodies(
    source: dict[str, Any], *, offset: int, limit: int, filter_: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The (page, count) bodies ``fetchPage`` sends: stable ordering, ``_offset``, merged column filter, count(*)."""
    base = dict(source.get("conditions", {}))
    merged = {**(base.get("filter") or {}), **{k: v for k, v in (filter_ or {}).items() if v not in ("", None)}}
    page = {**base, "_offset": offset, "querylimit": limit}
    count = {k: v for k, v in base.items() if k not in {"fields", "ordering", "grouping", "_offset", "limit"}}
    count["fields"] = ["count(*) as total"]
    count["querylimit"] = 1
    for body in (page, count):
        if merged:
            body["filter"] = dict(merged)
        else:
            body.pop("filter", None)
    return page, count


async def post_query(
    session: aiohttp.ClientSession, base_url: str, token: str, source: dict[str, Any], body: dict[str, Any]
) -> list[dict[str, Any]]:
    """POST one query for ``source``; a 404 or any non-200 is a hard failure, never an empty frame."""
    url = query_url(base_url, source["slug"], source.get("tenant"))
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with session.post(url, json=body, headers=headers) as resp:
        if resp.status == 404:
            raise CheckError(f"source '{source['slug']}' is unavailable (HTTP 404)")
        if resp.status != 200:
            raise CheckError(f"source '{source['slug']}' failed: HTTP {resp.status}")
        return select_frame(await resp.json(), source)


def evaluate(rows: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Compare fetched rows with the spec's verified map (AC7); return one message per mismatch."""
    failures: list[str] = []
    for key, (column, expected) in EXPECTED_KPIS.items():
        try:
            actual = int(rows[key][0][column])
        except (KeyError, IndexError, TypeError, ValueError):
            failures.append(f"{key}: no '{column}' value")
            continue
        if actual != expected:
            failures.append(f"{key}: expected {expected}, got {actual}")
    for key, expected_groups in EXPECTED_GROUPS.items():
        if len(rows.get(key, [])) != expected_groups:
            failures.append(f"{key}: expected {expected_groups} groups, got {len(rows.get(key, []))}")
    slices: dict[str, int] = {}
    for row in rows.get("by_course", []):
        try:
            slices[str(row.get("course"))] = int(row["graduates"])
        except (KeyError, TypeError, ValueError):
            continue
    if slices != EXPECTED_SLICES:
        failures.append(f"by_course: expected {EXPECTED_SLICES}, got {slices}")
    return failures


def print_values(rows: dict[str, list[dict[str, Any]]]) -> None:
    """Print the AC7 values as a key | value table."""
    emit("key | value")
    emit("----|------")
    for key, (column, _) in EXPECTED_KPIS.items():
        value = rows[key][0].get(column) if rows.get(key) else "(no data)"
        emit(f"{key} | {value}")
    for key in EXPECTED_GROUPS:
        emit(f"{key} | {len(rows.get(key, []))} groups")
    for row in rows.get("by_course", []):
        emit(f"by_course | {row.get('course') or 'Unassigned'} = {row.get('graduates')}")


async def check_grid(
    session: aiohttp.ClientSession, base_url: str, token: str, source: dict[str, Any], expected_total: int | None
) -> list[str]:
    """Exercise the grid's server paging: a full page, stable ordering, the total, and a column filter."""
    failures: list[str] = []
    page, count = page_bodies(source, offset=0, limit=GRID_PAGE)
    rows = await post_query(session, base_url, token, source, page)
    counted = await post_query(session, base_url, token, source, count)
    total = int(counted[0]["total"]) if counted and "total" in counted[0] else -1
    emit(f"{GRID_KEY} | page 1: {len(rows)} rows, total {total}")
    if len(rows) != GRID_PAGE:
        failures.append(f"{GRID_KEY}: expected a page of {GRID_PAGE} rows, got {len(rows)}")
    if not page.get("ordering"):
        failures.append(f"{GRID_KEY}: paging must send a stable ordering")
    if expected_total is not None and total != expected_total:
        failures.append(f"{GRID_KEY}: total {total} != kpi_total {expected_total}")
    second_page, _ = page_bodies(source, offset=GRID_PAGE, limit=GRID_PAGE)
    second = await post_query(session, base_url, token, source, second_page)
    ordering = (page.get("ordering") or [None])[0]
    if ordering and rows and second and rows[-1].get(ordering) == second[0].get(ordering):
        failures.append(f"{GRID_KEY}: page 2 repeats the last row of page 1 (unstable paging)")
    country = next((row.get("country") for row in rows if row.get("country")), None)
    if country:
        f_page, f_count = page_bodies(source, offset=0, limit=GRID_PAGE, filter_={"country": country})
        f_rows = await post_query(session, base_url, token, source, f_page)
        f_counted = await post_query(session, base_url, token, source, f_count)
        f_total = int(f_counted[0]["total"]) if f_counted and "total" in f_counted[0] else -1
        emit(f"{GRID_KEY} | filter country={country}: total {f_total}")
        if not 0 < f_total < total:
            failures.append(f"{GRID_KEY}: filter country={country} gave total {f_total} (all: {total})")
        if any(row.get("country") != country for row in f_rows):
            failures.append(f"{GRID_KEY}: filtered page contains other countries")
    else:
        failures.append(f"{GRID_KEY}: no country value to filter on")
    return failures


async def check(base_url: str, user: str, password: str, *, expect: bool = True) -> int:
    """Run the headless check; return 0 only if login, fetches, values and grid paging all pass."""
    try:
        async with aiohttp.ClientSession() as session:
            token = await login(session, base_url, user, password)
            envelope = await fetch_dashboard(session, base_url, token)
            sources = envelope.get("metadata", {}).get("extensions", {}).get("parrot_data_sources", {})
            missing = [key for key in EXPECTED_KEYS if key not in sources]
            if missing:
                raise CheckError(f"dashboard envelope is missing sources: {', '.join(missing)}")
            rows: dict[str, list[dict[str, Any]]] = {}
            for key in EXPECTED_KEYS:
                if key == GRID_KEY:
                    continue
                rows[key] = await post_query(session, base_url, token, sources[key], lane_body(sources[key]))
            print_values(rows)
            failures = evaluate(rows) if expect else []
            expected_total = EXPECTED_KPIS["kpi_total"][1] if expect else None
            failures += await check_grid(session, base_url, token, sources[GRID_KEY], expected_total)
    except (CheckError, aiohttp.ClientError) as exc:
        logger.error("check failed: %s", exc)
        return 1
    for failure in failures:
        logger.error("MISMATCH %s", failure)
    if failures:
        return 1
    emit("OK: all checks passed")
    return 0


def open_dashboard(base_url: str) -> None:
    """Open the dashboard in the default browser."""
    url = f"{base_url}/"
    logger.info("Opening %s", url)
    webbrowser.open(url)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"example server (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--open", action="store_true", help="open the dashboard in the default browser")
    parser.add_argument("--check", action="store_true", help="run the headless check against the server")
    parser.add_argument("--no-expect", action="store_true", help="print values without asserting the verified map")
    parser.add_argument("--user", default="admin", help="username (default: admin)")
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
    password = os.environ.get("A2UI_DEMO_PASSWORD")
    if not password:
        logger.error("A2UI_DEMO_PASSWORD environment variable not set")
        return 1
    return asyncio.run(check(args.base_url, args.user, password, expect=not args.no_expect))


if __name__ == "__main__":
    sys.exit(main())
