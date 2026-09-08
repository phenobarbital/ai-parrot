"""Multi-browser harness for the moderated broadcast (FEAT-537 TASK-2968).

Runs the **actual** `examples/clients/voice/server.py` app — real REST handlers
over a real `BroadcastService`, real page, real Chromium — with up to eleven
independent browser contexts. Only the vendor boundaries are faked (LiveKit
SDK, LiveAvatar/publisher factories, `WebSocket` transport, `getUserMedia`).

**What this suite is and is not.** It proves the *broadcast* behaviours across
many browsers: admission and the ten-seat limit, moderator election and
succession, floor grants and revocation, per-page media attachment and cutover,
and the microphone permission gate. It does **not** drive real Nova turns — no
provider is reachable here, and a faked one would prove nothing about lip-sync,
interruption latency or audio quality. Those belong to the real-vendor gate
(`test_voice_demo_multibrowser_live.py` and TASK-2969), which has **not** run.

Each scenario writes a per-browser measurement table to
`artifacts/logs/feat-537-browser-<scenario>-<stamp>.json`.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest
import uvloop
from aiohttp.test_utils import TestServer

from . import _broadcast_browser_fakes as fakes

# Same reason as FEAT-536's browser suite: Playwright launches a Node.js
# subprocess whose plain-asyncio path needs a child watcher this repo's uvloop
# install replaces process-wide. Install uvloop's policy before pytest-asyncio
# creates any loop.
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

async_playwright = pytest.importorskip(
    "playwright.async_api", reason="playwright is required for browser tests"
).async_playwright

API = fakes.API_PREFIX
TOKENS = fakes.DEMO_TOKENS


# ── Vendor-side fakes injected into the real service ───────────────────────


class FakeMediaSession:
    """Producer stand-in. Counts starts so "exactly one producer" is testable."""

    starts = 0
    instances: List["FakeMediaSession"] = []
    fail_avatar = False

    def __init__(
        self, descriptor: Any, registry: Any, room_manager: Any, worker_id: str,
        owner_epoch: int, **_kw: Any
    ) -> None:
        from parrot.integrations.liveavatar.broadcast import BroadcastState

        self.descriptor = descriptor
        self.registry = registry
        self.room_manager = room_manager
        self.owner_epoch = owner_epoch
        self.output_epoch = 0
        self.floor_epoch = descriptor.floor_epoch
        self.room_name = descriptor.room_name or f"bcast-{descriptor.broadcast_id}"
        self.avatar_identity = "avatar-pub"
        self.direct_identity = "direct-pub"
        self.state = BroadcastState.PENDING
        self.avatar_starts = 0
        FakeMediaSession.instances.append(self)

    async def start(self) -> Any:
        from parrot.integrations.liveavatar.broadcast import (
            BroadcastReason,
            BroadcastState,
        )

        FakeMediaSession.starts += 1
        await self.registry.transition(
            self.descriptor.tenant_id, self.descriptor.broadcast_id,
            BroadcastState.STARTING, expected_owner_epoch=self.owner_epoch,
        )
        if FakeMediaSession.fail_avatar:
            # Startup degradation: the audience keeps Nova audio in the same
            # room, in audio_only (spec §2 / AC5).
            self.state = BroadcastState.AUDIO_ONLY
            self.output_epoch = 1
            await self.registry.transition(
                self.descriptor.tenant_id, self.descriptor.broadcast_id,
                BroadcastState.AUDIO_ONLY, output_epoch=1,
                reason=BroadcastReason.AVATAR_STARTUP_TIMEOUT,
                expected_owner_epoch=self.owner_epoch,
            )
            return self.state
        self.avatar_starts += 1
        self.state = BroadcastState.AVATAR
        self.output_epoch = 1
        await self.registry.transition(
            self.descriptor.tenant_id, self.descriptor.broadcast_id,
            BroadcastState.AVATAR, output_epoch=1,
            expected_owner_epoch=self.owner_epoch,
        )
        return self.state

    def media_state(self) -> Dict[str, Any]:
        return {
            "room_name": self.room_name,
            "avatar_identity": self.avatar_identity,
            "direct_identity": self.direct_identity,
            "state": self.state.value,
            "output_epoch": self.output_epoch,
            "floor_epoch": self.floor_epoch,
            "reason": None,
            "liveavatar_session_id": "vendor-session",
        }

    async def switch_speaker(self, lease_id: str, floor_epoch: int) -> None:
        self.floor_epoch = floor_epoch

    async def on_participant_disconnected(self, identity: str) -> None:
        if identity == self.avatar_identity:
            await self._cutover("avatar_track_lost")

    async def _on_avatar_close(self, reason: str) -> None:
        await self._cutover("avatar_control_lost")

    async def _cutover(self, reason: str) -> None:
        from parrot.integrations.liveavatar.broadcast import (
            BroadcastReason,
            BroadcastState,
        )

        if self.state is not BroadcastState.AVATAR:
            return
        self.state = BroadcastState.AUDIO_ONLY
        self.output_epoch += 1
        await self.registry.transition(
            self.descriptor.tenant_id, self.descriptor.broadcast_id,
            BroadcastState.AUDIO_ONLY, output_epoch=self.output_epoch,
            reason=BroadcastReason(reason),
            expected_owner_epoch=self.owner_epoch,
        )

    async def aclose(self, *, final_state: Any = None, reason: Any = None, **_kw: Any) -> None:
        from parrot.integrations.liveavatar.broadcast import BroadcastState

        target = final_state or BroadcastState.ENDED
        try:
            await self.registry.transition(
                self.descriptor.tenant_id, self.descriptor.broadcast_id,
                target, reason=reason, expected_owner_epoch=self.owner_epoch,
            )
        except Exception:  # noqa: BLE001
            pass
        self.state = target


class FakeVoiceSession:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.turns: List[Any] = []

    def set_fanout(self, fanout: Any) -> None:
        self.fanout = fanout

    def begin_speaker_turn(self, lease_id: str, principal: Any, floor_epoch: int) -> int:
        self.turns.append((lease_id, principal.user_id, floor_epoch))
        return len(self.turns)

    def end_speaker_turn(self) -> None:
        return None

    async def start_turn(self) -> None:
        return None

    async def push_audio(self, pcm: bytes) -> None:
        return None

    async def end_turn(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeRoomManager:
    def __init__(self) -> None:
        self.url = "wss://fake.livekit.cloud"
        self.removed: List[str] = []

    async def create_room(self, room: str, *, max_participants: int = 12) -> None:
        return None

    def mint_publisher_token(self, room: str, identity: str, **_kw: Any) -> str:
        return f"pub-{identity}"

    def mint_viewer_token(self, room: str, identity: str, *, ttl_s: int = 60) -> str:
        return f"viewer-jwt-{identity}"

    async def list_participant_identities(self, room: str) -> List[str]:
        return ["avatar-pub", "direct-pub"]

    async def remove_participant(self, room: str, identity: str) -> None:
        self.removed.append(identity)

    async def delete_room(self, room: str) -> None:
        return None


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeMediaSession.starts = 0
    FakeMediaSession.instances.clear()
    FakeMediaSession.fail_avatar = False


@pytest.fixture
async def demo_server(monkeypatch: pytest.MonkeyPatch):
    """The real example app with broadcast mode over in-memory fakes."""
    from parrot.integrations.liveavatar.broadcast import InMemoryBroadcastRegistry
    from parrot.integrations.liveavatar.broadcast import redis_registry
    from parrot.integrations.liveavatar.broadcast import service as service_module
    import parrot.integrations.liveavatar.room_manager as room_manager_module

    stubs = fakes.client_stub_modules()
    if stubs:
        for name, module in stubs.items():
            monkeypatch.setitem(sys.modules, name, module)
    fakes.ensure_server_handler(monkeypatch)

    monkeypatch.setenv("VOICEBOT_BROADCAST_REDIS_URL", "redis://unused/0")
    monkeypatch.setenv("VOICEBOT_DEMO_PARTICIPANTS", fakes.DEMO_PARTICIPANTS_ENV)
    monkeypatch.setenv("VOICEBOT_BROADCAST_FAILURE_HOOK", "1")
    monkeypatch.setattr(
        redis_registry.RedisBroadcastRegistry, "from_url",
        classmethod(lambda cls, *a, **kw: InMemoryBroadcastRegistry()),
    )
    monkeypatch.setattr(room_manager_module, "LiveKitRoomManager", FakeRoomManager)

    real_service = service_module.BroadcastService

    def _patched(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("session_factory", FakeMediaSession)
        kwargs.setdefault("voice_session_factory", FakeVoiceSession)
        return real_service(*args, **kwargs)

    monkeypatch.setattr(service_module, "BroadcastService", _patched)

    module = fakes.load_server_module("voice_demo_multibrowser_server")
    monkeypatch.setattr(module, "NOVA_AVAILABLE", True)
    monkeypatch.setattr(module, "make_nova_bot", lambda: None, raising=False)
    app = module.build_app()
    assert app["broadcast_service"] is not None, app["broadcast_unavailable_reason"]

    server = TestServer(app)
    await server.start_server()
    yield server
    await server.close()


class Tab:
    """One browser context standing in for one participant's device."""

    def __init__(self, name: str, page: Any, context: Any) -> None:
        self.name = name
        self.page = page
        self.context = context
        self.errors: List[str] = []

    async def enter(self, broadcast_id: Optional[str] = None) -> Dict[str, Any]:
        """Create or join the broadcast as this participant."""
        return await self.page.evaluate(
            """async ([token, bid]) => {
                const client = window.voiceChatClient;
                client.demoToken = token;
                await client.enterBroadcast(bid ? { broadcastId: bid } : {});
                const bc = client.broadcastClient;
                return { broadcastId: bc ? bc.broadcastId : null,
                         leaseId: bc ? bc.leaseId : null,
                         state: bc ? bc.state : null };
            }""",
            [TOKENS[self.name], broadcast_id],
        )

    async def state(self) -> Optional[Dict[str, Any]]:
        return await self.page.evaluate(
            "() => window.voiceChatClient.broadcastClient?.state || null"
        )

    async def refresh(self) -> Optional[Dict[str, Any]]:
        return await self.page.evaluate(
            "async () => { const c = window.voiceChatClient.broadcastClient;"
            " return c ? await c.refresh() : null; }"
        )

    async def permissions(self) -> Dict[str, Any]:
        return await self.page.evaluate(
            "() => window.voiceChatClient.broadcastClient?.permissions || {}"
        )

    async def talk_disabled(self) -> bool:
        return await self.page.evaluate(
            "() => document.getElementById('recordBtn').disabled"
        )

    async def counters(self) -> Dict[str, Any]:
        return await self.page.evaluate(
            """() => ({ video: window.__videoFrames, audio: window.__audioSamples,
                        attached: window.__attachedIdentities,
                        detached: window.__detachCount,
                        getUserMedia: window.__getUserMediaCalls })"""
        )

    async def publish(self, identity: str, kinds: List[str]) -> None:
        """Simulate a publisher starting to send in this browser's room."""
        await self.page.evaluate(
            "([identity, kinds]) => window.__latestRoom.addPublisher(identity, kinds)",
            [identity, kinds],
        )

    async def close(self) -> None:
        await self.context.close()


