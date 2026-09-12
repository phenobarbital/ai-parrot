# TASK-3202: Headless subprocess supervisor and loopback command channel

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3200
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (+ §7 "Endpoint & auth", "Cancellation semantics",
"Supervisor bounds", design research S4/S7/S8). `HeadlessRunProcess` spawns
and observes one `parrot devloop run --headless` child (TASK-3197 implements the
child side; this task only needs its **contract**: one JSON handshake line on
stdout, bearer token via `PARROT_DEVLOOP_COMMAND_TOKEN`, exit codes 0/1/2/3).
`LoopbackRestChannel` sends the existing `ResolveGateRequest` /
`CancelRunRequest` bodies to the child's mounted `register_command_routes` over
a Unix socket (default) or 127.0.0.1 TCP, always with the per-run bearer token.
Because the wire contract is fixed by the spec, this task is testable against a
fake child script before TASK-3197 exists.

---

## Scope

- `devloop/process.py`: `HeadlessRunProcess` with `spawn()` (`asyncio.create_subprocess_exec`, `cwd=config.repo_path`, `start_new_session=True`, `stdout=PIPE`, `stderr=PIPE`, env with the token), continuous stdout/stderr reader tasks feeding 4 KiB ring buffers, `wait_ready(timeout)` returning the handshake (first stdout line validating as `{"event":"ready", ...}`), `wait()`, `stderr_tail()`, `terminate(grace)` (SIGTERM → SIGKILL), `cleanup()` (socket + brief file, idempotent), `pid`.
- `devloop/bridge.py`: `RunCommandChannel` Protocol; `LoopbackRestChannel(endpoint, *, token, timeout)` with `resolve_gate(...)`, `cancel(...)`, `probe()`; status → reason mapping.
- `HeadlessHandshakeView` (pydantic) in `process.py`: `event`, `run_id`, `command_endpoint`, `kind`, `pid` (mirror of the child's `HeadlessHandshake`, TASK-3197).
- Tests with a fake child script fixture: `test_process.py`, `test_bridge.py` (the latter mounts `register_command_routes` on a real `web.UnixSite` with a stub runner).

**NOT in scope**: the child's own headless mode (TASK-3197), the service that decides when to spawn/cancel (TASK-3204), Redis.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/process.py` | CREATE | `HeadlessRunProcess`, `HeadlessHandshakeView` |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/bridge.py` | CREATE | `RunCommandChannel`, `LoopbackRestChannel` |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py` | MODIFY | re-exports |
| `packages/ai-parrot-integrations/tests/integrations/devloop/fake_child.py` | CREATE | Script used as the child in tests (handshake + stub REST) |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_process.py` | CREATE | spawn / handshake / timeout / drain / terminate / cleanup |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_bridge.py` | CREATE | status mapping over a real UnixSite with the library routes |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import asyncio, collections, json, os, signal, sys        # stdlib
from aiohttp import ClientSession, ClientTimeout, TCPConnector, UnixConnector, web   # aiohttp (core dependency)
from pydantic import BaseModel
from parrot.flows.dev_loop.commands import ResolveGateRequest, CancelRunRequest, register_command_routes  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/commands.py:46,64,208
from parrot.integrations.devloop.models import BridgeResult, DevLoopIntegrationConfig, SpawnError   # TASK-3200
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/commands.py
class ResolveGateRequest(BaseModel):   # line 46 — frozen, extra="forbid"
    resolution: Literal["approved", "rejected"]; resolved_by: str (min_length=1); comment: str = ""; client_seq: int = 0
    answers: dict[str, str] = {}       # line 63
class CancelRunRequest(BaseModel):     # line 64 — requested_by: str (min_length=1)
async def resolve_gate_handler(request) -> web.Response      # line 77
#   400 {"error": "invalid_json"} | {"error": "invalid_body"} | {"error": "answers_required"} (lines 98,104,137)
#   404 {"error": "unknown_gate"} | {"error": "unknown_run"} (lines 121,126) ; 409 {"error": "already_resolved"} (line 148)
#   200 {"envelope": {...}} (line 160)
async def cancel_run_handler(request) -> web.Response        # line 163 — 400 invalid_json/invalid_body, 404 unknown_run, 200 envelope
def register_command_routes(app: web.Application, runner: DevLoopRunner) -> None   # line 208
#   app["dev_loop_runner"] = runner ; POST /runs/{run_id}/gates/{gate_id}/resolve ; POST /runs/{run_id}/cancel  (lines 220-224)
#   the handlers call runner.resolve_gate(run_id, gate_id, resolution, resolved_by, comment=..., answers=...) and runner.cancel_run(run_id, requested_by)
```
Child contract (spec §2/§7, implemented by TASK-3197): argv `[*config.command, "--brief", brief_path, "--yes", "--headless", "--run-id", run_id, "--command-socket", socket_path]` (or `"--command-port", str(port)`); env `PARROT_DEVLOOP_COMMAND_TOKEN=<token>`; first stdout line `{"event":"ready","run_id":…,"command_endpoint":"unix:///…|http://127.0.0.1:N","kind":…,"pid":N}`; all logging on stderr; exit 0 completed / 1 failed / 2 cancelled / 3 bootstrap failure; every request without `Authorization: Bearer <token>` ⇒ 401.

### Does NOT Exist
- ~~`parrot.cli.devloop.headless`~~ — created by TASK-3197; do NOT import it (this package must not depend on the CLI). Define `HeadlessHandshakeView` locally.
- ~~`DevLoopRunner.start_run()`~~ — no fire-and-forget API; irrelevant here (the child owns the runner).
- ~~`requests` / `httpx`~~ — banned (TID251); aiohttp only.
- ~~`aiohttp.UnixConnector(path=...)` with a `unix://` URL passed to `session.post`~~ — with `UnixConnector` the request URL must be `http://localhost/runs/...` (host is ignored); strip the `unix://` scheme into the connector path.
- ~~`asyncio.subprocess.Process.terminate()` killing the whole session~~ — `start_new_session=True` makes the child a session leader; send signals to `proc.pid` only, never to a group.
- ~~`fakeredis`~~ — not needed here and not installed.

---

## Implementation Notes

### Pattern to Follow
```python
# Continuous pipe drain (S8): never await proc.wait() without reader tasks running.
async def _drain(self, stream: asyncio.StreamReader, buf: collections.deque[bytes], first_line: asyncio.Future | None) -> None:
    while True:
        line = await stream.readline()
        if not line:
            break
        if first_line is not None and not first_line.done():
            first_line.set_result(line)  # handshake candidate
            continue
        buf.append(line[-4096:])
```

### Key Constraints
- Ring buffers are bounded by bytes (4 KiB total per stream), not lines.
- `wait_ready` validates lines until one parses as `HeadlessHandshakeView`; non-JSON lines before it are logged at DEBUG (spec §7 Handshake contract); EOF/exit before a handshake ⇒ `SpawnError(exit_code=proc.returncode, stderr_tail=...)`; timeout ⇒ `terminate()` then `SpawnError`.
- `LoopbackRestChannel` maps: 200 → `ok=True`; 400 → reason from body `error` (`invalid_body`/`answers_required`/`invalid_json`); 404 → `not_found`; 409 → `already_resolved`; 401 → `unauthorized`; `ClientConnectorError`/`asyncio.TimeoutError`/`OSError` → `ok=False, status=0, reason="unreachable"`. Never raises on HTTP status.
- `probe()`: `GET /` — ANY HTTP response (401/404 included) ⇒ `True`; connection error ⇒ `False`.
- Bodies are built with `ResolveGateRequest(...).model_dump()` / `CancelRunRequest(...).model_dump()` so the contract cannot drift.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py:77-160` — status/error names.
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:585-626` — aiohttp `ClientSession` POST pattern with headers.

---

## Implementation Blueprint

### Steps (in order)
1. Write `process.py` with the handshake model and the supervisor — *why*: the fake child script in tests must match this exact contract.
2. Write `bridge.py` — *why*: independent of process; testable against the library routes mounted in-test.
3. Write `fake_child.py` (argparse for `--command-socket/--run-id`, prints the handshake, serves `register_command_routes` with a stub runner, exits with a code from `FAKE_CHILD_EXIT`) — *why*: exercises the real cross-process contract (spec §4 `test_cross_process_command_contract` groundwork).
4. Tests, `ruff`, `black`; extend `devloop/__init__.py` exports.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/process.py` (CREATE)
```python
"""Headless child supervisor (spec §3 Module 6; design research S7/S8)."""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import signal
from typing import Any, Deque, Literal, Optional

from pydantic import BaseModel, ValidationError

from parrot.integrations.devloop.models import DevLoopIntegrationConfig, SpawnError

_RING_BYTES = 4096


class HeadlessHandshakeView(BaseModel):
    """Mirror of the child's ``HeadlessHandshake`` (TASK-3197) — the one stdout line the parent waits for."""

    event: Literal["ready"]
    run_id: str
    command_endpoint: str
    kind: str
    pid: int


class HeadlessRunProcess:
    """One ``parrot devloop run --headless`` child, drained continuously from spawn to exit."""

    def __init__(self, proc: asyncio.subprocess.Process, *, socket_path: Optional[str], brief_path: str) -> None:
        self._proc = proc
        self._socket_path = socket_path
        self._brief_path = brief_path
        self._stdout: Deque[bytes] = collections.deque()
        self._stderr: Deque[bytes] = collections.deque()
        self._handshake: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._readers = [asyncio.create_task(self._drain(proc.stdout, self._stdout, self._handshake)),
                         asyncio.create_task(self._drain(proc.stderr, self._stderr, None))]
        self.logger = logging.getLogger(__name__)

    @property
    def pid(self) -> int:
        return self._proc.pid

    @classmethod
    async def spawn(cls, *, config: DevLoopIntegrationConfig, run_id: str, brief_path: str,
                    socket_path: Optional[str], port: Optional[int], token: str) -> "HeadlessRunProcess":
        """Spawn the child (session leader, both pipes captured, token only via env)."""
        argv = [*config.command, "--brief", brief_path, "--yes", "--headless", "--run-id", run_id]
        argv += ["--command-socket", socket_path] if socket_path else ["--command-port", str(port or 0)]
        env = {**os.environ, "PARROT_DEVLOOP_COMMAND_TOKEN": token}
        proc = await asyncio.create_subprocess_exec(*argv, cwd=config.repo_path or None, env=env, start_new_session=True,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        return cls(proc, socket_path=socket_path, brief_path=brief_path)

    async def _drain(self, stream: Any, buf: Deque[bytes], first: Optional["asyncio.Future[bytes]"]) -> None:
        # FILL IN: readline loop per "Pattern to Follow"; keep buf ≤ _RING_BYTES total (pop left); when `first` is
        # set and a line validates as HeadlessHandshakeView JSON, resolve it; other pre-handshake lines → DEBUG log —
        # bounded by spec §7 Handshake contract / AC4.
        raise NotImplementedError

    async def wait_ready(self, timeout: float) -> HeadlessHandshakeView:
        """First handshake line, or SpawnError (child exit/EOF/timeout — timeout also terminates the child)."""
        # FILL IN: asyncio.wait({self._handshake, asyncio.create_task(self._proc.wait())}, timeout=...) ; map the
        # three outcomes to HeadlessHandshakeView / SpawnError(exit_code, stderr_tail) — bounded by AC14.
        raise NotImplementedError

    async def wait(self) -> int:
        code = await self._proc.wait()
        await asyncio.gather(*self._readers, return_exceptions=True)
        return code

    def stderr_tail(self) -> str:
        return b"".join(self._stderr).decode("utf-8", "replace")[-_RING_BYTES:]

    async def terminate(self, grace: float = 10.0) -> None:
        """SIGTERM, then SIGKILL after ``grace`` seconds (only the child pid, never its group)."""
        # FILL IN: if returncode is None: proc.send_signal(SIGTERM); wait_for(proc.wait(), grace) except TimeoutError → proc.kill() — S7/S8.
        raise NotImplementedError

    def cleanup(self) -> None:
        """Remove the socket file and brief file if still present (idempotent, parent-side)."""
        for path in (self._socket_path, self._brief_path):
            if path and os.path.exists(path):
                os.remove(path)
```
**Why this shape**: reader tasks start in `__init__` so no byte is ever left unread (S8); the handshake future is resolved by the stdout drain itself, so `wait_ready` can race it against `proc.wait()` and classify EOF/exit/timeout (AC14). `terminate` targets the pid only because `start_new_session=True` isolates the child from the bot's signals by design (G7).

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/bridge.py` (CREATE)
```python
"""Command channel to a headless child (spec §3 Module 6; S4 token in both modes)."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Protocol

from aiohttp import ClientConnectorError, ClientSession, ClientTimeout, UnixConnector

from parrot.flows.dev_loop.commands import CancelRunRequest, ResolveGateRequest  # verified: commands.py:46,64
from parrot.integrations.devloop.models import BridgeResult

_STATUS_REASON = {404: "not_found", 409: "already_resolved", 401: "unauthorized"}


class RunCommandChannel(Protocol):
    """Inbound command path to one run. A Redis implementation may replace this later (brainstorm Option B)."""

    async def resolve_gate(self, run_id: str, gate_id: str, *, resolution: str, resolved_by: str,
                           comment: str = "", answers: Optional[dict[str, str]] = None) -> BridgeResult: ...
    async def cancel(self, run_id: str, *, requested_by: str) -> BridgeResult: ...
    async def probe(self) -> bool: ...


class LoopbackRestChannel:
    """``RunCommandChannel`` over the child's ``register_command_routes`` (Unix socket or 127.0.0.1 TCP)."""

    def __init__(self, endpoint: str, *, token: str, timeout: float = 10.0) -> None:
        self._endpoint = endpoint
        self._token = token
        self._timeout = ClientTimeout(total=timeout)
        self.logger = logging.getLogger(__name__)

    def _session(self) -> ClientSession:
        headers = {"Authorization": f"Bearer {self._token}"}
        if self._endpoint.startswith("unix://"):
            return ClientSession(connector=UnixConnector(path=self._endpoint[len("unix://"):]), headers=headers,
                                 timeout=self._timeout)
        return ClientSession(headers=headers, timeout=self._timeout)

    def _url(self, path: str) -> str:
        base = "http://localhost" if self._endpoint.startswith("unix://") else self._endpoint
        return f"{base}{path}"

    async def _post(self, path: str, body: dict) -> BridgeResult:
        # FILL IN: async with self._session() as s, s.post(self._url(path), json=body) as resp → status mapping:
        # 200 ok; 400 reason=(await resp.json()).get("error", "invalid_body"); 401/404/409 via _STATUS_REASON;
        # ClientConnectorError / asyncio.TimeoutError / OSError → BridgeResult(ok=False, status=0, reason="unreachable") — never raise.
        raise NotImplementedError

    async def resolve_gate(self, run_id: str, gate_id: str, *, resolution: str, resolved_by: str,
                           comment: str = "", answers: Optional[dict[str, str]] = None) -> BridgeResult:
        body = ResolveGateRequest(resolution=resolution, resolved_by=resolved_by, comment=comment,
                                  answers=dict(answers or {})).model_dump()
        return await self._post(f"/runs/{run_id}/gates/{gate_id}/resolve", body)

    async def cancel(self, run_id: str, *, requested_by: str) -> BridgeResult:
        return await self._post(f"/runs/{run_id}/cancel", CancelRunRequest(requested_by=requested_by).model_dump())

    async def probe(self) -> bool:
        """Any HTTP response (even 401/404) means the child is listening; a connection error means it is not."""
        # FILL IN: GET self._url("/") inside try/except (ClientConnectorError, asyncio.TimeoutError, OSError) → False — used by re-attach (AC13).
        raise NotImplementedError
```
**Why this shape**: request bodies come from the library's own Pydantic models so the wire contract cannot drift (spec G4 "reuse the existing gate contract"); `UnixConnector` needs a dummy `http://localhost` URL; the token header is unconditional (S4).

### `packages/ai-parrot-integrations/tests/integrations/devloop/fake_child.py` (CREATE)
```python
"""Fake headless child for tests: prints the handshake, serves the library routes with a stub runner, exits.

Usage (spawned by tests): python fake_child.py --brief B --yes --headless --run-id R --command-socket S
Env: PARROT_DEVLOOP_COMMAND_TOKEN (required in Authorization header), FAKE_CHILD_EXIT (default 0),
FAKE_CHILD_NO_HANDSHAKE=1 (exit 3 without printing), FAKE_CHILD_SPAM=1 (write 1 MiB to stdout/stderr after handshake).
"""
from __future__ import annotations

import argparse, asyncio, json, os, sys

from aiohttp import web

from parrot.flows.dev_loop.commands import register_command_routes  # verified: commands.py:208


class _StubRunner:
    """Enough of DevLoopRunner for resolve_gate_handler / cancel_run_handler (commands.py:77,163)."""

    def __init__(self) -> None:
        self.resolved: list[tuple] = []
        self.cancelled = asyncio.Event()

    async def resolve_gate(self, run_id, gate_id, resolution, resolved_by, comment="", origin=None, answers=None):
        # FILL IN: raise GateAlreadyResolvedError on a second call for the same gate_id; raise ValueError when
        # gate_id startswith "oq-" and not answers (answers_required); record and return a stub with model_dump(mode="json")
        # — bounded by commands.py:77-160 error branches.
        raise NotImplementedError

    async def cancel_run(self, run_id, requested_by):
        self.cancelled.set()
        return _Envelope()


class _Envelope:
    def model_dump(self, mode: str = "json") -> dict:
        return {"ok": True}


@web.middleware
async def _auth(request, handler):
    if request.headers.get("Authorization") != f"Bearer {os.environ.get('PARROT_DEVLOOP_COMMAND_TOKEN', '')}":
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def main(ns: argparse.Namespace) -> int:
    if os.environ.get("FAKE_CHILD_NO_HANDSHAKE"):
        print("boom", file=sys.stderr); return 3
    app = web.Application(middlewares=[_auth]); runner = _StubRunner(); register_command_routes(app, runner)
    app_runner = web.AppRunner(app); await app_runner.setup()
    await web.UnixSite(app_runner, ns.command_socket).start()
    print(json.dumps({"event": "ready", "run_id": ns.run_id, "command_endpoint": f"unix://{ns.command_socket}",
                      "kind": "bug", "pid": os.getpid()}), flush=True)
    # FILL IN: FAKE_CHILD_SPAM → write 1 MiB to stdout and stderr; then wait for runner.cancelled or 30 s; cleanup site
    # and socket; return int(os.environ.get("FAKE_CHILD_EXIT", 0)) (2 when cancelled).
    raise NotImplementedError


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--brief"); p.add_argument("--yes", action="store_true")
    p.add_argument("--headless", action="store_true"); p.add_argument("--run-id"); p.add_argument("--command-socket")
    sys.exit(asyncio.run(main(p.parse_args())))
```
**Why this shape**: it is the real library routes behind the real Unix site, so `test_bridge.py` covers the actual wire contract, not a mock; the stub runner reproduces the three error branches the handlers translate (400/404/409).

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_process.py` (CREATE)
```python
"""Tests for HeadlessRunProcess (TASK-3202) using fake_child.py."""
import os, sys
from pathlib import Path

import pytest

from parrot.integrations.devloop.models import DevLoopIntegrationConfig, SpawnError
from parrot.integrations.devloop.process import HeadlessRunProcess

_CHILD = Path(__file__).with_name("fake_child.py")


def _cfg(tmp_path) -> DevLoopIntegrationConfig:
    return DevLoopIntegrationConfig(name="t", enabled=True, repo_path=str(tmp_path), command=[sys.executable, str(_CHILD)])


async def _spawn(tmp_path, **env):
    os.environ.update(env)
    try:
        return await HeadlessRunProcess.spawn(config=_cfg(tmp_path), run_id="run-t1", brief_path=str(tmp_path / "b.json"),
                                              socket_path=str(tmp_path / "s.sock"), port=None, token="tok")
    finally:
        for k in env: os.environ.pop(k, None)


async def test_spawn_reads_handshake(tmp_path):
    proc = await _spawn(tmp_path)
    hs = await proc.wait_ready(timeout=20)
    assert hs.run_id == "run-t1" and hs.command_endpoint.startswith("unix://")
    await proc.terminate(); assert await proc.wait() in (2, -15)


async def test_no_handshake_raises_spawn_error(tmp_path):
    proc = await _spawn(tmp_path, FAKE_CHILD_NO_HANDSHAKE="1")
    with pytest.raises(SpawnError) as exc:
        await proc.wait_ready(timeout=20)
    assert exc.value.exit_code == 3 and "boom" in exc.value.stderr_tail


# FILL IN: test_wait_ready_timeout_kills_child (FAKE_CHILD hang before handshake variant), test_pipes_drained
# (FAKE_CHILD_SPAM=1 then wait() returns; stderr_tail ≤ 4096 chars), test_cleanup_removes_socket_and_brief — AC4/AC14.
```

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_bridge.py` (CREATE)
```python
"""Tests for LoopbackRestChannel against the real library routes on a UnixSite (TASK-3202)."""
import pytest
from aiohttp import web

from parrot.flows.dev_loop.commands import register_command_routes
from parrot.integrations.devloop.bridge import LoopbackRestChannel


@pytest.fixture
async def child_site(tmp_path):
    # FILL IN: build an app with the same _auth middleware + _StubRunner as fake_child.py (import them from
    # tests.integrations.devloop.fake_child), register_command_routes, start web.UnixSite at tmp_path/"c.sock",
    # yield the socket path, cleanup — bounded by commands.py:208-224.
    raise NotImplementedError


async def test_status_mapping(child_site):
    ch = LoopbackRestChannel(f"unix://{child_site}", token="tok")
    assert (await ch.resolve_gate("r", "g1", resolution="approved", resolved_by="slack:T:U")).ok
    assert (await ch.resolve_gate("r", "g1", resolution="approved", resolved_by="x")).reason == "already_resolved"
    assert (await ch.resolve_gate("r", "oq-1", resolution="approved", resolved_by="x")).reason == "answers_required"
    assert (await ch.cancel("r", requested_by="x")).ok
    assert LoopbackRestChannel(f"unix://{child_site}", token="bad") and (await LoopbackRestChannel(f"unix://{child_site}", token="bad").probe())


async def test_unreachable(tmp_path):
    res = await LoopbackRestChannel(f"unix://{tmp_path}/none.sock", token="t").cancel("r", requested_by="x")
    assert not res.ok and res.reason == "unreachable" and res.status == 0
```

### FILL IN checklist
- [ ] `process.py::_drain` — ring buffer + handshake detection; bounded by spec §7 handshake contract / AC4.
- [ ] `process.py::wait_ready` — race handshake vs exit vs timeout; bounded by AC14.
- [ ] `process.py::terminate` — SIGTERM → SIGKILL after grace; bounded by S7/S8.
- [ ] `bridge.py::_post` — status/reason mapping, never raise; bounded by `commands.py:77-207`.
- [ ] `bridge.py::probe` — any response ⇒ True; bounded by AC13 re-attach.
- [ ] `fake_child.py::_StubRunner.resolve_gate`, `main` tail — error branches, spam mode, cancel exit 2.
- [ ] Stubbed tests in both test files (+ `child_site` fixture).

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/devloop/test_process.py packages/ai-parrot-integrations/tests/integrations/devloop/test_bridge.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/devloop packages/ai-parrot-integrations/tests/integrations/devloop`
- [ ] Imports work: `from parrot.integrations.devloop import HeadlessRunProcess, LoopbackRestChannel, RunCommandChannel`
- [ ] Spec AC14 (crash before handshake ⇒ exit code + stderr tail) and AC15 (bearer token sent in both modes; 401 mapped) hold; a child writing 1 MiB never blocks (S8)

---

## Test Specification

See the three test blueprints above.

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
7. **Move this file** to `sdd/tasks/completed/TASK-3202-devloop-subprocess-and-command-channel.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-12
**Notes**: Implemented `process.py` (`HeadlessHandshakeView`,
`HeadlessRunProcess.spawn`/`wait_ready`/`wait`/`stderr_tail`/`terminate`/
`cleanup`) — `_drain` validates every pre-handshake line as
`HeadlessHandshakeView` JSON (logs non-matching lines at DEBUG and keeps
reading, rather than resolving on the very first line unconditionally, to
tolerate startup log noise from the real child), with a byte-bounded ring
buffer that also truncates a single oversized line to its tail.
`wait_ready` races the handshake future against `proc.wait()` and maps
EOF/exit/timeout to `SpawnError`; `terminate` signals only the child's own
pid (SIGTERM → SIGKILL after `grace`), never a process group. Implemented
`bridge.py` (`RunCommandChannel` Protocol, `LoopbackRestChannel` with the
exact status→reason mapping, bodies built from the library's own
`ResolveGateRequest`/`CancelRunRequest`). `fake_child.py`'s `_StubRunner`
reproduces the three `resolve_gate_handler` error branches (already
resolved, `answers_required` for `oq-`-prefixed gates) and its `get_host`
returns `None` so the handler's 409 branch degrades safely. Discovered
during testing: pre-creating the socket path before spawn breaks the real
child's `UnixSite.start()` (bind fails against an existing regular file)
— fixed the test to assert the socket's existence only after the real
child creates it, not before.
`pytest packages/ai-parrot-integrations/tests/integrations/devloop -q`:
43 passed (test_process.py exercises real subprocesses end to end,
~15s). `ruff check` and `black --check` clean on all touched/created
files. Imports verified: `from parrot.integrations.devloop import
HeadlessRunProcess, LoopbackRestChannel, RunCommandChannel`.

**Deviations from spec**: none.
