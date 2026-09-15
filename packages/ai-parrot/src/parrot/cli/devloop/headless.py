"""Headless child mode for ``parrot devloop run`` (FEAT-555 Module 1).

Non-interactive child process driven by the Slack/dev-loop integration
(``parrot.integrations.devloop``, out of this module's scope): load a
brief, preflight for its topology, build the matching runtime, mount the
existing gate-resolve/cancel REST routes on a private Unix socket or
127.0.0.1 TCP port behind a per-run bearer token, print exactly one JSON
handshake line on stdout, run the flow to completion, and exit with a
status code the parent can act on.

All logging is routed to stderr — stdout carries the single
:class:`HeadlessHandshake` line and nothing else.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from enum import IntEnum
from typing import Any, Callable, Literal, Optional

from aiohttp import web
from pydantic import BaseModel

from parrot.flows.dev_loop.commands import cancel_run_handler, resolve_gate_handler  # verified: commands.py:163,77

logger = logging.getLogger(__name__)


class HeadlessHandshake(BaseModel):
    """Single JSON line printed to stdout once the command endpoint is listening."""

    event: Literal["ready"] = "ready"
    run_id: str
    command_endpoint: str
    kind: Literal["bug", "enhancement", "new_feature", "feature"]
    pid: int


class HeadlessExit(IntEnum):
    """Process exit codes: 0 completed, 1 failed, 2 cancelled, 3 bootstrap/preflight failure."""

    COMPLETED = 0
    FAILED = 1
    CANCELLED = 2
    BOOTSTRAP_FAILED = 3


def _bearer_middleware(token: str) -> Any:
    """Build an aiohttp middleware requiring ``Authorization: Bearer <token>``.

    Args:
        token: The per-run bearer capability minted by the parent.

    Returns:
        An aiohttp middleware rejecting any request lacking the exact
        bearer token with a 401.
    """

    @web.middleware
    async def middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.headers.get("Authorization", "") != f"Bearer {token}":
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    return middleware


async def mount_command_endpoint(
    runner: Any,
    *,
    socket_path: Optional[str],
    port: Optional[int],
    token: str,
    on_cancelled: Callable[[], None],
) -> tuple[web.AppRunner, str]:
    """Mount the gate-resolve / cancel routes on a Unix socket or TCP port.

    Registers the routes by hand (rather than calling
    :func:`~parrot.flows.dev_loop.commands.register_command_routes`
    directly) so the cancel route can be wrapped: a 200 response fires
    ``on_cancelled`` (design research S7 — ``DevLoopRunner.cancel_run``
    only records the ``run/cancelled`` action; it does not stop the flow).
    Every request in both modes must carry the per-run bearer token (S4).

    Args:
        runner: The ``DevLoopRunner``/``DevFlowRunner`` backing the routes.
        socket_path: Unix socket path. Takes precedence over ``port``.
        port: 127.0.0.1 port (``0`` = ephemeral) used when ``socket_path``
            is ``None``.
        token: The bearer token every request must present.
        on_cancelled: Callback fired once the cancel route succeeds.

    Returns:
        A ``(app_runner, command_endpoint)`` tuple, where
        ``command_endpoint`` is ``"unix://<path>"`` or
        ``"http://127.0.0.1:<port>"``.
    """

    async def _cancel_then_stop(request: web.Request) -> web.Response:
        resp = await cancel_run_handler(request)
        if resp.status == 200:
            on_cancelled()
        return resp

    app = web.Application(middlewares=[_bearer_middleware(token)])
    # What register_command_routes does (commands.py:208-224) — done by hand
    # here so the cancel route can be wrapped above.
    app["dev_loop_runner"] = runner
    app.router.add_post("/runs/{run_id}/gates/{gate_id}/resolve", resolve_gate_handler)
    app.router.add_post("/runs/{run_id}/cancel", _cancel_then_stop)

    app_runner = web.AppRunner(app)
    await app_runner.setup()

    if socket_path:
        site: web.BaseSite = web.UnixSite(app_runner, socket_path)
        await site.start()
        os.chmod(socket_path, 0o600)
        return app_runner, f"unix://{socket_path}"

    tcp_site = web.TCPSite(app_runner, "127.0.0.1", port or 0)
    await tcp_site.start()
    return app_runner, f"http://127.0.0.1:{tcp_site.port}"


async def run_headless(
    *,
    brief_path: str,
    run_id: Optional[str],
    command_socket: Optional[str],
    command_port: Optional[int],
    cancel_grace: float = 30.0,
) -> int:
    """Run one brief headless, end to end.

    Loads the brief, preflights + builds the matching runtime (dev-loop
    for ``WorkBrief``/``FeatureBrief``, dev-flow for ``DevRequestBrief``),
    mounts the command endpoint, prints the handshake, runs the flow as a
    cancellable task, and maps the outcome to a :class:`HeadlessExit` code.
    Never raises.

    Args:
        brief_path: Path to the YAML/JSON brief file.
        run_id: Externally minted run id, or ``None`` to generate one.
        command_socket: Unix socket path for the command endpoint.
        command_port: 127.0.0.1 port (``0`` = ephemeral) when
            ``command_socket`` is not given.
        cancel_grace: Seconds to await the run task's unwind after a
            cancel before returning ``CANCELLED`` anyway.

    Returns:
        The process exit code (see :class:`HeadlessExit`).
    """
    import uuid  # noqa: PLC0415

    from parrot.cli.devloop.bootstrap import (  # noqa: PLC0415
        build_dev_flow_runtime,
        build_runtime,
        load_headless_brief,
    )
    from parrot.flows.dev_flow.models import DevRequestBrief  # noqa: PLC0415

    # `force=True` is required here: by this point `parrot.cli.devloop.bootstrap`'s
    # own imports (navconfig/`parrot.conf`) have already installed a root
    # logging handler, so a plain `basicConfig()` would silently no-op (a
    # bare `basicConfig` call is a documented no-op once any handler exists)
    # and every subsequent `logger.*` call — including this module's own
    # `logger.exception(...)` on failure — would keep leaking onto stdout
    # instead of stderr (code review finding, FEAT-555 completion pass).
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)  # stdout is reserved for the handshake

    token = os.environ.get("PARROT_DEVLOOP_COMMAND_TOKEN", "")
    if not token:
        logger.error("PARROT_DEVLOOP_COMMAND_TOKEN is required in --headless mode")
        return int(HeadlessExit.BOOTSTRAP_FAILED)

    run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    app_runner: Optional[web.AppRunner] = None
    cancelled = asyncio.Event()

    try:
        brief = load_headless_brief(brief_path)
        runtime = await (build_dev_flow_runtime() if isinstance(brief, DevRequestBrief) else build_runtime())
        runner = runtime.runner

        app_runner, endpoint = await mount_command_endpoint(
            runner,
            socket_path=command_socket,
            port=command_port,
            token=token,
            on_cancelled=cancelled.set,
        )

        handshake = HeadlessHandshake(
            run_id=run_id,
            command_endpoint=endpoint,
            kind=brief.kind,
            pid=os.getpid(),
        )
        sys.stdout.write(handshake.model_dump_json() + "\n")
        sys.stdout.flush()

        run_task = asyncio.create_task(runner.run(brief, run_id=run_id), name=f"devloop-run-{run_id}")
        cancel_waiter = asyncio.create_task(cancelled.wait())
        done, _pending = await asyncio.wait({run_task, cancel_waiter}, return_when=asyncio.FIRST_COMPLETED)

        if cancel_waiter in done and run_task not in done:
            run_task.cancel()
            try:
                await asyncio.wait_for(run_task, timeout=cancel_grace)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            return int(HeadlessExit.CANCELLED)

        cancel_waiter.cancel()
        result = run_task.result()  # raises if the run task itself raised
        from parrot.bots.flows.core.types import FlowStatus  # noqa: PLC0415

        if getattr(result, "status", None) == FlowStatus.COMPLETED:
            return int(HeadlessExit.COMPLETED)
        return int(HeadlessExit.FAILED)
    except (SystemExit, FileNotFoundError, ValueError) as exc:
        logger.error("headless bootstrap failed: %s", exc)
        return int(HeadlessExit.BOOTSTRAP_FAILED)
    except Exception:  # noqa: BLE001 - the run itself failed
        logger.exception("headless run %s failed", run_id)
        return int(HeadlessExit.FAILED)
    finally:
        if app_runner is not None:
            await app_runner.cleanup()
        if command_socket and os.path.exists(command_socket):
            os.unlink(command_socket)