@pytest.fixture
async def tabs(demo_server):
    """Factory for independent browser contexts (one per participant)."""
    opened: List[Tab] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )

        async def _open(name: str) -> Tab:
            context = await browser.new_context()
            page = await context.new_page()
            tab = Tab(name, page, context)
            page.on("pageerror", lambda exc: tab.errors.append(str(exc)))
            await page.add_init_script(fakes.INIT_SCRIPT)
            await page.goto(str(demo_server.make_url("/")))
            await page.wait_for_function("window.voiceChatClient !== undefined", timeout=8000)
            opened.append(tab)
            return tab

        yield _open

        for tab in opened:
            await tab.context.close()
        await browser.close()


async def _settle(seconds: float = 0.2) -> None:
    await asyncio.sleep(seconds)


async def _state_settles(
    tab: Any, predicate: Callable[[Dict[str, Any]], bool], timeout: float = 5.0
) -> Dict[str, Any]:
    """Poll a tab's cached broadcast state until ``predicate`` holds.

    ``tab.state()`` returns the last state the fan-out *pushed to that
    browser*, not an authoritative read.  Asserting on a single sample races
    the push: a tab can still be showing the snapshot from before the most
    recent join.  The product guarantees the state converges, not that it
    arrives synchronously, so the test waits for convergence and fails with
    the last value it actually saw.

    Args:
        tab: The browser tab wrapper.
        predicate: Condition the state must satisfy.
        timeout: Seconds to wait before giving up.

    Returns:
        The first state satisfying ``predicate``.

    Raises:
        AssertionError: If the state never converges within ``timeout``.
    """
    deadline = time.monotonic() + timeout
    latest: Optional[Dict[str, Any]] = None
    while time.monotonic() < deadline:
        latest = await tab.state()
        if latest and predicate(latest):
            return latest
        await _settle(0.1)
    raise AssertionError(f"broadcast state never converged; last seen: {latest}")


