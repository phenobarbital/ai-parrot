"""Workday homologation smoke test (FEAT-415, Module 7) — MAINTAINER-RUN ONLY.

This script exercises the flowtask → ai-parrot Workday homologation surface
against a REAL Workday implementation/sandbox tenant. It is NOT a unit test:
it is not named ``test_*``, it does not live under ``tests/``, and it is
NEVER wired into CI — CI is entirely mock-based (there is no Workday tenant
available to it). Run this by hand, on demand, when you need to verify the
ported surface (especially the TASK-2138 ``aiohttp`` rewrite of
``WorkdayRestClient``, which — unlike flowtask's ``httpx`` original — has
never been exercised against a live tenant) against reality.

What it exercises:
    1. ``WorkdayConfig(env="sandbox")`` resolution (TASK-2136).
    2. The SOAP endpoint host rewrite actually pointing ``WorkdayService``
       at the configured sandbox host (TASK-2137).
    3. A read via ``WorkdayService.fetch(...)``.
    4. A ``WorkdayRestClient.find_worker(...)`` +
       ``get_time_clock_events(...)`` round trip (TASK-2138).
    5. Optionally, a ``Put_Time_Clock_Events`` write followed by a REST
       read-back verification of the client-assigned event id — gated
       behind a SEPARATE, explicit confirmation (``--write``) on top of the
       script's own opt-in gate.

Credentials come from ``parrot.conf`` (the ``WORKDAY_*_IMPL`` sandbox
settings) exactly like any other ``WorkdayConfig(env="sandbox")`` caller —
this script NEVER hardcodes a credential. Configure the environment before
running (e.g. via ``.env`` / process env):

    WORKDAY_ENV=sandbox
    WORKDAY_CLIENT_ID_IMPL=...
    WORKDAY_CLIENT_SECRET_IMPL=...
    WORKDAY_REFRESH_TOKEN_IMPL=...
    WORKDAY_TOKEN_URL_IMPL=...

Usage::

    # Explicit opt-in is mandatory — running with no flags refuses:
    python examples/workday_homologation_smoke.py

    # Read-only smoke run:
    python examples/workday_homologation_smoke.py --confirm --worker-search "Alice"

    # Read-only + a write/read-back round trip (needs a SECOND, separate flag):
    python examples/workday_homologation_smoke.py --confirm --write \\
        --worker-search "Alice" --employee-id 123456

Requires the ``workday`` extra (TASK-2144):

    uv pip install -e 'packages/ai-parrot-tools[workday]'
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("workday_homologation_smoke")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI flags. Both opt-in gates default to False (refuse by default)."""
    parser = argparse.ArgumentParser(
        description=(
            "Maintainer-run-only smoke test for the Workday homologation "
            "surface (FEAT-415). Never run in CI."
        )
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Required opt-in. Without this flag the script refuses to run.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help=(
            "SEPARATE opt-in for the write + read-back round trip "
            "(Put_Time_Clock_Events). Ignored unless --confirm is also set."
        ),
    )
    parser.add_argument(
        "--worker-search",
        default=None,
        help="Free-text search term for WorkdayRestClient.find_worker(...).",
    )
    parser.add_argument(
        "--employee-id",
        default=None,
        help="Employee_ID used for the WorkdayService.fetch('get_workers', ...) read.",
    )
    return parser.parse_args(argv)


def _print_plan(args: argparse.Namespace) -> None:
    """Print exactly what this run is about to do before doing it."""
    print("Workday homologation smoke test — plan:")
    print("  1. Resolve WorkdayConfig(env='sandbox') and print the resolved env/host.")
    print("  2. WorkdayService.start() and verify the SOAP endpoint host rewrite.")
    print(
        "  3. WorkdayService.fetch('get_workers', "
        f"employee_id={args.employee_id!r}) — a read."
    )
    print(
        "  4. WorkdayRestClient.find_worker("
        f"{args.worker_search!r}) + get_time_clock_events(...) — a REST round trip."
    )
    if args.write:
        print(
            "  5. [--write] Put_Time_Clock_Events write, THEN a REST "
            "find_time_clock_event(...) read-back to verify it landed."
        )
    else:
        print("  5. [skipped] Pass --write to also exercise the write + read-back round trip.")
    print()


