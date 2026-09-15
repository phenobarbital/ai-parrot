"""Child-side stub runtime for headless e2e tests (activated by PARROT_DEVLOOP_STUB_RUNNER=1 via PYTHONPATH).

Imported by the spawned child process itself (``python -c "import
_stub_runner; ..."`` with this file's directory prepended to
``PYTHONPATH``); it monkeypatches ``parrot.cli.devloop.bootstrap``'s
runtime builders so ``run_headless`` drives a real :class:`SessionHost`
instead of a real dev-loop/dev-flow graph — every other part of the
headless contract (socket, bearer, handshake, cancel wrap, exit codes)
is the genuine production code path.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Optional

from parrot.bots.flows.core.types import FlowStatus  # verified: bots/flows/core/types.py:62
from parrot.flows.dev_loop.session_state import RunCancelled, SessionHost  # verified: session_state.py:1134,384


@dataclass
class _StubRuntime:
    runner: Any


class _StubResult:
    def __init__(self, status: FlowStatus) -> None:
        self.status = status


class StubRunner:
    """Opens one open_questions gate on a real SessionHost, waits for it, then completes."""

    def __init__(self) -> None:
        self._hosts: dict[str, SessionHost] = {}

    def get_host(self, run_id: str) -> Optional[SessionHost]:
        return self._hosts.get(run_id)

    async def resolve_gate(self, run_id, gate_id, resolution, resolved_by, comment="", origin=None, answers=None):
        host = self._hosts[run_id]
        return host.resolve_gate(gate_id, resolution, resolved_by, comment, origin, answers)

    async def cancel_run(self, run_id, requested_by):
        host = self._hosts[run_id]
        return host.apply(RunCancelled(requested_by=requested_by))

    async def run(self, brief, *, run_id=None, **_):
        run_id = run_id or "run-stub"
        host = SessionHost(run_id=run_id)
        self._hosts[run_id] = host
        gate_id, _env = host.open_gate(
            kind="open_questions",
            node_id="ideation",
            title="Open questions — stub run",
            questions=["What store?"],
            ttl_seconds=None,
            on_expiry="fail",
        )
        # Real gate_ids are uuid4 hex, not predictable by the test process.
        # The command socket has no "list gates" route (production discovers
        # gate ids via the Redis state stream, out of scope for this
        # in-process stub) — so hand it to the test over a file side-channel
        # instead, gated by an env var only the test sets.
        gate_file = os.environ.get("PARROT_DEVLOOP_STUB_GATE_FILE")
        if gate_file:
            with open(gate_file, "w", encoding="utf-8") as fh:
                fh.write(gate_id)
        gate = await host.wait_gate(gate_id)
        # Keep the command endpoint alive briefly after resolution so a test
        # can exercise a duplicate resolve (⇒ 409, first-writer wins)
        # against the still-live socket before the process tears it down.
        await asyncio.sleep(0.5)
        if gate.status == "approved":
            return _StubResult(FlowStatus.COMPLETED)
        return _StubResult(FlowStatus.FAILED)


async def _stub_build(**_):
    return _StubRuntime(runner=StubRunner())


if os.environ.get("PARROT_DEVLOOP_STUB_RUNNER") == "1":
    import parrot.cli.devloop.bootstrap as _b

    _b.build_runtime = _stub_build  # type: ignore[assignment]
    _b.build_dev_flow_runtime = _stub_build  # type: ignore[assignment]