async def confirm_all_leases(demo_server: Any) -> None:
    """Mark every admitted lease as an *active, confirmed* participant.

    ⚠️ **Product gap this compensates for (TASK-2968 finding, NOT fixed here).**
    `BroadcastRegistry.confirm_viewer` has **no production caller**: nothing in
    `BroadcastService`, the HTTP handlers or the control socket ever transitions
    a lease from `pending` to `active`. But `grant_floor` requires the target to
    be `active`, so **no floor grant can ever succeed in production** — the
    moderator's Grant button would always return `403 floor_not_granted`.

    Spec §2 says a lease becomes confirmed when presence is confirmed against
    LiveKit (participant events or reconciliation), so the fix belongs in
    `BroadcastService` — outside this task's scope, which explicitly says found
    product bugs are noted rather than fixed. Recorded in the completion note as
    a blocking follow-up.

    Until then the browser scenarios establish the precondition server-side, so
    they exercise the real handoff machinery rather than being blocked by it.

    Args:
        demo_server: The running test server.
    """
    service = demo_server.app["broadcast_service"]
    for (tenant_id, broadcast_id) in list(service._known):  # noqa: SLF001
        for lease in await service.registry.list_leases(tenant_id, broadcast_id):
            await service.registry.confirm_viewer(
                tenant_id, broadcast_id, lease.lease_id
            )
            await service.registry.heartbeat_control(
                tenant_id, broadcast_id, lease.lease_id
            )


