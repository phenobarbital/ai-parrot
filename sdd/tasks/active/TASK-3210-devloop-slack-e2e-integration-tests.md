# TASK-3210: End-to-end integration tests — cross-process contract, Slack flows, auth parity, packaging

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3198, TASK-3208
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests (design research S11). Every earlier task tests its
module in isolation with stubs. This task exercises the real seams: a genuine
headless child over a Unix socket, the Slack adapter driven end-to-end with a
recorded Web API, restart re-attach, Redis loss, crash classification, auth
parity between webhook and Socket Mode, and the `[devloop]` packaging extra.
It lands last because it needs the core lane (TASK-3198) and the Slack lane
(TASK-3208, manager wiring) on the branch.

---

## Scope

Create the fixtures and the nine integration tests named in spec §4:

- `packages/ai-parrot/tests/cli/devloop/integration/test_headless_contract.py`:
  `test_cross_process_command_contract`, `test_headless_child_end_to_end_stub_runner`,
  `test_child_crash_before_terminal_action`.
- `packages/ai-parrot-integrations/tests/integrations/devloop/conftest.py`: fixtures
  `fake_child` (script path), `fake_redis` (in-process streams fake), `slack_api`
  (recorder), `devloop_config`.
- `packages/ai-parrot-integrations/tests/integrations/devloop/test_e2e_service.py`:
  `test_tail_survives_redis_loss`, `test_restart_reattach`.
- `packages/ai-parrot-integrations/tests/integrations/devloop/test_e2e_slack.py`:
  `test_slack_feature_run_thread_flow`, `test_slack_bug_confirm_then_run`,
  `test_slack_auth_parity_webhook_vs_socket`.
- `packages/ai-parrot-integrations/tests/integrations/devloop/test_packaging.py`:
  `test_devloop_extra_installs_redis`.

