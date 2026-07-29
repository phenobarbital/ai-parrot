"""REST command endpoints — resolve a HITL gate, cancel a run (FEAT-322).

Implements **Module 7** (spec §3, goal G5 write side; proposal U3: WS for
reads / REST for commands). These are thin adapters over
:class:`DevLoopRunner`'s command surface (:meth:`DevLoopRunner.resolve_gate`,
:meth:`DevLoopRunner.cancel_run`) — no business logic lives here, and
neither handler touches a :class:`SessionHost` directly except to read the
gate's audit fields for the 409 conflict body.

Routes (registered by :func:`register_command_routes`):

* ``POST /runs/{run_id}/gates/{gate_id}/resolve`` — body
  :class:`ResolveGateRequest`. 200 envelope | 400 invalid body | 404 unknown
  run/gate | 409 already-resolved (with resolver identity + timestamp).
* ``POST /runs/{run_id}/cancel`` — body :class:`CancelRunRequest`. 200
  envelope | 404 unknown run.

Authentication/authorization are NOT handled here — the hosting aiohttp
app's own auth middleware (if any) applies to these routes like any other;
this module is deliberately auth-agnostic (out of scope, spec §3 M7).
"""

from __future__ import annotations

import logging
from typing import Literal

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from parrot.flows.dev_loop.runner import DevLoopRunner
from parrot.flows.dev_loop.session_state import (
    ActionOrigin,
    GateAlreadyResolvedError,
    GateNotFoundError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ResolveGateRequest(BaseModel):
    """Body of ``POST /runs/{run_id}/gates/{gate_id}/resolve``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolution: Literal["approved", "rejected"]
    resolved_by: str = Field(..., min_length=1)
    comment: str = ""
    client_seq: int = 0


class CancelRunRequest(BaseModel):
    """Body of ``POST /runs/{run_id}/cancel``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_by: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def resolve_gate_handler(request: web.Request) -> web.Response:
    """``POST /runs/{run_id}/gates/{gate_id}/resolve``.

    Args:
        request: The incoming aiohttp request. Path params: ``run_id``,
            ``gate_id``. The runner instance is read from
            ``request.app["dev_loop_runner"]`` (bound by
            :func:`register_command_routes`).

    Returns:
        200 ``{"envelope": <ActionEnvelope>}`` on success; 400 on a
        malformed body; 404 for an unknown run or gate; 409 when the gate
        was already resolved (body names the first resolver + timestamp).
    """
    runner: DevLoopRunner = request.app["dev_loop_runner"]
    run_id = request.match_info["run_id"]
    gate_id = request.match_info["gate_id"]

    try:
        raw_body = await request.json()
    except Exception:  # noqa: BLE001 - malformed JSON body
        return web.json_response({"error": "invalid_json"}, status=400)

    try:
        body = ResolveGateRequest.model_validate(raw_body)
    except ValidationError as exc:
        return web.json_response(
            {"error": "invalid_body", "detail": exc.errors()}, status=400
        )

    origin = ActionOrigin(client_id=body.resolved_by, client_seq=body.client_seq)

    try:
        envelope = await runner.resolve_gate(
            run_id, gate_id, body.resolution, body.resolved_by,
            body.comment, origin=origin,
        )
    except GateNotFoundError:
        # NOTE: GateNotFoundError subclasses KeyError — this except clause
        # MUST come before the bare ``except KeyError`` below, or the more
        # specific case is silently swallowed as "unknown_run".
        logger.info(
            "resolve_gate: unknown gate_id=%s for run_id=%s", gate_id, run_id
        )
        return web.json_response({"error": "unknown_gate"}, status=404)
    except KeyError:
        logger.info(
            "resolve_gate: unknown run_id=%s gate_id=%s", run_id, gate_id
        )
        return web.json_response({"error": "unknown_run"}, status=404)
    except GateAlreadyResolvedError:
        host = runner.get_host(run_id)
        gate = host.state.gates.get(gate_id) if host is not None else None
        logger.info(
            "resolve_gate: gate_id=%s on run_id=%s already resolved "
            "(attempted by %s)", gate_id, run_id, body.resolved_by,
        )
        return web.json_response(
            {
                "error": "already_resolved",
                "status": gate.status if gate is not None else "unknown",
                "resolved_by": gate.resolved_by if gate is not None else "",
                "resolved_at": gate.resolved_at if gate is not None else None,
            },
            status=409,
        )

    logger.info(
        "resolve_gate: run_id=%s gate_id=%s resolution=%s by=%s",
        run_id, gate_id, body.resolution, body.resolved_by,
    )
    return web.json_response({"envelope": envelope.model_dump(mode="json")})


async def cancel_run_handler(request: web.Request) -> web.Response:
    """``POST /runs/{run_id}/cancel``.

    Args:
        request: The incoming aiohttp request. Path param: ``run_id``. The
            runner instance is read from ``request.app["dev_loop_runner"]``.

    Returns:
        200 ``{"envelope": <ActionEnvelope>}`` on success (terminal-sticky —
        a second cancel is still a 200 no-op envelope, per the reducer's
        total/terminal-sticky contract); 400 on a malformed body; 404 for an
        unknown run.
    """
    runner: DevLoopRunner = request.app["dev_loop_runner"]
    run_id = request.match_info["run_id"]

    try:
        raw_body = await request.json()
    except Exception:  # noqa: BLE001 - malformed JSON body
        return web.json_response({"error": "invalid_json"}, status=400)

    try:
        body = CancelRunRequest.model_validate(raw_body)
    except ValidationError as exc:
        return web.json_response(
            {"error": "invalid_body", "detail": exc.errors()}, status=400
        )

    try:
        envelope = await runner.cancel_run(run_id, body.requested_by)
    except KeyError:
        logger.info("cancel_run: unknown run_id=%s", run_id)
        return web.json_response({"error": "unknown_run"}, status=404)

    logger.info(
        "cancel_run: run_id=%s requested_by=%s", run_id, body.requested_by
    )
    return web.json_response({"envelope": envelope.model_dump(mode="json")})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_command_routes(app: web.Application, runner: DevLoopRunner) -> None:
    """Register the gate-resolve and run-cancel REST routes on *app*.

    Mirrors the ``register_*`` naming precedent
    (``webhook.register_pull_request_webhook``). The runner is bound onto
    ``app["dev_loop_runner"]`` so the handlers can resolve it without a
    closure per-route.

    Args:
        app: The hosting aiohttp application.
        runner: The :class:`DevLoopRunner` instance backing these commands.
    """
    app["dev_loop_runner"] = runner
    app.router.add_post(
        "/runs/{run_id}/gates/{gate_id}/resolve", resolve_gate_handler
    )
    app.router.add_post("/runs/{run_id}/cancel", cancel_run_handler)


__all__ = [
    "CancelRunRequest",
    "ResolveGateRequest",
    "cancel_run_handler",
    "register_command_routes",
    "resolve_gate_handler",
]