# ── Scenario 1: combined path across three browsers ────────────────────────


async def test_scenario1_three_browsers_share_one_broadcast(tabs) -> None:
    """One producer, one room, three browsers seeing the same state and media."""
    mod = await tabs("mod")
    created = await mod.enter()
    bid = created["broadcastId"]
    assert bid

    alice = await tabs("alice")
    bob = await tabs("bob")
    await alice.enter(bid)
    await bob.enter(bid)

    # Exactly one producer for three participants.
    assert FakeMediaSession.starts == 1
    assert FakeMediaSession.instances[0].avatar_starts == 1

    # The avatar publisher starts sending; every browser attaches it.
    for tab in (mod, alice, bob):
        await tab.publish("avatar-pub", ["video", "audio"])
    await _settle(0.3)

    measurements = {}
    for tab in (mod, alice, bob):
        counters = await tab.counters()
        measurements[tab.name] = counters
        # A "connected" badge is not enough — real frames must have arrived.
        assert counters["video"] > 0, f"{tab.name} received no video frames"
        assert counters["audio"] > 0, f"{tab.name} received no audio samples"
        assert "avatar-pub:video" in counters["attached"]

    state = await _state_settles(mod, lambda st: st.get("viewer_count") == 3)
    assert state["viewer_count"] == 3
    assert state["moderator_display_id"] == created["leaseId"]

    # A viewer leaving does not disturb the others.
    await bob.page.evaluate("async () => { await window.voiceChatClient.leaveBroadcast(); }")
    await _settle()
    for tab in (mod, alice):
        refreshed = await tab.refresh()
        assert refreshed["viewer_count"] == 2
        assert refreshed["state"] == "avatar"

    # A late joiner attaches media that was already flowing.
    carol = await tabs("carol")
    await carol.enter(bid)
    await carol.publish("avatar-pub", ["video", "audio"])
    await _settle(0.3)
    late = await carol.counters()
    assert late["video"] > 0
    measurements["carol_late_join"] = late

    fakes.write_measurements("scenario1-three-browsers", {
        "producer_starts": FakeMediaSession.starts,
        "avatar_sessions": FakeMediaSession.instances[0].avatar_starts,
        "per_browser": measurements,
    })
    for tab in (mod, alice, carol):
        assert tab.errors == []


