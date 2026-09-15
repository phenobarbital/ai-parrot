"""Fake headless child for tests: prints the handshake, serves the library routes with a stub runner, exits.

Usage (spawned by tests): python fake_child.py --brief B --yes --headless --run-id R --command-socket S
Env: PARROT_DEVLOOP_COMMAND_TOKEN (required in Authorization header), FAKE_CHILD_EXIT (default 0),
FAKE_CHILD_NO_HANDSHAKE=1 (exit 3 without printing), FAKE_CHILD_SPAM=1 (write 1 MiB to stdout/stderr after handshake).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from aiohttp import web

from parrot.flows.dev_loop.commands import register_command_routes  # verified: commands.py:208
from parrot.flows.dev_loop.session_state import GateAlreadyResolvedError  # verified: session_state.py:736


class _Envelope:
    """Minimal stand-in for ActionEnvelope — only model_dump is used."""

    def model_dump(self, mode: str = "json") -> dict:
        return {"ok": True}


class _StubRunner:
    """Enough of DevLoopRunner for resolve_gate_handler / cancel_run_handler (commands.py:77,163)."""

    def __init__(self) -> None:
        self.resolved: list[tuple] = []
        self._resolved_gate_ids: set[str] = set()
        self.cancelled = asyncio.Event()

    async def resolve_gate(self, run_id, gate_id, resolution, resolved_by, comment="", origin=None, answers=None):
        if gate_id in self._resolved_gate_ids:
            raise GateAlreadyResolvedError(f"gate {gate_id} on run {run_id} already resolved")
        if gate_id.startswith("oq-") and not answers:
            raise ValueError(f"gate {gate_id} requires at least one answer")
        self._resolved_gate_ids.add(gate_id)
        self.resolved.append((run_id, gate_id, resolution, resolved_by, comment, answers))
        return _Envelope()

    def get_host(self, run_id):
        """No real SessionHost — the 409 branch degrades to an 'unknown' gate summary."""
        return None

    async def cancel_run(self, run_id, requested_by):
        self.cancelled.set()
        return _Envelope()


@web.middleware
async def _auth(request, handler):
    if request.headers.get("Authorization") != f"Bearer {os.environ.get('PARROT_DEVLOOP_COMMAND_TOKEN', '')}":
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def main(ns: argparse.Namespace) -> int:
    if os.environ.get("FAKE_CHILD_NO_HANDSHAKE"):
        print("boom", file=sys.stderr)
        return 3

    app = web.Application(middlewares=[_auth])
    runner = _StubRunner()
    register_command_routes(app, runner)
    app_runner = web.AppRunner(app)
    await app_runner.setup()
    site = web.UnixSite(app_runner, ns.command_socket)
    await site.start()

    print(
        json.dumps(
            {
                "event": "ready",
                "run_id": ns.run_id,
                "command_endpoint": f"unix://{ns.command_socket}",
                "kind": "bug",
                "pid": os.getpid(),
            }
        ),
        flush=True,
    )

    if os.environ.get("FAKE_CHILD_SPAM"):
        sys.stdout.write("x" * (1024 * 1024) + "\n")
        sys.stdout.flush()
        sys.stderr.write("y" * (1024 * 1024) + "\n")
        sys.stderr.flush()

    try:
        await asyncio.wait_for(runner.cancelled.wait(), timeout=30)
        exit_code = 2
    except asyncio.TimeoutError:
        exit_code = int(os.environ.get("FAKE_CHILD_EXIT", 0))
    finally:
        await app_runner.cleanup()
        if os.path.exists(ns.command_socket):
            os.remove(ns.command_socket)
    return exit_code


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--brief")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--run-id")
    p.add_argument("--command-socket")
    sys.exit(asyncio.run(main(p.parse_args())))
