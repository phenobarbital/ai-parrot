"""FEAT-610 — open the dashboard or run a headless smoke check against a running example server.

Run: python examples/a2ui/client.py --check --user admin
     python examples/a2ui/client.py --open
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


def query_url(base_url: str, slug: str, tenant: str | None) -> str:
    """Build the QuerySource URL following the same rule as linked.js (v3 / v1 tenant)."""
    base = base_url.rstrip("/")
    s = slug  # already encoded by caller
    return f"{base}/api/v1/{tenant}/queries/{s}" if tenant else f"{base}/api/v3/queries/{s}"


async def login(session: aiohttp.ClientSession, base_url: str, user: str, password: str) -> str:
    """Login and return the bearer token."""
    login_url = f"{base_url}/api/v1/login"
    auth = aiohttp.BasicAuth(user, password)
    headers = {"X-Auth-Method": "BasicAuth"}
    async with session.get(login_url, auth=auth, headers=headers) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Login failed: {resp.status} {await resp.text()}")
        data = await resp.json()
        token = data.get("token") or data.get("ai_parrot_token")
        if not token:
            raise RuntimeError(f"No token in login response: {data}")
        return token


async def fetch_dashboard(session: aiohttp.ClientSession, base_url: str, token: str) -> dict[str, Any]:
    """Fetch the dashboard envelope."""
    url = f"{base_url}/api/a2ui/dashboard"
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(url, headers=headers) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Dashboard fetch failed: {resp.status} {await resp.text()}")
        return await resp.json()


async def fetch_source(
    session: aiohttp.ClientSession,
    base_url: str,
    token: str,
    slug: str,
    tenant: str | None,
    conditions: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch a single source using the same route rule as linked.js."""
    url = query_url(base_url, slug, tenant)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {**conditions, "querylimit": 100}
    async with session.post(url, json=body, headers=headers) as resp:
        if resp.status == 404:
            logger.warning("Source %s not found", slug)
            return []
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"Source {slug} fetch failed: {resp.status} {text}")
        payload = await resp.json()
        # Normalize payload (same logic as linked.js selectFrame)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if "result" in payload:
                result = payload["result"]
                return result if isinstance(result, list) else []
            keys = list(payload.keys())
            if len(keys) == 1:
                result = payload[keys[0]]
                return result if isinstance(result, list) else []
        return []


def print_value_table(results: list[dict[str, Any]], key: str) -> None:
    """Print a key | value table for the results."""
    if not results:
        print(f"{key} | (no data)")
        return
    # For grouped results (e.g., by course), print first few rows
    for row in results[:10]:
        values = " | ".join(str(v) for v in row.values())
        print(f"{key} | {values}")
    if len(results) > 10:
        print(f"... ({len(results) - 10} more rows)")


async def check(base_url: str, user: str, password: str) -> int:
    """Run the headless smoke check: login, fetch dashboard, re-fetch each source, print values."""
    async with aiohttp.ClientSession() as session:
        try:
            token = await login(session, base_url, user, password)
        except Exception as e:
            logger.error("Login failed: %s", e)
            return 1

        try:
            dashboard = await fetch_dashboard(session, base_url, token)
        except Exception as e:
            logger.error("Dashboard fetch failed: %s", e)
            return 1

        sources = dashboard.get("metadata", {}).get("extensions", {}).get("parrot_data_sources", {})
        if not sources:
            logger.error("No parrot_data_sources in dashboard")
            return 1

        print("key | value")
        print("----|-------")

        for key, src in sources.items():
            slug = src.get("slug")
            tenant = src.get("tenant")
            conditions = src.get("conditions", {})
            request = src.get("request", {})
            # Apply any filter from the request
            if "filter" in request:
                conditions = {**conditions, **request["filter"]}

            try:
                rows = await fetch_source(session, base_url, token, slug, tenant, conditions)
                print_value_table(rows, key)
            except Exception as e:
                logger.error("Source %s check failed: %s", key, e)
                return 1

        return 0


def open_dashboard(base_url: str) -> None:
    """Open the dashboard in the default browser."""
    url = f"{base_url}/"
    logger.info("Opening %s", url)
    webbrowser.open(url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of the example server (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the dashboard in the default browser",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run a headless smoke check against the server",
    )
    parser.add_argument(
        "--user",
        default="admin",
        help="Username for authentication (default: admin)",
    )
    args = parser.parse_args(argv)

    password = os.environ.get("A2UI_DEMO_PASSWORD")
    if not password:
        print("Error: A2UI_DEMO_PASSWORD environment variable not set", file=sys.stderr)
        return 1

    if args.open and args.check:
        print("Error: --open and --check are mutually exclusive", file=sys.stderr)
        return 1

    if not args.open and not args.check:
        print("Error: specify either --open or --check", file=sys.stderr)
        return 1

    if args.open:
        open_dashboard(args.base_url)
        return 0

    return asyncio.run(check(args.base_url, args.user, password))


if __name__ == "__main__":
    sys.exit(main())