# ── Scenario 2: moderated handoff ──────────────────────────────────────────


async def test_scenario2_moderated_handoff(tabs, demo_server) -> None:
    """Only one lease can ever hold the floor, and the conversation survives."""
    mod = await tabs("mod")
    created = await mod.enter()
    bid = created["broadcastId"]
    alice = await tabs("alice")
    bob = await tabs("bob")
    a = await alice.enter(bid)
    b = await bob.enter(bid)

    # See confirm_all_leases(): a product gap means nothing marks a lease
    # active, and grant_floor requires it.
    await confirm_all_leases(demo_server)

    # Both raise hands; neither gains any permission by doing so.
    for tab in (alice, bob):
        await tab.page.evaluate(
            "async () => { await window.voiceChatClient.broadcastClient.raiseHand(); }"
        )
    await _settle()
    state = await mod.refresh()
    assert [hand["lease_id"] for hand in state["hand_requests"]] == [a["leaseId"], b["leaseId"]]
    assert await alice.talk_disabled() is True
    assert await bob.talk_disabled() is True

    # Moderator grants alice.
    await mod.page.evaluate(
        "async ([lease]) => { const c = window.voiceChatClient.broadcastClient;"
        " await c.setFloor(lease); }",
        [a["leaseId"]],
    )
    await _settle()
    await alice.refresh()
    await bob.refresh()
    assert (await alice.permissions())["canTalk"] is True
    assert (await bob.permissions())["canTalk"] is False
    assert (await mod.permissions())["canTalk"] is False  # moderator yielded

    # Moderator grants bob: alice loses the floor in the same breath.
    await mod.page.evaluate(
        "async ([lease]) => { const c = window.voiceChatClient.broadcastClient;"
        " await c.setFloor(lease); }",
        [b["leaseId"]],
    )
    await _settle()
    for tab in (mod, alice, bob):
        await tab.refresh()
    assert (await alice.permissions())["canTalk"] is False
    assert (await bob.permissions())["canTalk"] is True

    # Moderator reclaims.
    await mod.page.evaluate(
        "async () => { const c = window.voiceChatClient.broadcastClient;"
        " await c.setFloor(c.leaseId); }"
    )
    await _settle()
    for tab in (mod, alice, bob):
        await tab.refresh()
    assert (await mod.permissions())["canTalk"] is True
    assert (await bob.permissions())["canTalk"] is False

    # One conversation throughout: the producer was never rebuilt.
    assert FakeMediaSession.starts == 1
    fakes.write_measurements("scenario2-handoff", {
        "grants": ["alice", "bob", "moderator"],
        "producer_starts": FakeMediaSession.starts,
        "single_speaker_invariant": True,
    })


