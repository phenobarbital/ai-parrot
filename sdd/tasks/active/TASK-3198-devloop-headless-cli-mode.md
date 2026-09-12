# TASK-3198: `parrot devloop run --headless` — child mode with command endpoint, handshake and exit codes

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3197
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (design research S4/S7/S8). The Slack integration spawns one
headless `parrot devloop run` child per run. The child must: load the brief,
preflight for its topology, build the runtime (`build_runtime()` for
`WorkBrief`/`FeatureBrief`, `build_dev_flow_runtime()` for `DevRequestBrief`),
mount the existing `register_command_routes` on a Unix socket (or 127.0.0.1
port) behind a per-run bearer token, print exactly one JSON handshake line on
stdout, run `runner.run(...)` as a task, honour cancel by actually cancelling
that task (S7: `cancel_run` only records the action), and exit 0/1/2/3.

---

## Scope

- CREATE `parrot/cli/devloop/headless.py`: `HeadlessHandshake`, `HeadlessExit`,
  `mount_command_endpoint(runner, *, socket_path, port, token, on_cancelled)`,
  `run_headless(*, brief_path, run_id, command_socket, command_port, cancel_grace)`.
- Bearer middleware in BOTH modes (`Authorization: Bearer <token>`, 401 otherwise).
- Wrap the cancel route: after `cancel_run_handler` returns 200, call `on_cancelled`.
- stdout discipline: the handshake is the only stdout line; route logging to stderr.
- MODIFY `run_cmd`: `--headless`, `--command-socket`, `--command-port`, `--run-id`,
  `--cancel-grace`; token from `PARROT_DEVLOOP_COMMAND_TOKEN` (mandatory in headless mode).
- Socket file removed on exit (`finally`), endpoint closed.
- Tests: `packages/ai-parrot/tests/cli/devloop/test_headless.py`.

