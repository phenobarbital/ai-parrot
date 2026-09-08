"""Opt-in real-vendor multi-browser variant (FEAT-537 TASK-2968).

The deterministic sibling (`test_voice_demo_multibrowser.py`) fakes the vendor
boundaries, which is what makes it fast and reliable — and is exactly why it
**cannot** answer the questions AC10 asks: does a real LiveAvatar session
publish lip-synced media into our room, do ten real browsers actually hear and
see it, and does a real interruption stop real audio.

This module runs scenarios 1, 2 and 4 against **real** Nova, LiveAvatar and
LiveKit with the **real** `livekit-client` UMD bundle — no fake SDK — and
captures a ten-second synchronized A/V sample per browser for the human
lip-sync assessment that TASK-2969 signs off.

It skips by default. A skipped live test is reported as **NOT VERIFIED**, never
as a pass: `docs/testing/voicebot-multiroom-live-gate.md` is the record, and at
the time of writing it reads 0 of 12.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import uvloop

from . import _broadcast_browser_fakes as fakes

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

pytestmark = pytest.mark.live_vendor

#: Credentials the live path needs, on top of the opt-in switch.
_REQUIRED_ENV: Tuple[str, ...] = (
    "LIVEAVATAR_API_KEY",
    "LIVEAVATAR_AVATAR_ID",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "VOICEBOT_BROADCAST_REDIS_URL",
)

_GATE_ENABLED: bool = (
    os.environ.get("PARROT_LIVE_BROADCAST_GATE") == "1"
    and all(os.environ.get(name) for name in _REQUIRED_ENV)
)

_SKIP_REASON: str = (
    "real-vendor multi-browser gate not enabled / credentials missing — "
    "NOT VERIFIED (set PARROT_LIVE_BROADCAST_GATE=1 plus "
    f"{', '.join(_REQUIRED_ENV)}; see docs/testing/voicebot-multiroom-live-gate.md)"
)

pytest.importorskip(
    "playwright.async_api", reason="playwright is required for browser tests"
)

#: Seconds of synchronized A/V captured per browser for the human assessment.
CAPTURE_SECONDS: float = 10.0


def _record(scenario: str, payload: Dict[str, Any]) -> Path:
    """Write a sanitized live-run measurement file."""
    return fakes.write_measurements(f"live-{scenario}", payload)


@pytest.fixture
def live_env() -> Dict[str, str]:
    """The live configuration, with credential *values* never returned."""
    return {name: "<set>" for name in _REQUIRED_ENV}


@pytest.mark.skipif(not _GATE_ENABLED, reason=_SKIP_REASON)
async def test_live_scenario1_three_real_browsers(live_env) -> None:
    """Scenario 1 against real Nova → LiveAvatar → LiveKit, three browsers.

    Captures per-browser decoded video-frame counts, received audio sample
    counts and a ten-second A/V sample. A connected badge or a published track
    alone is explicitly insufficient evidence (spec §4).
    """
    pytest.fail(
        "The real-vendor multi-browser path is UNIMPLEMENTED beyond this "
        "harness's skip gate. Implementing it against fabricated expectations "
        "would be worse than leaving it NOT RUN: the run must be authored "
        "against an actual account so the track manifest, codec observations "
        "and lip-sync capture reflect what the vendor really does. "
        "See docs/testing/voicebot-multiroom-live-gate.md rows 5-12."
    )


@pytest.mark.skipif(not _GATE_ENABLED, reason=_SKIP_REASON)
async def test_live_scenario2_real_moderated_handoff(live_env) -> None:
    """Scenario 2 against real vendors: two speakers, one conversation."""
    pytest.fail(
        "UNIMPLEMENTED — see test_live_scenario1_three_real_browsers. "
        "Requires a real account to author against."
    )


@pytest.mark.skipif(not _GATE_ENABLED, reason=_SKIP_REASON)
async def test_live_scenario4_ten_real_browsers(live_env) -> None:
    """Scenario 4 against real vendors: ten browsers, one avatar session."""
    pytest.fail(
        "UNIMPLEMENTED — see test_live_scenario1_three_real_browsers. "
        "Requires a real account to author against."
    )


def test_live_gate_is_disabled_by_default() -> None:
    """The gate must never be silently on, and must say so when it is off.

    This is the one assertion in this module that CAN run without credentials:
    it proves the skip is deliberate rather than accidental, so a green CI run
    can never be mistaken for real-vendor coverage.
    """
    if _GATE_ENABLED:
        pytest.skip("live gate is enabled in this environment")
    assert "NOT VERIFIED" in _SKIP_REASON
    assert "PARROT_LIVE_BROADCAST_GATE" in _SKIP_REASON
    for name in _REQUIRED_ENV:
        assert name in _SKIP_REASON


def test_capture_budget_is_documented() -> None:
    """The A/V capture length is a stated constant, not a magic number."""
    assert CAPTURE_SECONDS == 10.0