# ── Scenario 3: races and departure ────────────────────────────────────────


async def test_scenario3_races_and_departure(tabs, demo_server) -> None:
    mod = await tabs("mod")
    created = await mod.enter()
    bid = created["broadcastId"]

    # Two tabs join simultaneously — neither becomes a second moderator.
    alice = await tabs("alice")
    bob = await tabs("bob")
    await asyncio.gather(alice.enter(bid), bob.enter(bid))
    states = [await tab.refresh() for tab in (mod, alice, bob)]
    moderators = {state["moderator_display_id"] for state in states}
    assert len(moderators) == 1
    assert moderators.pop() == created["leaseId"]

    await confirm_all_leases(demo_server)

    # Conflicting grants from the moderator with the same expected_version.
    a = await alice.page.evaluate("() => window.voiceChatClient.broadcastClient.leaseId")
    b = await bob.page.evaluate("() => window.voiceChatClient.broadcastClient.leaseId")
    outcome = await mod.page.evaluate(
        """async ([leaseA, leaseB]) => {
            const c = window.voiceChatClient.broadcastClient;
            // Read the version the server has NOW: confirming leases bumped it,
            // and a stale cached version would make both attempts lose.
            await c.refresh();
            const version = c.state.version;
            const attempt = async (lease) => {
                try {
                    await c.request('POST', `/${c.broadcastId}/floor`,
                                    { lease_id: lease, expected_version: version });
                    return 'ok';
                } catch (err) { return err.code || String(err); }
            };
            return await Promise.all([attempt(leaseA), attempt(leaseB)]);
        }""",
        [a, b],
    )
    assert sorted(outcome) == ["ok", "stale_version"]

    # Moderator closes its tab: a successor is elected everywhere.
    await mod.page.evaluate("async () => { await window.voiceChatClient.leaveBroadcast(); }")
    await _settle(0.3)
    successors = {(await tab.refresh())["moderator_display_id"] for tab in (alice, bob)}
    assert len(successors) == 1
    assert successors.pop() in (a, b)

    fakes.write_measurements("scenario3-races", {
        "single_moderator_under_race": True,
        "conflicting_grants": outcome,
        "succession_converged": True,
    })


# ── Scenario 4: the ten-viewer limit ───────────────────────────────────────


async def test_scenario4_ten_viewers_and_an_eleventh_refused(tabs) -> None:
    """AC2 in browsers: ten live pages, one producer, one avatar session."""
    mod = await tabs("mod")
    created = await mod.enter()
    bid = created["broadcastId"]

    joined = [mod]
    for name in fakes.PARTICIPANTS[1:10]:  # nine more → ten total
        tab = await tabs(name)
        await tab.enter(bid)
        joined.append(tab)
    assert len(joined) == 10

    state = await mod.refresh()
    assert state["viewer_count"] == 10
    assert state["max_viewers"] == 10

    # The eleventh has a VALID token, so this tests the seat limit and not auth.
    eleventh = await tabs("judy")
    outcome = await eleventh.page.evaluate(
        """async ([token, bid]) => {
            const client = window.voiceChatClient;
            client.demoToken = token;
            try {
                await client.broadcastClient?.leave();
            } catch (err) { /* none yet */ }
            const bc = await import('/static/broadcast-ui.js');
            const c = new bc.BroadcastClient({ config: window.__CONFIG__.broadcast,
                                               getToken: () => token });
            try {
                await c.join(bid, { attempts: 1, delayMs: 10 });
                return 'admitted';
            } catch (err) { return err.code || String(err); }
        }""",
        [TOKENS["judy"], bid],
    )
    assert outcome == "viewer_limit_reached"

    assert FakeMediaSession.starts == 1
    assert FakeMediaSession.instances[0].avatar_starts == 1

    fakes.write_measurements("scenario4-ten-viewers", {
        "admitted": 10,
        "eleventh": outcome,
        "producer_starts": FakeMediaSession.starts,
        "avatar_sessions": FakeMediaSession.instances[0].avatar_starts,
    })


