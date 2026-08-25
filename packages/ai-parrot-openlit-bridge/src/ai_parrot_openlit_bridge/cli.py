"""CLI entry point: ``parrot-openlit-check`` — validate an OTLP endpoint.

FEAT-462 — Unified Telemetry Bus.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ai_parrot_openlit_bridge.probe import validate_endpoint


def main() -> None:
    """Entry point for the ``parrot-openlit-check`` console script.

    Exits with code ``0`` when the endpoint is reachable, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="parrot-openlit-check",
        description="Validate an OTLP endpoint for OpenLIT compatibility.",
    )
    parser.add_argument("url", help="OTLP base URL (e.g. http://localhost:4318)")
    parser.add_argument("--timeout", type=float, default=5.0, help="Timeout in seconds")
    args = parser.parse_args()

    result = asyncio.run(validate_endpoint(args.url, timeout=args.timeout))
    if result.reachable:
        print(f"✅ Endpoint reachable: {args.url}")
        print(f"   Status: {result.status_code}")
        if result.collector_info:
            print(f"   Collector: {result.collector_info}")
        sys.exit(0)
    else:
        print(f"❌ Endpoint unreachable: {args.url}")
        print(f"   Error: {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
