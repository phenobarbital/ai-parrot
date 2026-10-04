"""FEAT-610 — open the dashboard or run a headless check against a running example server.

Run: ENV=prod python examples/a2ui/client.py --check  (A2UI_USER_USERNAME / A2UI_USER_PASSWORD from env/prod/.env)
     python examples/a2ui/client.py --open

``--check`` logs in, fetches the dashboard envelope, replays exactly the requests the browser lane sends (each
query-slug source's own conditions, ``querylimit`` capped at 5000 — derived views are computed locally from their
parent's rows with the transform DSL, exactly like the lane), prints the values and ASSERTS them against the spec's
verified map (AC7). It also exercises the grid's server paging (page, stable ordering, column filter, total). Exit 0
only when every check passes; any failure (login, 404, wrong value, missing source) exits 1. ``--no-expect`` prints
without asserting values, for data that has legitimately drifted since the map was verified.
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

# Verified against production on 2026-09-28 (spec §2). KPIs count people; the pie counts diplomas. The four KPIs now
# come from the single dashboard source `kpis`; `by_country` / `by_licensee` are derived views of the `geo` source
# (DSL group_by, which drops a NULL group key — the old server-side `grouping` kept it as one "Unassigned" bucket, so
# the group counts are re-verified with `--no-expect` after this change).
KPI_SOURCE = "kpis"
EXPECTED_KPIS: dict[str, tuple[str, int]] = {
    "kpi_total": ("total", 17572),
    "kpi_studio": ("studio", 9191),
    "kpi_mat": ("mat", 6245),
    "kpi_multi": ("multi_graduates", 2884),
}
EXPECTED_GROUPS: dict[str, int] = {"by_country": 95, "by_licensee": 23}
EXPECTED_SLICES: dict[str, int] = {"Pilates Studio": 9204, "Pilates Mat": 6247, "Rehab": 3300, "Reformer": 2048}
EXPECTED_KEYS = [KPI_SOURCE, "geo", *EXPECTED_GROUPS, "by_course", GRID_KEY]


class CheckError(RuntimeError):
    """A request failed in a way the check must not paper over (login, 404, non-200, unusable payload)."""


def emit(line: str = "") -> None:
    """Write one line of CLI output."""
    sys.stdout.write(line + "\n")


def query_url(base_url: str, slug: str, tenant: str | None, is_multiquery: bool = False) -> str:
    """Build the QuerySource URL with the same rule as linked.js.

    ``tenant`` → ``/api/v1/{tenant}/queries/{slug}``; ``is_multiquery`` → ``/api/v3/queries/{slug}`` (MultiQS, the
    only HTTP lane that expands a pipeline); otherwise the plain ``QS()`` route ``/api/v2/services/queries/{slug}``.
    """
    base = base_url.rstrip("/")
    if tenant:
        return f"{base}/api/v1/{tenant}/queries/{slug}"
    if is_multiquery:
        return f"{base}/api/v3/queries/{slug}"
    return f"{base}/api/v2/services/queries/{slug}"


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
    """POST one query for ``source``; a 404 or any other non-200/204 is a hard failure, never an empty frame."""
    url = query_url(base_url, source["slug"], source.get("tenant"), bool(source.get("is_multiquery")))
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with session.post(url, json=body, headers=headers) as resp:
        if resp.status == 404:
            raise CheckError(f"source '{source['slug']}' is unavailable (HTTP 404)")
        if resp.status == 204:  # QuerySource "Empty Result": zero rows, no body
            return []
        if resp.status != 200:
            raise CheckError(f"source '{source['slug']}' failed: HTTP {resp.status}")
        return select_frame(await resp.json(), source)


def derive_rows(source: dict[str, Any], rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Compute a derived view from its parent's fetched rows with the reference DSL executor (what the lane does)."""
    from parrot.outputs.a2ui.linked.dsl import apply_transform, frame_from_records, frame_to_records
    from parrot.outputs.a2ui.linked.models import TransformSpec

    parent = source["from"]
    if parent not in rows:
        raise CheckError(f"derived source depends on '{parent}', which was not fetched")
    frames = {key: frame_from_records(value) for key, value in rows.items()}
    return frame_to_records(
        apply_transform(frames[parent], TransformSpec.model_validate(source["transform"]), frames=frames)
    )


def evaluate(rows: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Compare fetched rows with the spec's verified map (AC7); return one message per mismatch."""
    failures: list[str] = []
    kpi_rows = rows.get(KPI_SOURCE) or []
    for key, (column, expected) in EXPECTED_KPIS.items():
        try:
            actual = int(kpi_rows[0][column])
        except (KeyError, IndexError, TypeError, ValueError):
            failures.append(f"{key}: no '{column}' value in source '{KPI_SOURCE}'")
            continue
        if actual != expected:
            failures.append(f"{key}: expected {expected}, got {actual}")
    for key, expected_groups in EXPECTED_GROUPS.items():
        if len(rows.get(key, [])) != expected_groups:
            failures.append(f"{key}: expected {expected_groups} groups, got {len(rows.get(key, []))}")
    # The derived views must add up to the shared KPI: the geo matrix and the KPI query count the same people.
    geo_total = sum(int(row.get("graduates") or 0) for row in rows.get("geo", []))
    if kpi_rows and geo_total != int(kpi_rows[0].get("total") or -1):
        failures.append(f"geo: sum(graduates) {geo_total} != kpis.total {kpi_rows[0].get('total')}")
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
        value = rows[KPI_SOURCE][0].get(column) if rows.get(KPI_SOURCE) else "(no data)"
        emit(f"{key} | {value}")
    emit(f"geo | {len(rows.get('geo', []))} country × licensee rows (one fetch feeds by_country and by_licensee)")
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
            for key in EXPECTED_KEYS:  # query-slug sources first (one request each), then the derived views
                if key == GRID_KEY or sources[key].get("kind") == "derived":
                    continue
                rows[key] = await post_query(session, base_url, token, sources[key], lane_body(sources[key]))
            for key in EXPECTED_KEYS:
                if sources[key].get("kind") == "derived":
                    rows[key] = derive_rows(sources[key], rows)
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


def env_setting(name: str) -> str | None:
    """Return ``name`` from the process environment, else from navconfig (``env/<ENV>/.env``, e.g. ENV=prod)."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        from navconfig import config
    except ImportError:
        return None
    return config.get(name) or None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"example server (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--open", action="store_true", help="open the dashboard in the default browser")
    parser.add_argument("--check", action="store_true", help="run the headless check against the server")
    parser.add_argument("--no-expect", action="store_true", help="print values without asserting the verified map")
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