**NOT in scope**: the parent-side supervisor / channel (TASK-3202); the
runtime builders (TASK-3197); any change to `commands.py`, `runner.py`,
`session_state.py` (spec non-goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/headless.py` | CREATE | Handshake, exit codes, endpoint, `run_headless` |
| `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` | MODIFY | New Click options on `run_cmd` (:73-121) + headless branch |
| `packages/ai-parrot/tests/cli/devloop/test_headless.py` | CREATE | Unit tests (socket, TCP+token, exit codes, cancel) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references. **DO NOT** invent imports, attributes or methods not listed here.

### Verified Imports
```python
import click                                                             # verified: cli/devloop/__init__.py:12
from aiohttp import web                                                  # core dependency (web.Application, web.AppRunner, web.UnixSite, web.TCPSite, web.middleware)
from pydantic import BaseModel                                           # core dependency
from parrot.flows.dev_loop import register_command_routes                # verified: flows/dev_loop/__init__.py:12
from parrot.flows.dev_loop.commands import cancel_run_handler            # verified: flows/dev_loop/commands.py:163
from parrot.cli.devloop.bootstrap import preflight, build_runtime, build_dev_flow_runtime, load_headless_brief  # verified: bootstrap.py:84,249 + TASK-3197
from parrot.flows.dev_flow.models import DevRequestBrief                 # verified: dev_flow/models.py:61
from parrot.bots.flows.core.types import FlowStatus                      # verified: bots/flows/core/types.py:62 (COMPLETED/PARTIAL/FAILED)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/devloop/__init__.py
@devloop.command("run")                                                  # line 73
@click.option("--brief", "brief_file", type=click.Path(exists=True), default=None, help=...)   # line 74
@click.option("--yes", "skip_wizard", is_flag=True, default=False, help=...)                    # line 79
@click.option("--dev-agent", "dev_agent_flags", multiple=True, default=(), help=...)            # line 84
@click.option("--text", "intake_text", default=None, help=...)                                  # line 88-91
def run_cmd(brief_file: str | None = None, skip_wizard: bool = False,
            dev_agent_flags: tuple[str, ...] = (), intake_text: str | None = None) -> None:     # line 92-97
#   body: `from parrot.cli.devloop.console import DevLoopConsole  # noqa: PLC0415` (line 110), builds DevLoopConsole, asyncio.run(console.start(...)), raise SystemExit(exit_code)  # lines 110-121

# packages/ai-parrot/src/parrot/flows/dev_loop/commands.py
async def resolve_gate_handler(request: web.Request) -> web.Response      # line 77  (200/400/404/409)
async def cancel_run_handler(request: web.Request) -> web.Response        # line 163 (200 terminal-sticky / 400 / 404)
def register_command_routes(app: web.Application, runner: DevLoopRunner) -> None   # line 208 — app["dev_loop_runner"]=runner; add_post("/runs/{run_id}/gates/{gate_id}/resolve"), add_post("/runs/{run_id}/cancel")

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:
    async def run(self, brief, *, run_id=None, initial_task="", extra_shared=None, flow_kwargs_overrides=None) -> FlowResult   # line 1189 — awaits the whole run
    async def cancel_run(self, run_id: str, requested_by: str) -> ActionEnvelope   # line 1051 — ONLY applies RunCancelled (lines 1064-1067); does not stop the flow
    def get_host(self, run_id: str) -> Optional[SessionHost]                       # line 516
# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py
class DevFlowRunner(DevLoopRunner): async def run(self, brief: DevRequestBrief | FeatureBrief, *, run_id=None, initial_task="", extra_shared=None, model_plan=None) -> FlowResult   # line 80

# packages/ai-parrot/src/parrot/bots/flows/core/result.py
class FlowResult: status: FlowStatus ...                                  # line 360 (status values "completed"/"partial"/"failed")

# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py (after TASK-3197)
async def build_runtime(*, console=None) -> DevLoopRuntime               # line 249 — .runner
async def build_dev_flow_runtime(*, console=None) -> DevFlowRuntime      # TASK-3197 — .runner
def load_headless_brief(path: str) -> WorkBrief | FeatureBrief | DevRequestBrief   # TASK-3197
```

### Does NOT Exist
- ~~`parrot/cli/devloop/headless.py`~~, ~~`--headless` / `--command-socket` / `--command-port` / `--run-id` / `--cancel-grace`~~ — created by THIS task.
- ~~`DevLoopRunner.start_run()` / fire-and-forget API~~ — `run()` awaits completion; wrap it in `asyncio.create_task` (as `console.py:770` and `server_dev.py:801` do).
- ~~a runner-level "cancel actually stops the flow" hook~~ — none; `cancel_run` only records `run/cancelled` (runner.py:1064-1067). THIS task cancels the asyncio task itself.
- ~~`register_command_routes` accepting an auth callback~~ — the routes are auth-agnostic by design (commands.py:19); auth is a middleware added by THIS task on the private app.
- ~~`web.UnixSite` setting file mode~~ — aiohttp does not chmod the socket; call `os.chmod(path, 0o600)` after `site.start()`.
- ~~stdout logging by default in the child~~ — must be configured to stderr by `run_headless` (`logging.basicConfig(stream=sys.stderr)`) before any output.

---

## Implementation Notes

### Pattern to Follow
```python
# server_dev.py:801 / console.py:770 — how a run is started without blocking
run_task = asyncio.create_task(runner.run(brief, run_id=run_id), name=f"devloop-run-{run_id}")
```
```python
# aiohttp private server (UnixSite or TCPSite)
app = web.Application(middlewares=[_bearer_middleware(token)])
register_command_routes(app, runner)
app_runner = web.AppRunner(app); await app_runner.setup()
site = web.UnixSite(app_runner, socket_path) if socket_path else web.TCPSite(app_runner, "127.0.0.1", port or 0)
await site.start()
```

### Key Constraints
- The handshake line is `HeadlessHandshake.model_dump_json()` + `"\n"` written to `sys.stdout` and flushed, AFTER `site.start()`, BEFORE `runner.run` is scheduled.
- For TCP with `port=0`, read the bound port from `site._server.sockets[0].getsockname()[1]` (FILL IN: verify the attribute on the installed aiohttp) to build `command_endpoint`.
- Cancel path: wrapping means registering the cancel route yourself: call `register_command_routes` then override — aiohttp does not allow duplicate routes, so instead register the routes manually: `app.router.add_post("/runs/{run_id}/gates/{gate_id}/resolve", resolve_gate_handler)` and `app.router.add_post("/runs/{run_id}/cancel", _cancel_then_stop)` where `_cancel_then_stop` awaits `cancel_run_handler(request)` and fires `on_cancelled()` when `resp.status == 200`; set `app["dev_loop_runner"] = runner` yourself (that is all `register_command_routes` does, commands.py:208-224).
- Exit mapping (spec §7): FlowResult status `completed` ⇒ 0; exception or `failed`/`partial` ⇒ 1; cancelled (task cancelled via `on_cancelled`) ⇒ 2; preflight/bootstrap failure (`SystemExit` from the builders, `FileNotFoundError`/`ValueError` from the loader) ⇒ 3.
- Never raise out of `run_headless`; `finally` removes the socket file and calls `app_runner.cleanup()`.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py:208-224` — what `register_command_routes` does
- `examples/dev_loop/server_dev.py:580-831` — run task + flow_tasks bookkeeping precedent
- `packages/ai-parrot/tests/cli/devloop/test_click_wiring.py` — Click option test style (`CliRunner`)

---

## Implementation Blueprint

### Steps (in order)
1. Create `headless.py` with the models, middleware and `mount_command_endpoint` — *why*: the parent (TASK-3202) codes against this exact handshake/endpoint contract.
2. Add `run_headless` — *why*: single entry that owns bootstrap, run task, cancel, exit code, cleanup.
3. Add the Click options + headless branch to `run_cmd` — *why*: the child is spawned as `parrot devloop run --brief … --yes --headless …`.
4. Tests with a stub runner (`resolve_gate`/`cancel_run`/`run` fakes) — *why*: AC4, AC15, AC21 without a real flow.

### `packages/ai-parrot/src/parrot/cli/devloop/headless.py` (CREATE)
```python
"""Headless child mode for ``parrot devloop run`` (FEAT-555 Module 1)."""
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
    @web.middleware
    async def middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.headers.get("Authorization", "") != f"Bearer {token}":
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    return middleware


async def mount_command_endpoint(
    runner: Any, *, socket_path: Optional[str], port: Optional[int], token: str, on_cancelled: Callable[[], None]
) -> tuple[web.AppRunner, str]:
    """Mount the gate-resolve / cancel routes on a UnixSite or 127.0.0.1 TCPSite behind a bearer token.

    The cancel route is wrapped so a 200 fires ``on_cancelled`` (S7). Returns the AppRunner and the endpoint
    string (``unix://<path>`` | ``http://127.0.0.1:<port>``).
    """

    async def _cancel_then_stop(request: web.Request) -> web.Response:
        resp = await cancel_run_handler(request)
        if resp.status == 200:
            on_cancelled()
        return resp

    app = web.Application(middlewares=[_bearer_middleware(token)])
    app["dev_loop_runner"] = runner  # what register_command_routes does (commands.py:208-224)
    app.router.add_post("/runs/{run_id}/gates/{gate_id}/resolve", resolve_gate_handler)
    app.router.add_post("/runs/{run_id}/cancel", _cancel_then_stop)
    app_runner = web.AppRunner(app)
    await app_runner.setup()
    if socket_path:
        site: web.BaseSite = web.UnixSite(app_runner, socket_path)
        await site.start()
        os.chmod(socket_path, 0o600)
        return app_runner, f"unix://{socket_path}"
    site = web.TCPSite(app_runner, "127.0.0.1", port or 0)
    await site.start()
    # FILL IN: bound port for port=0 (site._server.sockets[0].getsockname()[1] — verify on installed aiohttp) — bounded by AC4
    return app_runner, f"http://127.0.0.1:{port}"
```
**Why this shape**: spec M1 skeleton; routes are registered by hand only to wrap cancel (aiohttp forbids duplicate routes); bearer in both modes is the resolved S4 decision.

### `packages/ai-parrot/src/parrot/cli/devloop/headless.py` (CREATE — second half, same file)
```python
async def run_headless(
    *, brief_path: str, run_id: Optional[str], command_socket: Optional[str], command_port: Optional[int],
    cancel_grace: float = 30.0,
) -> int:
    """Run one brief headless; never raises. See HeadlessExit for the exit-code contract."""
    import uuid  # noqa: PLC0415
    from parrot.cli.devloop.bootstrap import build_dev_flow_runtime, build_runtime, load_headless_brief  # noqa: PLC0415
    from parrot.flows.dev_flow.models import DevRequestBrief  # noqa: PLC0415

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)  # stdout is reserved for the handshake
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
            runner, socket_path=command_socket, port=command_port, token=token, on_cancelled=cancelled.set
        )
        sys.stdout.write(HeadlessHandshake(run_id=run_id, command_endpoint=endpoint, kind=brief.kind, pid=os.getpid()).model_dump_json() + "\n")
        sys.stdout.flush()
        run_task = asyncio.create_task(runner.run(brief, run_id=run_id), name=f"devloop-run-{run_id}")
        cancel_waiter = asyncio.create_task(cancelled.wait())
        done, _ = await asyncio.wait({run_task, cancel_waiter}, return_when=asyncio.FIRST_COMPLETED)
        if cancel_waiter in done and run_task not in done:
            run_task.cancel()
            # FILL IN: await run_task with asyncio.wait_for(..., cancel_grace), swallowing CancelledError/TimeoutError — bounded by AC21
            return int(HeadlessExit.CANCELLED)
        cancel_waiter.cancel()
        result = run_task.result()  # raises if the run raised
        # FILL IN: map result.status (FlowStatus.COMPLETED ⇒ COMPLETED, else FAILED) — bounded by spec §7 exit codes
        return int(HeadlessExit.COMPLETED)
    except (SystemExit, FileNotFoundError, ValueError) as exc:
        logger.error("headless bootstrap failed: %s", exc)
        return int(HeadlessExit.BOOTSTRAP_FAILED)
    except Exception:  # noqa: BLE001 — run failed
        logger.exception("headless run %s failed", run_id)
        return int(HeadlessExit.FAILED)
    finally:
        if app_runner is not None:
            await app_runner.cleanup()
        if command_socket and os.path.exists(command_socket):
            os.unlink(command_socket)
```
**Why**: `cancelled.set` is the S7 hook; bootstrap failures exit 3 BEFORE the handshake so the parent classifies them as spawn errors.

### `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` (MODIFY — options)
```python
# occurrences: 1 (verified: grep -c '@click.option("--text", "intake_text", default=None,' packages/ai-parrot/src/parrot/cli/devloop/__init__.py)
# BEFORE — insert above `@click.option("--text", "intake_text", default=None,` (verified: cli/devloop/__init__.py:88)
@click.option("--headless", is_flag=True, default=False,
              help="Non-interactive child mode (FEAT-555): requires --brief; prints a JSON handshake on stdout.")
@click.option("--command-socket", default=None, help="Unix socket path for the gate/cancel REST endpoint.")
@click.option("--command-port", type=int, default=None,
              help="127.0.0.1 port (0 = ephemeral) instead of a socket; token from PARROT_DEVLOOP_COMMAND_TOKEN.")
@click.option("--run-id", default=None, help="Externally minted run id (run-<hex8>); generated when omitted.")
@click.option("--cancel-grace", type=float, default=30.0,
              help="Seconds to wait for the run task to unwind after a cancel before exiting 2.")
```
```python
# occurrences: 1 (verified: grep -c '    intake_text: str | None = None,' packages/ai-parrot/src/parrot/cli/devloop/__init__.py)
# AFTER — insert below `    intake_text: str | None = None,` (verified: cli/devloop/__init__.py:96) — new run_cmd parameters
    headless: bool = False,
    command_socket: str | None = None,
    command_port: int | None = None,
    run_id: str | None = None,
    cancel_grace: float = 30.0,
```
```python
# occurrences: 2 (verified: grep -c '    from parrot.cli.devloop.console import DevLoopConsole  # noqa: PLC0415' packages/ai-parrot/src/parrot/cli/devloop/__init__.py)
# FILL IN: disambiguate — the anchor appears in run_cmd (:110) AND revise_cmd; insert the block below at the START of run_cmd's
# body, i.e. right after the closing `"""` of run_cmd's docstring (the paragraph ending "new_feature WorkBrief path, unchanged.")
    if headless:
        if not brief_file:
            raise click.UsageError("--headless requires --brief")
        if intake_text:
            raise click.UsageError("--headless cannot be combined with --text")
        from parrot.cli.devloop.headless import run_headless  # noqa: PLC0415

        raise SystemExit(asyncio.run(run_headless(
            brief_path=brief_file, run_id=run_id, command_socket=command_socket,
            command_port=command_port, cancel_grace=cancel_grace,
        )))
```
**Why**: the headless branch returns before `DevLoopConsole` is imported, keeping the interactive path byte-identical.

### `packages/ai-parrot/tests/cli/devloop/test_headless.py` (CREATE)
```python
"""FEAT-555 TASK-3198 — headless child: handshake, endpoint auth, exit codes, cancel."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientSession, UnixConnector

from parrot.cli.devloop.headless import HeadlessExit, HeadlessHandshake, mount_command_endpoint, run_headless


def _stub_runner() -> MagicMock:
    runner = MagicMock()
    runner.cancel_run = AsyncMock(return_value=MagicMock(model_dump=lambda: {}))
    runner.resolve_gate = AsyncMock(return_value=MagicMock(model_dump=lambda: {}))
    return runner


@pytest.mark.asyncio
async def test_unix_socket_requires_bearer(tmp_path):
    sock = str(tmp_path / "r.sock")
    fired = []
    app_runner, endpoint = await mount_command_endpoint(_stub_runner(), socket_path=sock, port=None, token="t0k", on_cancelled=lambda: fired.append(1))
    assert endpoint == f"unix://{sock}"
    async with ClientSession(connector=UnixConnector(path=sock)) as s:
        r = await s.post("http://x/runs/run-1/cancel", json={"requested_by": "u"})
        assert r.status == 401
        r = await s.post("http://x/runs/run-1/cancel", json={"requested_by": "u"}, headers={"Authorization": "Bearer t0k"})
        # FILL IN: assert status (200 with the stub, or 404 depending on stub cancel_run) and fired == [1] on 200 — bounded by AC15/AC21
    await app_runner.cleanup()


@pytest.mark.asyncio
async def test_tcp_ephemeral_port_in_endpoint():
    # FILL IN: port=0 ⇒ endpoint "http://127.0.0.1:<real port>"; 401 without bearer — bounded by AC4/AC15
    pytest.skip("FILL IN")


@pytest.mark.asyncio
async def test_run_headless_exit_codes(tmp_path, monkeypatch, capsys):
    # FILL IN: monkeypatch bootstrap.load_headless_brief/build_runtime with a stub runner whose run() returns a FlowResult-like
    # object (status completed/failed) or raises; assert exit 0/1, exactly one stdout line parsing as HeadlessHandshake,
    # and socket removed; missing token ⇒ 3 — bounded by AC4
    pytest.skip("FILL IN")


@pytest.mark.asyncio
async def test_cancel_stops_run_task(tmp_path, monkeypatch):
    # FILL IN: stub runner.run awaits forever; POST cancel with bearer ⇒ run_headless returns 2 within cancel_grace — bounded by AC21
    pytest.skip("FILL IN")
```
**Why this shape**: rows `test_headless_handshake_line`, `test_mount_command_endpoint_*`, `test_headless_exit_codes`, `test_headless_cancel_stops_run_task` from spec §4.

### FILL IN checklist
- [ ] `headless.py::mount_command_endpoint` — ephemeral TCP port discovery; bounded by AC4
- [ ] `headless.py::run_headless` — cancel wait with `cancel_grace`; FlowResult status mapping; bounded by AC21 / spec §7
- [ ] `__init__.py::run_cmd` — place the headless branch before the console import (2 anchor occurrences, see block); bounded by "interactive path unchanged"
- [ ] tests — four stubs; bounded by AC4/AC15/AC21

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/devloop -q`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/cli/devloop`
- [ ] Imports work: `from parrot.cli.devloop.headless import run_headless, HeadlessHandshake, HeadlessExit`
- [ ] Spec AC4 (one handshake line, exit codes, socket removed), AC15 (bearer in both modes), AC21 (cancel ⇒ exit 2)
- [ ] `parrot devloop run --help` lists the five new options and stays fast (no heavy import at import time)

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/devloop/test_headless.py — see blueprint block above
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/dev-loop-slack.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3198-devloop-headless-cli-mode.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