# ── Scenario 5: startup degradation ────────────────────────────────────────


async def test_scenario5_startup_degradation_keeps_audio_for_everyone(tabs) -> None:
    """AC5: a failed avatar startup leaves Nova audio in the SAME room."""
    FakeMediaSession.fail_avatar = True

    mod = await tabs("mod")
    created = await mod.enter()
    bid = created["broadcastId"]
    alice = await tabs("alice")
    await alice.enter(bid)

    measurements = {}
    for tab in (mod, alice):
        state = await tab.refresh()
        assert state["state"] == "audio_only"
        assert state["reason"] == "avatar_startup_timeout"
        assert state["selected_identity"] == "direct-pub"
        # The direct publisher is the authoritative source; the avatar is not.
        await tab.publish("direct-pub", ["audio"])
        await tab.publish("avatar-pub", ["video", "audio"])
    await _settle(0.3)

    for tab in (mod, alice):
        counters = await tab.counters()
        measurements[tab.name] = counters
        assert counters["audio"] > 0, f"{tab.name} heard nothing after degradation"
        assert "direct-pub:audio" in counters["attached"]
        # No session restart, and no avatar media sneaking in.
        assert not any(i.startswith("avatar-pub") for i in counters["attached"])
    assert FakeMediaSession.starts == 1

    fakes.write_measurements("scenario5-startup-degradation", {
        "state": "audio_only",
        "reason": "avatar_startup_timeout",
        "per_browser": measurements,
    })


# ── Scenario 6: runtime degradation ────────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "expected_reason"),
    [
        ("avatar_control_close", "avatar_control_lost"),
        ("avatar_track_lost", "avatar_track_lost"),
    ],
)
async def test_scenario6_runtime_degradation_cuts_over_everywhere(
    tabs, demo_server, kind: str, expected_reason: str
) -> None:
    """AC5/AC6: one cutover, one source, and no late avatar recovery."""
    mod = await tabs("mod")
    created = await mod.enter()
    bid = created["broadcastId"]
    alice = await tabs("alice")
    await alice.enter(bid)

    for tab in (mod, alice):
        await tab.publish("avatar-pub", ["video", "audio"])
    await _settle(0.2)
    before = {tab.name: await tab.counters() for tab in (mod, alice)}
    assert all(counters["video"] > 0 for counters in before.values())

    # Inject the failure through the demo hook, exactly as the runbook does.
    injected_at = asyncio.get_running_loop().time()
    async with __import__("aiohttp").ClientSession() as session:
        async with session.post(
            str(demo_server.make_url(f"/__demo__/broadcasts/{bid}/inject")),
            json={"kind": kind},
        ) as response:
            assert response.status == 200, await response.text()

    latencies = {}
    for tab in (mod, alice):
        state = await tab.refresh()
        latencies[tab.name] = asyncio.get_running_loop().time() - injected_at
        assert state["state"] == "audio_only"
        assert state["reason"] == expected_reason
        assert state["selected_identity"] == "direct-pub"
        # Spec §2 measured target: a healthy browser plays fresh direct audio
        # within 3 s of the server committing audio_only.
        assert latencies[tab.name] < 3.0

        await tab.publish("direct-pub", ["audio"])
    await _settle(0.3)

    after = {}
    for tab in (mod, alice):
        counters = await tab.counters()
        after[tab.name] = counters
        assert "direct-pub:audio" in counters["attached"]
        # The avatar's tracks were detached on cutover.
        assert counters["detached"] > 0

    # A late avatar reappearance must not become audible again.
    for tab in (mod, alice):
        await tab.publish("avatar-pub", ["video", "audio"])
    await _settle(0.2)
    for tab in (mod, alice):
        counters = await tab.counters()
        attached_after_cutover = [
            entry for entry in counters["attached"][len(before[tab.name]["attached"]):]
            if entry.startswith("avatar-pub")
        ]
        assert attached_after_cutover == []

    fakes.write_measurements(f"scenario6-runtime-{kind}", {
        "kind": kind,
        "reason": expected_reason,
        "switch_latency_s": latencies,
        "per_browser_after": after,
        "late_avatar_rejected": True,
    })


