"""TASK-3335: opt-in, paid Google GenAI video-reel smoke tests (``live_google`` marker).

Skipped by default. To actually run: set ``PARROT_TEST_LIVE_GOOGLE=1`` AND a
real credential (``GOOGLE_API_KEY`` for the Gemini Developer API surface, or
``GOOGLE_APPLICATION_CREDENTIALS`` for Vertex), then run explicitly:

    PARROT_TEST_LIVE_GOOGLE=1 pytest -m live_google packages/ai-parrot-client-google/tests/live/test_reel_smoke.py -v

The skip condition is evaluated from environment variables ONLY, at
COLLECTION time — this module makes no network call, constructs no SDK
client, and imports no provider module at collection time; every real call
happens inside a test body that only runs once the skip has already been
evaluated false.

Every test records model/API surface/SDK version/region as REDACTED
diagnostics (never a raw key/token) into ``artifacts/logs/reel-smoke/`` —
these are evidence for the still-open evidence gates (§8 Q3-Q6 of the spec:
Omni URI authentication, image model id, Vertex Veo 3.1 GA capabilities,
Lyria api_version/PCM format), NOT a claim that this deployment is
live-ready. See ``docs/migration/video-reel-omni-veo-reliability.md``
"Outstanding deployment gates" for what remains unresolved regardless of
whether this suite has ever been run.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_google

_ENABLED = os.environ.get("PARROT_TEST_LIVE_GOOGLE") == "1"
_HAS_CREDENTIALS = bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))

skip_unless_live = pytest.mark.skipif(
    not (_ENABLED and _HAS_CREDENTIALS),
    reason=(
        "Opt-in paid smoke test — set PARROT_TEST_LIVE_GOOGLE=1 and a real "
        "GOOGLE_API_KEY (or GOOGLE_APPLICATION_CREDENTIALS) to run."
    ),
)

_ARTIFACT_DIR = Path("artifacts/logs/reel-smoke")


def _record_diagnostics(test_name: str, **fields) -> Path:
    """Writes a REDACTED diagnostics record for one smoke test run.

    Args:
        test_name: The smoke test's own name, used as the log filename stem.
        **fields: Arbitrary model/API/version/region fields to record —
            each value is passed through ``reel.errors._redact`` before
            being written, so a credential-shaped value never lands on disk.

    Returns:
        The path the diagnostics record was written to.
    """
    from parrot.clients.google.reel.errors import _redact

    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "test": test_name,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        **{k: (_redact(str(v)) if v is not None else None) for k, v in fields.items()},
    }
    out_path = _ARTIFACT_DIR / f"{test_name}.json"
    out_path.write_text(json.dumps(record, indent=2))
    return out_path


async def _sdk_version() -> str:
    import google.genai

    return getattr(google.genai, "__version__", "unknown")


@skip_unless_live
class TestVeoSmoke:
    """A single, short, cheap Veo text-to-video scene."""

    async def test_veo_single_scene_text_to_video(self, tmp_path):
        from parrot.clients.google import GoogleGenAIClient
        from parrot.models.google import VideoReelRequest, VideoReelScene

        request = VideoReelRequest(
            prompt="A single still shot of calm ocean waves at sunrise.",
            scenes=[
                VideoReelScene(
                    background_prompt="Calm ocean waves at sunrise, cinematic.",
                    video_prompt="Slow, steady pan across the horizon.",
                    duration=4.0,
                )
            ],
            video_model="veo-3.1-generate-preview",
            audio_mode="muted",
        )

        # Explicit key only — NEVER let the client fall back to
        # navconfig's resolved settings (config.get("GOOGLE_API_KEY")),
        # which is a DIFFERENT source than the raw os.environ this
        # module's skip condition checks and could resolve an ambient
        # dev credential not intended for this specific opt-in test.
        client = GoogleGenAIClient(api_key=os.environ["GOOGLE_API_KEY"])
        start = time.monotonic()
        async with client:
            result = await client.generate_video_reel(request=request, output_directory=tmp_path)
        elapsed = time.monotonic() - start

        reel_result = result.metadata["video_reel"]
        _record_diagnostics(
            "test_veo_single_scene_text_to_video",
            model=reel_result["effective_models"]["video"],
            api_surface=reel_result["api_surface"],
            sdk_version=reel_result["sdk_version"],
            region=os.environ.get("GOOGLE_CLOUD_LOCATION") or os.environ.get("GOOGLE_CLOUD_REGION"),
            elapsed_seconds=round(elapsed, 2),
        )
        assert reel_result["scenes"][0]["status"] == "succeeded"
        assert reel_result["scenes"][0]["backend"] == "veo"


@skip_unless_live
class TestOmniSmoke:
    """A single, short Omni scene, routed explicitly via a per-scene override."""

    async def test_omni_single_scene(self, tmp_path):
        from parrot.clients.google import GoogleGenAIClient
        from parrot.models.google import VideoReelRequest, VideoReelScene

        request = VideoReelRequest(
            prompt="A single still shot of a city skyline at dusk.",
            scenes=[
                VideoReelScene(
                    background_prompt="City skyline at dusk, warm lights.",
                    video_prompt="Gentle drift toward the skyline.",
                    duration=4.0,
                    video_model="gemini-omni-1.1-flash",
                )
            ],
            audio_mode="native",
        )

        # Explicit key only — NEVER let the client fall back to
        # navconfig's resolved settings (config.get("GOOGLE_API_KEY")),
        # which is a DIFFERENT source than the raw os.environ this
        # module's skip condition checks and could resolve an ambient
        # dev credential not intended for this specific opt-in test.
        client = GoogleGenAIClient(api_key=os.environ["GOOGLE_API_KEY"])
        async with client:
            result = await client.generate_video_reel(request=request, output_directory=tmp_path)

        reel_result = result.metadata["video_reel"]
        _record_diagnostics(
            "test_omni_single_scene",
            model=reel_result["scenes"][0]["video_model"],
            api_surface=reel_result["api_surface"],
            sdk_version=reel_result["sdk_version"],
        )
        assert reel_result["scenes"][0]["status"] == "succeeded"
        assert reel_result["scenes"][0]["backend"] == "omni"


@skip_unless_live
class TestMixedReelSmoke:
    """One Veo scene + one Omni scene in the SAME reel — the mixed-backend path."""

    async def test_mixed_veo_and_omni_scenes(self, tmp_path):
        from parrot.clients.google import GoogleGenAIClient
        from parrot.models.google import VideoReelRequest, VideoReelScene

        request = VideoReelRequest(
            prompt="A two-scene reel mixing two visual styles.",
            scenes=[
                VideoReelScene(
                    background_prompt="Calm ocean waves at sunrise.",
                    video_prompt="Slow pan.",
                    duration=4.0,
                    video_model="veo-3.1-generate-preview",
                ),
                VideoReelScene(
                    background_prompt="City skyline at dusk.",
                    video_prompt="Gentle drift.",
                    duration=4.0,
                    video_model="gemini-omni-1.1-flash",
                ),
            ],
            audio_mode="muted",
        )

        # Explicit key only — NEVER let the client fall back to
        # navconfig's resolved settings (config.get("GOOGLE_API_KEY")),
        # which is a DIFFERENT source than the raw os.environ this
        # module's skip condition checks and could resolve an ambient
        # dev credential not intended for this specific opt-in test.
        client = GoogleGenAIClient(api_key=os.environ["GOOGLE_API_KEY"])
        async with client:
            result = await client.generate_video_reel(request=request, output_directory=tmp_path)

        reel_result = result.metadata["video_reel"]
        backends = [s["backend"] for s in reel_result["scenes"]]
        _record_diagnostics(
            "test_mixed_veo_and_omni_scenes",
            backends=",".join(backends),
            sdk_version=reel_result["sdk_version"],
        )
        assert backends == ["veo", "omni"]
        assert all(s["status"] == "succeeded" for s in reel_result["scenes"])


@skip_unless_live
class TestNativeAudioSmoke:
    """`audio_mode="native"` — no separate TTS/Lyria calls, clip's own audio kept."""

    async def test_native_audio_mode_makes_no_separate_tts_or_music_calls(self, tmp_path):
        from parrot.clients.google import GoogleGenAIClient
        from parrot.models.google import VideoReelRequest, VideoReelScene

        request = VideoReelRequest(
            prompt="A single scene relying on the clip's own native audio.",
            scenes=[
                VideoReelScene(
                    background_prompt="A quiet forest clearing.",
                    video_prompt="Static shot, ambient motion only.",
                    duration=4.0,
                    video_model="gemini-omni-1.1-flash",
                )
            ],
            audio_mode="native",
        )

        # Explicit key only — NEVER let the client fall back to
        # navconfig's resolved settings (config.get("GOOGLE_API_KEY")),
        # which is a DIFFERENT source than the raw os.environ this
        # module's skip condition checks and could resolve an ambient
        # dev credential not intended for this specific opt-in test.
        client = GoogleGenAIClient(api_key=os.environ["GOOGLE_API_KEY"])
        async with client:
            result = await client.generate_video_reel(request=request, output_directory=tmp_path)

        reel_result = result.metadata["video_reel"]
        _record_diagnostics(
            "test_native_audio_mode",
            audio_mode=reel_result["audio_mode"],
            music_status=reel_result["music_status"],
            sdk_version=reel_result["sdk_version"],
        )
        assert reel_result["audio_mode"] == "native"
        # native/muted never start a Lyria connection (TASK-3327 contract).
        assert reel_result["music_status"] == "off"