**NOT in scope**: fixing bugs found in other modules (report them in the
Completion Note and open follow-ups); unit tests already owned by earlier tasks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/cli/devloop/integration/test_headless_contract.py` | CREATE | Real `parrot devloop run --headless` child with a stub runner (env `PARROT_DEVLOOP_STUB_RUNNER=1`) |
| `packages/ai-parrot/tests/cli/devloop/integration/_stub_runner.py` | CREATE | Importable stub runner + helper used by the child under the env flag |
| `packages/ai-parrot-integrations/tests/integrations/devloop/__init__.py` | CREATE | package marker |
| `packages/ai-parrot-integrations/tests/integrations/devloop/conftest.py` | CREATE | shared fixtures |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_e2e_service.py` | CREATE | service-level e2e |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_e2e_slack.py` | CREATE | Slack-level e2e |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_packaging.py` | CREATE | extra metadata |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# core
from parrot.cli.devloop.headless import HeadlessHandshake, HeadlessExit, run_headless   # TASK-3198
from parrot.flows.dev_loop.commands import ResolveGateRequest, CancelRunRequest          # verified: commands.py:46,64
from parrot.flows.dev_loop.session_state import SessionHost, ApprovalGate, ActionEnvelope, session_channel   # verified: session_state.py:1134,257,626,88
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer                         # verified: streaming.py:73
from aiohttp import ClientSession, UnixConnector                                          # core dep
# integrations (all created by the Slack/integration lanes — verify each landed before use)
from parrot.integrations.devloop.service import DevLoopDispatchService                    # TASK-3204
from parrot.integrations.devloop.models import DevLoopIntegrationConfig, DevLoopCommand, Requester, RunRecord   # TASK-3200
from parrot.integrations.devloop.tail import RunStateTail                                 # TASK-3203
from parrot.integrations.devloop.registry import RunRegistry                              # TASK-3203
from parrot.integrations.slack import SlackAgentWrapper, SlackAgentConfig, SlackSocketHandler   # verified: slack/__init__.py:3-20
from parrot.integrations.slack.devloop import register_devloop                            # TASK-3206
from parrot.integrations.manager import IntegrationBotManager                             # verified: manager.py:63
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/flows/dev_loop/test_streaming.py — REUSE, do not depend on `fakeredis` (not a dependency; the
# dev_loop tests use this in-process fake, see test_streaming_state_view.py:1-4)
class _FakeStreamsRedis:                       # line 26
    def __init__(self) -> None                 # line 27
    async def xadd(...)                        # line 31
    async def xread(...)                       # line 44
# → copy this class into the new conftest (tests are not importable across packages) and add the extra methods the
#   registry needs (hset/hgetall/sadd/smembers/srem/expire/ping) as simple dict-backed coroutines.

# live-stream entry shape the tail consumes: fields {"envelope": ActionEnvelope.model_dump_json()}   # streaming.py:386-389
# terminal action types: {"run/closed", "run/cancelled"}                                             # streaming.py:360

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
class SessionHost:                                                                   # line 1134
    def open_gate(self, *, kind, node_id, title, instructions="", payload_ref="", ttl_seconds=None, on_expiry="fail", questions=None) -> Tuple[str, ActionEnvelope]   # line 1290
    def resolve_gate(self, gate_id, resolution, resolved_by, comment="", origin=None, answers=None) -> ActionEnvelope        # line 1226
    async def wait_gate(self, gate_id: str) -> ApprovalGate                          # line 1374

# Slack payload shapes used by the wrapper (verified):
#   slash command form fields: command, text, user_id, channel_id, team_id, response_url, trigger_id      # wrapper.py:341-347
#   signature: verify_slack_signature_raw(raw_body, headers, signing_secret)                                 # wrapper.py:333
#   interactive route: POST form field "payload" = JSON (block_actions / view_submission)                  # interactive.py:137-140
#   Socket Mode entry points: SlackSocketHandler._handle_event(payload), _handle_slash_command(payload), _handle_interactive(payload)   # socket_handler.py:173,266,352

# packages/ai-parrot-integrations/pyproject.toml — extras table; `[devloop]` is added by TASK-3208
```

### Does NOT Exist
- ~~`fakeredis`~~ — not a dependency of any package here; use the in-process streams fake pattern from `tests/flows/dev_loop/test_streaming.py:26`.
- ~~a shared cross-package test helper module~~ — `packages/ai-parrot/tests` is not importable from `packages/ai-parrot-integrations/tests`; duplicate the tiny fake in the new `conftest.py`.
- ~~`PARROT_DEVLOOP_STUB_RUNNER` handling inside `headless.py`~~ — NOT present; this task adds the hook by monkeypatching `parrot.cli.devloop.bootstrap.build_runtime` / `build_dev_flow_runtime` via a `sitecustomize`-style import in the child (`_stub_runner.py` sets them when the env var is set and the child is launched with `PYTHONPATH` including the test dir). Do not modify `headless.py` for tests.
- ~~real Slack network calls~~ — every `chat.postMessage` / `chat.update` / `views.open` / `conversations.open` / `users.info` must be intercepted by the `slack_api` recorder (monkeypatch `aiohttp.ClientSession.post` or the wrapper's post/update helpers).
- ~~a running Redis~~ — none required; the tail and registry take an injected client.

---

## Implementation Notes

### Pattern to Follow
```python
# Spawning the real child from a test (mirrors what HeadlessRunProcess does in production)
proc = await asyncio.create_subprocess_exec(
    sys.executable, "-m", "parrot.cli", "devloop", "run", "--brief", brief, "--yes", "--headless",
    "--command-socket", sock, "--run-id", "run-e2e1",
    env={**os.environ, "PARROT_DEVLOOP_COMMAND_TOKEN": "tok", "PARROT_DEVLOOP_STUB_RUNNER": "1", "PYTHONPATH": stub_dir},
    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
)
line = await asyncio.wait_for(proc.stdout.readline(), 60)
hs = HeadlessHandshake.model_validate_json(line)
```

### Key Constraints
- Mark every child-spawning test `@pytest.mark.integration` and skip when `shutil.which("parrot") is None` and `python -m parrot.cli` is unavailable (keep CI green without the console entry point).
- The stub runner in the child must open ONE `open_questions` gate via a real `SessionHost` (so `resolve_gate` semantics — first-writer 409 — are real), publish to the injected fake or a real Redis when `REDIS_URL` is set, and complete when the gate is approved.
- Timeouts everywhere (`asyncio.wait_for`, ≤60 s); always `proc.kill()` in `finally`.
- Slack e2e tests drive `SlackAgentWrapper` through its aiohttp routes (`aiohttp.test_utils.TestClient`) for webhook mode and call `SlackSocketHandler._handle_*` directly for Socket Mode, with the same payloads, asserting identical outcomes (AC17/AC20).

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_streaming.py:26-88` — fake streams client
- `packages/ai-parrot/tests/flows/dev_loop/test_commands.py` — REST contract expectations (200/400/404/409)
- `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_whitelist_integration.py` — TestClient-driven wrapper tests
- `packages/ai-parrot/tests/cli/devloop/integration/conftest.py` — existing integration fixtures for the CLI

---

## Implementation Blueprint

### Steps (in order)
1. Write `_stub_runner.py` (child-side stub) and `conftest.py` fixtures — *why*: every test depends on them.
2. Write the headless contract tests — *why*: they validate TASK-3198's contract against a real process.
3. Write the service e2e tests (Redis loss, restart) — *why*: AC13 and the tail backoff are only observable end-to-end.
4. Write the Slack e2e tests — *why*: AC6/AC7/AC10/AC17/AC20 across both connection modes.
5. Write the packaging test — *why*: S12 / AC2.

### `packages/ai-parrot/tests/cli/devloop/integration/_stub_runner.py` (CREATE)
```python
"""Child-side stub runtime for headless e2e tests (activated by PARROT_DEVLOOP_STUB_RUNNER=1 via PYTHONPATH)."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from parrot.flows.dev_loop.session_state import SessionHost  # verified: session_state.py:1134


@dataclass
class _StubRuntime:
    runner: Any


class StubRunner:
    """Opens one open_questions gate on a real SessionHost, waits for it, then completes."""

    def __init__(self) -> None:
        self._hosts: dict[str, SessionHost] = {}

    def get_host(self, run_id: str):
        return self._hosts.get(run_id)

    async def resolve_gate(self, run_id, gate_id, resolution, resolved_by, comment="", origin=None, answers=None):
        return self._hosts[run_id].resolve_gate(gate_id, resolution, resolved_by, comment, origin, answers)

    async def cancel_run(self, run_id, requested_by):
        # FILL IN: apply RunCancelled through the host (mirror runner.py:1064-1067) — bounded by "real cancel semantics"
        raise NotImplementedError("FILL IN")

    async def run(self, brief, *, run_id=None, **_):
        # FILL IN: build a SessionHost for run_id (see how DevLoopRunner creates hosts around runner.py:1189+; the sink may be
        # a no-op when REDIS_URL is unset), open_gate(kind="open_questions", node_id="ideation", title="Q", questions=["q1"]),
        # await wait_gate, then return an object with .status == "completed" — bounded by "one real gate per child"
        raise NotImplementedError("FILL IN")


async def _stub_build(**_):
    return _StubRuntime(runner=StubRunner())


if os.environ.get("PARROT_DEVLOOP_STUB_RUNNER") == "1":
    import parrot.cli.devloop.bootstrap as _b

    _b.build_runtime = _stub_build  # type: ignore[assignment]
    _b.build_dev_flow_runtime = _stub_build  # type: ignore[assignment]
```
**Why this shape**: the child imports real `headless.py`; only the runtime builders are swapped, so the socket, bearer, handshake, cancel wrap and exit codes are the production code paths.

### `packages/ai-parrot/tests/cli/devloop/integration/test_headless_contract.py` (CREATE)
```python
"""FEAT-555 TASK-3210 — real headless child over a Unix socket."""
from __future__ import annotations

import asyncio, json, os, sys
from pathlib import Path

import pytest
from aiohttp import ClientSession, UnixConnector

from parrot.cli.devloop.headless import HeadlessHandshake

STUB_DIR = str(Path(__file__).parent)
pytestmark = pytest.mark.integration


async def _spawn(tmp_path, run_id="run-e2e1", token="tok"):
    brief = tmp_path / "b.json"
    brief.write_text(json.dumps({"kind": "new_feature", "title": "t", "description": "d"}))
    sock = str(tmp_path / "c.sock")
    env = {**os.environ, "PARROT_DEVLOOP_COMMAND_TOKEN": token, "PARROT_DEVLOOP_STUB_RUNNER": "1",
           "PYTHONPATH": STUB_DIR + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import _stub_runner; from parrot.cli import cli; cli()", "devloop", "run",
        "--brief", str(brief), "--yes", "--headless", "--command-socket", sock, "--run-id", run_id,
        env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
    line = await asyncio.wait_for(proc.stdout.readline(), 60)
    return proc, HeadlessHandshake.model_validate_json(line), sock


@pytest.mark.asyncio
async def test_cross_process_command_contract(tmp_path):
    proc, hs, sock = await _spawn(tmp_path)
    try:
        assert hs.command_endpoint == f"unix://{sock}"
        async with ClientSession(connector=UnixConnector(path=sock)) as s:
            h = {"Authorization": "Bearer tok"}
            # FILL IN: (1) no bearer ⇒ 401; (2) resolve the stub's gate with answers ⇒ 200; (3) second resolve ⇒ 409;
            # (4) child exits 0 within 60 s and the socket file is gone — bounded by AC4/AC7/AC9/AC15
            pass
    finally:
        if proc.returncode is None:
            proc.kill()


@pytest.mark.asyncio
async def test_headless_child_end_to_end_stub_runner(tmp_path):
    # FILL IN: same spawn; cancel with bearer ⇒ exit code 2 within cancel grace — bounded by AC21
    pytest.skip("FILL IN")


@pytest.mark.asyncio
async def test_child_crash_before_terminal_action(tmp_path):
    # FILL IN: spawn, then proc.kill() after the handshake; assert returncode != 0 and no "run/closed" published;
    # parent-side classification is tested in test_e2e_service via HeadlessRunProcess — bounded by AC14
    pytest.skip("FILL IN")
```
**Why**: this is the only test in the feature that exercises the real process boundary.

### `packages/ai-parrot-integrations/tests/integrations/devloop/conftest.py` (CREATE)
```python
"""Shared fixtures for FEAT-555 e2e tests (no network, no Redis server)."""
from __future__ import annotations

from typing import Any

import pytest

from parrot.integrations.devloop.models import DevLoopIntegrationConfig  # TASK-3200


class FakeStreamsRedis:
    """Dict-backed subset of redis.asyncio used by RunStateTail + RunRegistry.

    Copy of packages/ai-parrot/tests/flows/dev_loop/test_streaming.py:26 (`_FakeStreamsRedis`) plus hash/set ops.
    """

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.fail_next_xread = 0  # >0 ⇒ raise ConnectionError on xread (for test_tail_survives_redis_loss)

    # FILL IN: xadd/xread (copy from test_streaming.py:31-88), hset/hgetall/sadd/smembers/srem/expire/ping/aclose — bounded by
    # "only what tail.py and registry.py call" (read both modules first)


class SlackApiRecorder:
    """Records outgoing Slack Web API calls; returns canned ts / ids."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, payload))
        # FILL IN: return {"ok": True, "ts": f"1.{len(self.calls)}", "channel": payload.get("channel", "C1")} etc. — bounded by
        # the response fields wrapper.post_message/update_message/open_dm read (TASK-3205)
        return {"ok": True}


@pytest.fixture
def fake_redis() -> FakeStreamsRedis:
    return FakeStreamsRedis()


@pytest.fixture
def slack_api(monkeypatch) -> SlackApiRecorder:
    rec = SlackApiRecorder()
    # FILL IN: monkeypatch the wrapper's Web API call path (post_message/update_message/open_dm internals) to rec — bounded by "no network"
    return rec


@pytest.fixture
def devloop_config(tmp_path) -> DevLoopIntegrationConfig:
    return DevLoopIntegrationConfig(
        enabled=True, repo_path=str(tmp_path), socket_dir=str(tmp_path / "sock"),
        default_acceptance_criteria=[{"kind": "shell", "name": "unit", "command": "pytest -q"}],
    )


@pytest.fixture
def fake_child(tmp_path) -> str:
    """Path to a tiny python script that prints a handshake for argv's --command-socket and serves the command routes."""
    # FILL IN: write the script (aiohttp UnixSite + bearer + stub resolve/cancel + configurable exit code via env) — bounded by
    # the HeadlessHandshake contract (TASK-3198)
    return str(tmp_path / "fake_child.py")
```
**Why**: the fakes are the seam that keeps the e2e tests hermetic while exercising real tail/registry/service code.

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_e2e_service.py` (CREATE)
```python
"""FEAT-555 TASK-3210 — service-level e2e: Redis loss, restart re-attach."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_tail_survives_redis_loss(fake_redis, devloop_config, slack_api):
    # FILL IN: seed gate/opened on flow:{run}:actions; set fake_redis.fail_next_xread=2; run RunStateTail.events();
    # assert one gate_opened event (no duplicates) and that it resumed from last_seen_seq — bounded by §7 "Redis outage" + AC13
    pytest.skip("FILL IN")


@pytest.mark.asyncio
async def test_restart_reattach(fake_redis, devloop_config, slack_api, fake_child):
    # FILL IN: service.dispatch+confirm with fake_child; service.stop(); new DevLoopDispatchService on the same fake_redis;
    # service.start(); publish run/closed on the stream; assert post_terminal was rendered (slack_api.calls) — bounded by AC13
    pytest.skip("FILL IN")
```

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_e2e_slack.py` (CREATE)
```python
"""FEAT-555 TASK-3210 — Slack-level e2e through webhook routes and Socket Mode handlers."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_slack_feature_run_thread_flow(slack_api, devloop_config, fake_redis, fake_child):
    # FILL IN: /devloop --type feature ⇒ ephemeral ack + confirm card; Confirm ⇒ thread root + started; seed gate/opened ⇒ gate card;
    # view_submission with one answer ⇒ resolve via fake_child (200) ⇒ card edited; run/closed ⇒ terminal summary — bounded by AC6/AC7/AC10
    pytest.skip("FILL IN")


@pytest.mark.asyncio
async def test_slack_bug_confirm_then_run(slack_api, devloop_config, fake_redis, fake_child):
    # FILL IN: /devloop --type bug ⇒ confirm card with WorkBrief defaults; Edit modal submission overrides summary; Confirm ⇒ started — bounded by AC10
    pytest.skip("FILL IN")


@pytest.mark.asyncio
async def test_slack_auth_parity_webhook_vs_socket(slack_api, devloop_config):
    # FILL IN: for each of {unsigned webhook interactive, non-whitelisted user slash, non-whitelisted user block_action, non-owner answer}
    # assert the webhook route (aiohttp TestClient) and the Socket Mode handler produce the same rejection and never call the service
    # — bounded by AC8/AC17/AC20
    pytest.skip("FILL IN")
```

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_packaging.py` (CREATE)
```python
"""FEAT-555 TASK-3210 — the [devloop] extra declares redis (design research S12)."""
from __future__ import annotations

from pathlib import Path


def test_devloop_extra_installs_redis():
    root = Path(__file__).resolve().parents[3]  # packages/ai-parrot-integrations
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    block = text.split("devloop = [", 1)[1].split("]", 1)[0]
    assert "redis>=5.0" in block
```
**Why**: cheap, deterministic guard for the install path documented in `docs/integrations/slack-devloop.md`.

### FILL IN checklist
- [ ] `_stub_runner.py::StubRunner.run/cancel_run` — real SessionHost gate; bounded by "one real gate per child"
- [ ] `test_headless_contract.py` — 401 / 200 / 409 / exit 0 / socket removed; cancel ⇒ 2; crash classification; bounded by AC4/AC7/AC9/AC14/AC15/AC21
- [ ] `conftest.py::FakeStreamsRedis` — methods used by tail.py/registry.py; `SlackApiRecorder` responses; `fake_child` script; bounded by "no network, no Redis"
- [ ] `test_e2e_service.py` — Redis loss + re-attach; bounded by AC13
- [ ] `test_e2e_slack.py` — three flows incl. auth parity; bounded by AC6/AC7/AC8/AC10/AC17/AC20

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/devloop/integration packages/ai-parrot-integrations/tests/integrations/devloop -q -m integration`
- [ ] No linting errors: `ruff check` on every new test file
- [ ] Spec AC1/AC2 (suites green), AC13, AC14, AC17, AC20, AC21 exercised end-to-end
- [ ] No test requires network or a running Redis; child-spawning tests skip cleanly when the CLI cannot be launched

---

## Test Specification

> This task IS the test specification — see the blueprint blocks above.

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
7. **Move this file** to `sdd/tasks/completed/TASK-3210-devloop-slack-e2e-integration-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