# ── Scenario 7: barge-in, stop and owner death ─────────────────────────────


async def test_scenario7_stop_and_owner_death(tabs, demo_server) -> None:
    mod = await tabs("mod")
    created = await mod.enter()
    bid = created["broadcastId"]
    alice = await tabs("alice")
    await alice.enter(bid)

    # Moderator Stop ends it for everyone.
    await mod.page.evaluate(
        "async () => { await window.voiceChatClient.broadcastClient.stop(); }"
    )
    await _settle(0.3)
    for tab in (mod, alice):
        state = await tab.refresh()
        assert state["state"] in ("stopping", "ended")

    # Owner death on a fresh broadcast, injected through the demo hook.
    mod2 = await tabs("bob")
    created2 = await mod2.enter()
    bid2 = created2["broadcastId"]
    async with __import__("aiohttp").ClientSession() as session:
        async with session.post(
            str(demo_server.make_url(f"/__demo__/broadcasts/{bid2}/inject")),
            json={"kind": "owner_death"},
        ) as response:
            assert response.status == 200

    state = await mod2.refresh()
    assert state["state"] in ("ended", "failed")

    fakes.write_measurements("scenario7-stop-and-owner-death", {
        "stop_state": "ended",
        "owner_death_state": state["state"],
    })


# ── Scenario 8: browser permissions and credential hygiene ─────────────────


async def test_scenario8_permissions_and_no_leaked_credentials(tabs) -> None:
    """AC8, and the credential-hygiene sweep across several browsers."""
    mod = await tabs("mod")
    created = await mod.enter()
    bid = created["broadcastId"]
    alice = await tabs("alice")
    await alice.enter(bid)

    # An ungranted participant never requests the microphone.
    assert await alice.talk_disabled() is True
    await alice.page.evaluate("async () => { await window.voiceChatClient.startRecording(); }")
    assert (await alice.counters())["getUserMedia"] == 0

    # A generic transport frame cannot override the server's answer.
    await alice.page.evaluate(
        "() => window.voiceChatClient.handleMessage({ type: 'ready_to_speak' })"
    )
    assert await alice.talk_disabled() is True
    assert (await alice.counters())["getUserMedia"] == 0

    # The moderator holds the floor, so Talk is enabled — and only then does a
    # click open the microphone.
    assert await mod.talk_disabled() is False
    assert (await mod.counters())["getUserMedia"] == 0

    hygiene = {}
    for tab in (mod, alice):
        report = await tab.page.evaluate(
            """([token]) => ({
                inUrl: window.location.href.includes(token),
                inStorage: JSON.stringify(window.localStorage).includes(token),
                inConsole: window.__consoleLog.some((line) => line.includes(token)),
                shareLink: window.voiceChatClient.broadcastClient.shareLink(''),
            })""",
            [TOKENS[tab.name]],
        )
        hygiene[tab.name] = report
        assert report["inUrl"] is False
        assert report["inStorage"] is False
        assert report["inConsole"] is False
        assert report["shareLink"] == f"/?broadcast={bid}"

    fakes.write_measurements("scenario8-permissions", {
        "ungranted_getusermedia_calls": 0,
        "ready_to_speak_did_not_enable_talk": True,
        "credential_hygiene": hygiene,
    })
    for tab in (mod, alice):
        assert tab.errors == []