@skip_unless_live
class TestOptionalMusicSmoke:
    """`music="optional"` in `separate` mode — best-effort, never fails the job."""

    async def test_optional_music_records_a_structured_status(self, tmp_path):
        from parrot.clients.google import GoogleGenAIClient
        from parrot.models.google import VideoReelRequest, VideoReelScene

        request = VideoReelRequest(
            prompt="A single scene with best-effort background music.",
            scenes=[
                VideoReelScene(
                    background_prompt="A calm mountain lake at dawn.",
                    video_prompt="Slow zoom out.",
                    duration=4.0,
                    video_model="veo-3.1-generate-preview",
                )
            ],
            audio_mode="separate",
            music_policy="optional",
        )

        # Explicit key only — NEVER let the client fall back to
        # navconfig's resolved settings (config.get("GOOGLE_API_KEY")),
        # which is a DIFFERENT source than the raw os.environ this
        # module's skip condition checks and could resolve an ambient
        # dev credential not intended for this specific opt-in test.
        client = GoogleGenAIClient(api_key=os.environ["GOOGLE_API_KEY"])
        async with client:
            result = await client.generate_video_reel(request=request, output_directory=tmp_path)

        reel_result = result.metadata["video_reel"]
        _record_diagnostics(
            "test_optional_music",
            music_status=reel_result["music_status"],
            sdk_version=reel_result["sdk_version"],
        )
        # "optional" is best-effort: any of these outcomes is a valid,
        # non-fatal result — the job must never fail because of music alone.
        assert reel_result["music_status"] in ("succeeded", "unavailable", "timeout", "failed", "skipped")
        assert reel_result["scenes"][0]["status"] == "succeeded"
