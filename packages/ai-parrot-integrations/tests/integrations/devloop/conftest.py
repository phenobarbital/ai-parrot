"""Shared fixtures for the dev-loop integration tests (FEAT-555).

``fakeredis`` is not a declared dependency anywhere in this workspace; this
module provides an in-process stand-in mirroring the core dev-loop tests'
``_FakeStreamsRedis`` (packages/ai-parrot/tests/flows/dev_loop/test_streaming.py:26),
extended with the hash/set/expire subset ``RunRegistry`` (TASK-3203) needs.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import pytest

if TYPE_CHECKING:
    from parrot.integrations.devloop.models import DevLoopIntegrationConfig  # TASK-3200


class FakeRedis:
    """In-process stand-in for ``redis.asyncio.Redis`` (decode_responses=True).

    Supports the subset used by TASK-3203/3204: streams (``xadd``/``xread``/
    ``xrange``/``keys``), hashes (``hset``/``hgetall``/``delete``), sets
    (``sadd``/``srem``/``smembers``) and ``expire``.
    """

    def __init__(self) -> None:
        self._streams: Dict[str, List[Tuple[str, Dict[str, str]]]] = {}
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._sets: Dict[str, set] = {}
        self.expirations: Dict[str, int] = {}
        self._counter = 0
        # TASK-3210: >0 ⇒ the next N calls to xread raise ConnectionError,
        # simulating a transient Redis blip mid-tail (test_tail_survives_redis_loss).
        self.fail_next_xread = 0

    # -- streams ----------------------------------------------------------

    async def xadd(self, key: str, fields: Dict[str, str], **_kw: Any) -> str:
        self._counter += 1
        entry_id = f"{int(time.time() * 1000)}-{self._counter}"
        self._streams.setdefault(key, []).append((entry_id, fields))
        return entry_id

    async def xrange(
        self, name: str, *, min: str = "-", max: str = "+"
    ) -> List[Tuple[str, Dict[str, str]]]:  # noqa: A002
        return list(self._streams.get(name, []))

    async def xread(
        self,
        streams: Dict[str, str],
        *,
        block: Optional[int] = None,
        count: Optional[int] = None,
    ) -> List[Tuple[str, List[Tuple[str, Dict[str, str]]]]]:
        if self.fail_next_xread > 0:
            self.fail_next_xread -= 1
            raise ConnectionError("simulated redis blip (fail_next_xread)")
        # "$" only ever reaches xread here when state_replay() found the
        # stream completely empty (it otherwise always rewrites the
        # multiplexer's cursor to a real last-entry id first — streaming.py
        # state_replay:317) — so resolving it to "" (accept anything) is
        # safe and lets a freshly-launched run's first live tail observe
        # events added after it started, instead of never returning
        # anything (TASK-3210 e2e Slack flow needs this to be observable).
        resolved: Dict[str, str] = {key: ("" if cursor == "$" else cursor) for key, cursor in streams.items()}

        def _collect() -> List[Tuple[str, List[Tuple[str, Dict[str, str]]]]]:
            out: List[Tuple[str, List[Tuple[str, Dict[str, str]]]]] = []
            for key, cursor in resolved.items():
                entries = self._streams.get(key, [])
                collected = [(entry_id, fields) for entry_id, fields in entries if entry_id > cursor]
                if count:
                    collected = collected[:count]
                if collected:
                    out.append((key, collected))
            return out

        result = _collect()
        if not result and block:
            await asyncio.sleep(block / 1000.0)
            result = _collect()  # entries added during the "block" wait are still observed
        return result

    async def keys(self, pattern: str) -> List[str]:
        # Very rough wildcard handling: only support a trailing '*'.
        names = set(self._streams) | set(self._hashes) | set(self._sets)
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return sorted(k for k in names if k.startswith(prefix))
        return sorted(k for k in names if k == pattern)

    # -- hashes -------------------------------------------------------------

    async def hset(self, key: str, mapping: Optional[Dict[str, str]] = None, **kwargs: Any) -> int:
        data = dict(mapping or {})
        data.update(kwargs)
        self._hashes.setdefault(key, {}).update(data)
        return len(data)

    async def hget(self, key: str, field: str) -> Optional[str]:
        return self._hashes.get(key, {}).get(field)

    async def hgetall(self, key: str) -> Dict[str, str]:
        return dict(self._hashes.get(key, {}))

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            for store in (self._streams, self._hashes, self._sets):
                if key in store:
                    del store[key]
                    removed += 1
            self.expirations.pop(key, None)
        return removed

    # -- sets -----------------------------------------------------------------

    async def sadd(self, key: str, *members: str) -> int:
        s = self._sets.setdefault(key, set())
        before = len(s)
        s.update(members)
        return len(s) - before

    async def srem(self, key: str, *members: str) -> int:
        s = self._sets.get(key, set())
        before = len(s)
        s.difference_update(members)
        return before - len(s)

    async def smembers(self, key: str) -> set:
        return set(self._sets.get(key, set()))

    # -- misc ----------------------------------------------------------------

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_redis() -> FakeRedis:
    """Fresh fake Redis per test."""
    return FakeRedis()


class SlackApiRecorder:
    """Records every ``SlackAgentWrapper._slack_api`` call; returns canned Web API responses.

    Installed via the ``slack_api`` fixture, which monkeypatches the
    single seam ``SlackAgentWrapper._slack_api`` uses for every outbound
    call (``post_message``/``update_message``/``open_dm`` all funnel
    through it — wrapper.py:618) so no test ever hits the real network.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def __call__(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append((method, payload))
        if method == "conversations.open":
            return {"ok": True, "channel": {"id": "D1"}}
        return {"ok": True, "ts": f"1.{len(self.calls)}", "channel": payload.get("channel", "C1")}


@pytest.fixture
def slack_api(monkeypatch) -> SlackApiRecorder:
    """Recorder installed over ``SlackAgentWrapper._slack_api`` — no test ever calls slack.com."""
    from parrot.integrations.slack.wrapper import SlackAgentWrapper  # verified: slack/wrapper.py:75

    rec = SlackApiRecorder()
    monkeypatch.setattr(SlackAgentWrapper, "_slack_api", rec)
    return rec


@pytest.fixture
def devloop_config(tmp_path) -> "DevLoopIntegrationConfig":
    """A minimal, valid ``devloop:`` config rooted at a per-test tmp dir."""
    from parrot.integrations.devloop.models import DevLoopIntegrationConfig as _DevLoopIntegrationConfig

    return _DevLoopIntegrationConfig(
        name="t",
        enabled=True,
        repo_path=str(tmp_path),
        socket_dir=str(tmp_path / "sock"),
        cancel_grace_seconds=0.2,
        tail_drain_seconds=0.2,
        handshake_timeout_seconds=20.0,
        default_acceptance_criteria=[{"kind": "shell", "name": "unit", "command": "pytest -q"}],
    )


@pytest.fixture
def fake_child() -> str:
    """Path to ``fake_child.py`` — a tiny real headless-child stand-in (TASK-3202 pattern).

    Prints the ``HeadlessHandshake`` line, serves the real
    ``register_command_routes`` over a Unix socket with a stub runner,
    and exits when cancelled or after ``FAKE_CHILD_EXIT`` (env-configurable).
    """
    from pathlib import Path as _Path

    return str(_Path(__file__).parent / "fake_child.py")