async def _run(args: argparse.Namespace) -> None:
    # Imported lazily so `--help` works without the `workday` extra installed.
    from parrot_tools.interfaces.workday.config import WorkdayConfig
    from parrot_tools.interfaces.workday.models.clock_event import ClockEvent
    from parrot_tools.interfaces.workday.rest import WorkdayRestClient
    from parrot_tools.interfaces.workday.service import WorkdayService

    config = WorkdayConfig(env="sandbox")
    logger.info(
        "Resolved env=%s is_sandbox=%s workday_url=%s",
        config.resolved_env,
        config.resolved_is_sandbox,
        config.resolved_workday_url,
    )
    if not config.resolved_is_sandbox:
        print(
            "REFUSING: config.resolved_is_sandbox is False. This script only "
            "runs against the sandbox/implementation tenant — check WORKDAY_ENV."
        )
        return

    # --- Step 2: SOAP service, endpoint host rewrite -----------------------
    service = WorkdayService(config=config)
    try:
        await service.start()  # explicit lifecycle — SOAPClient has no __aenter__/__aexit__
        bound = service.bind_service()
        options = getattr(bound, "_binding_options", None) or {}
        address = options.get("address", "<unknown>")
        logger.info("Bound SOAP endpoint address: %s", address)
        if config.resolved_workday_url and config.resolved_workday_url not in address:
            print(
                f"WARNING: bound address {address!r} does not appear to match "
                f"the configured sandbox host {config.resolved_workday_url!r}."
            )

        # --- Step 3: SOAP read ----------------------------------------------
        if args.employee_id:
            df = await service.fetch("get_workers", employee_id=args.employee_id)
            print(f"fetch('get_workers') -> {len(df)} row(s)")
        else:
            print("Skipping SOAP read (pass --employee-id to exercise it).")
    finally:
        await service.close()

    # --- Step 4: REST round trip --------------------------------------------
    rest_client = WorkdayRestClient(config=config)
    try:
        worker_wid = None
        if args.worker_search:
            workers = await rest_client.find_worker(args.worker_search)
            print(f"find_worker({args.worker_search!r}) -> {len(workers)} row(s)")
            if workers:
                worker_wid = workers[0].get("id")
                print(f"  first match: id={worker_wid!r} descriptor={workers[0].get('descriptor')!r}")

        if worker_wid:
            events = await rest_client.get_time_clock_events(worker_wid)
            print(f"get_time_clock_events({worker_wid!r}) -> {len(events)} event(s)")
        else:
            print("Skipping get_time_clock_events (no worker WID resolved).")

        # --- Step 5: write + read-back (SEPARATE opt-in) --------------------
        if args.write:
            if not worker_wid:
                print("Cannot run --write: no worker WID resolved from --worker-search.")
            else:
                confirm = input(
                    f"About to Put_Time_Clock_Events for worker {worker_wid!r} "
                    "against the SANDBOX tenant. Type 'yes' to proceed: "
                )
                if confirm.strip().lower() != "yes":
                    print("Write cancelled (confirmation not given).")
                else:
                    import datetime as _dt
                    import uuid as _uuid

                    event_id = str(_uuid.uuid4())
                    event = ClockEvent(
                        employee_id=args.employee_id or worker_wid,
                        event_datetime=_dt.datetime.now(_dt.UTC),
                        clock_event_type="In",
                        time_clock_event_id=event_id,
                    )
                    write_service = WorkdayService(config=config)
                    try:
                        await write_service.start()
                        await write_service.put_time_clock_events([event])
                        print(f"Put_Time_Clock_Events submitted (client id={event_id!r}).")
                    finally:
                        await write_service.close()

                    found = await rest_client.find_time_clock_event(worker_wid, event_id)
                    if found:
                        print(f"Read-back verified: {found}")
                    else:
                        print(
                            "Read-back did NOT find the event yet — Workday's REST "
                            "index can lag ~1s; re-run find_time_clock_event manually."
                        )
    finally:
        await rest_client.close()  # never leak the aiohttp session


def main(argv: list[str] | None = None) -> int:
    """Entry point. Refuses to run anything without explicit --confirm opt-in."""
    args = _parse_args(argv)

    if not args.confirm:
        print(
            "REFUSING to run: this script talks to a real Workday tenant.\n"
            "Pass --confirm to opt in (and --write for the write + read-back round trip).\n"
            "Run with --help for the full flag list."
        )
        return 1

    _print_plan(args)
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
