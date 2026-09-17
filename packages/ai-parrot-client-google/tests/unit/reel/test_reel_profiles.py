"""TASK-3323: capability registry and covering-duration selection tests.

Verifies `VideoProfileRegistry` resolves/validates exactly the spec's
Developer API preview IDs and disabled Vertex GA entries (never by
substring), that Lite is excluded from 4k/reference guidance, and that
`select_generation_duration` picks the smallest legal covering duration
(4/5/6/8 s cases, high-resolution forcing 8 s, Omni returning None).
"""

from pathlib import Path

import pytest

from parrot.clients.google.reel.clip import GeneratedReelClip
from parrot.clients.google.reel.errors import ReelErrorCode, ReelValidationError
from parrot.clients.google.reel.profiles import VideoProfileRegistry, select_generation_duration


@pytest.fixture
def registry() -> VideoProfileRegistry:
    return VideoProfileRegistry.default()


# ---------------------------------------------------------------------------
# Registry resolution
# ---------------------------------------------------------------------------


class TestRegistryResolve:
    @pytest.mark.parametrize(
        "model_id",
        [
            "veo-3.1-generate-preview",
            "veo-3.1-fast-generate-preview",
            "veo-3.1-lite-generate-preview",
            "gemini-omni-1.1-flash",
        ],
    )
    def test_developer_preview_ids_resolve_enabled(self, registry, model_id):
        profile = registry.resolve(model_id, "gemini_developer")
        assert profile.enabled is True
        assert profile.model_id == model_id

    @pytest.mark.parametrize("model_id", ["veo-3.1-generate-001", "veo-3.1-fast-generate-001"])
    def test_vertex_ga_entries_are_disabled(self, registry, model_id):
        with pytest.raises(ReelValidationError) as exc_info:
            registry.resolve(model_id, "vertex")
        assert exc_info.value.code is ReelErrorCode.MODEL_DISABLED

    def test_unknown_model_id_rejected(self, registry):
        with pytest.raises(ReelValidationError) as exc_info:
            registry.resolve("veo-4-ultra-preview", "gemini_developer")
        assert exc_info.value.code is ReelErrorCode.UNKNOWN_MODEL

    def test_wrong_api_surface_rejected(self, registry):
        """Registered on gemini_developer, requested on vertex -> wrong_api_surface, not unknown_model."""
        with pytest.raises(ReelValidationError) as exc_info:
            registry.resolve("veo-3.1-generate-preview", "vertex")
        assert exc_info.value.code is ReelErrorCode.WRONG_API_SURFACE

    def test_no_substring_matching(self, registry):
        """'veo-3' must never resolve just because it's a prefix of a real id."""
        with pytest.raises(ReelValidationError) as exc_info:
            registry.resolve("veo-3", "gemini_developer")
        assert exc_info.value.code is ReelErrorCode.UNKNOWN_MODEL

    def test_default_video_model_per_surface(self, registry):
        assert registry.default_video_model("gemini_developer") == "veo-3.1-generate-preview"
        assert registry.default_video_model("vertex") == "veo-3.1-generate-001"


# ---------------------------------------------------------------------------
# Lite exclusions / capability shape
# ---------------------------------------------------------------------------


class TestLiteExclusions:
    def test_lite_never_gains_4k(self, registry):
        profile = registry.resolve("veo-3.1-lite-generate-preview", "gemini_developer")
        assert "4k" not in profile.resolutions

    def test_lite_never_gains_reference_guidance(self, registry):
        profile = registry.resolve("veo-3.1-lite-generate-preview", "gemini_developer")
        assert profile.supports_reference_guidance is False

    def test_standard_and_fast_support_4k_and_reference_guidance(self, registry):
        for model_id in ("veo-3.1-generate-preview", "veo-3.1-fast-generate-preview"):
            profile = registry.resolve(model_id, "gemini_developer")
            assert "4k" in profile.resolutions
            assert profile.supports_reference_guidance is True

    def test_validate_scene_rejects_4k_for_lite(self, registry):
        profile = registry.resolve("veo-3.1-lite-generate-preview", "gemini_developer")
        with pytest.raises(ReelValidationError) as exc_info:
            registry.validate_scene(profile, resolution="4k", audio_mode="separate", has_starting_frame=False)
        assert exc_info.value.code is ReelErrorCode.UNSUPPORTED_OPTION

    def test_validate_scene_accepts_supported_resolution(self, registry):
        profile = registry.resolve("veo-3.1-lite-generate-preview", "gemini_developer")
        # Must not raise.
        registry.validate_scene(profile, resolution="720p", audio_mode="separate", has_starting_frame=False)

    def test_validate_scene_rejects_unsupported_starting_frame(self, registry):
        profile = registry.resolve("gemini-omni-1.1-flash", "gemini_developer")
        with pytest.raises(ReelValidationError) as exc_info:
            registry.validate_scene(profile, resolution="720p", audio_mode="separate", has_starting_frame=True)
        assert exc_info.value.code is ReelErrorCode.UNSUPPORTED_OPTION

    def test_validate_scene_accepts_native_audio_on_controllable_profile(self, registry):
        profile = registry.resolve("veo-3.1-generate-preview", "gemini_developer")
        # Must not raise: this profile supports native audio (controllable).
        registry.validate_scene(profile, resolution="720p", audio_mode="native", has_starting_frame=False)

    def test_validate_scene_rejects_native_audio_when_unsupported(self):
        from datetime import date

        from parrot.clients.google.reel.profiles import VideoModelProfile
        from parrot.clients.google.reel.profiles import VideoProfileRegistry as _Registry

        no_audio_profile = VideoModelProfile(
            model_id="test-model-no-audio",
            surface="gemini_developer",
            backend="veo",
            enabled=True,
            durations_seconds=[4, 6, 8],
            resolutions=["720p"],
            resolution_min_duration={},
            supports_starting_frame=False,
            supports_reference_guidance=False,
            native_audio="none",
            person_generation_values=["allow_adult"],
            source="test",
            checked_on=date(2026, 9, 17),
        )
        empty_registry = _Registry([no_audio_profile])
        with pytest.raises(ReelValidationError) as exc_info:
            empty_registry.validate_scene(
                no_audio_profile, resolution="720p", audio_mode="native", has_starting_frame=False
            )
        assert exc_info.value.code is ReelErrorCode.UNSUPPORTED_OPTION


# ---------------------------------------------------------------------------
# Person-generation values are lowercase, never inferred
# ---------------------------------------------------------------------------


class TestPersonGenerationValues:
    def test_all_veo_profiles_have_lowercase_person_generation_values(self, registry):
        for model_id in (
            "veo-3.1-generate-preview",
            "veo-3.1-fast-generate-preview",
            "veo-3.1-lite-generate-preview",
        ):
            profile = registry.resolve(model_id, "gemini_developer")
            assert profile.person_generation_values
            for value in profile.person_generation_values:
                assert value == value.lower()

    def test_omni_has_no_person_generation_values(self, registry):
        """M4 scope: Omni takes no Veo config — person_generation is not applicable."""
        profile = registry.resolve("gemini-omni-1.1-flash", "gemini_developer")
        assert profile.person_generation_values == []


# ---------------------------------------------------------------------------
# select_generation_duration
# ---------------------------------------------------------------------------


class TestSelectGenerationDuration:
    @pytest.mark.parametrize(
        "target,expected",
        [
            (4.0, 4),
            (5.0, 6),
            (6.0, 6),
            (8.0, 8),
        ],
    )
    def test_720p_covering_duration(self, registry, target, expected):
        profile = registry.resolve("veo-3.1-generate-preview", "gemini_developer")
        assert select_generation_duration(profile, target, "720p", has_starting_frame=False) == expected

    def test_high_resolution_forces_8(self, registry):
        """A 1080p/4k request is forced to the resolution's minimum duration
        regardless of a lower target."""
        profile = registry.resolve("veo-3.1-generate-preview", "gemini_developer")
        for target in (4.0, 5.0, 6.0):
            assert select_generation_duration(profile, target, "1080p", has_starting_frame=False) == 8
        assert select_generation_duration(profile, 4.0, "4k", has_starting_frame=False) == 8

    def test_omni_duration_is_always_none(self, registry):
        profile = registry.resolve("gemini-omni-1.1-flash", "gemini_developer")
        assert select_generation_duration(profile, 5.0, "720p", has_starting_frame=False) is None
        assert select_generation_duration(profile, 8.0, "720p", has_starting_frame=True) is None

    def test_unconfigured_resolution_has_no_duration_floor(self, registry):
        """A resolution with no configured minimum imposes no floor — smallest
        candidate covering the target wins. Resolution *membership* is
        validate_scene's job, not duration selection's."""
        profile = registry.resolve("veo-3.1-lite-generate-preview", "gemini_developer")
        assert select_generation_duration(profile, 4.0, "8k", has_starting_frame=False) == 4

    def test_no_legal_duration_raises(self):
        """A profile where no duration satisfies the resolution's floor must
        raise rather than silently pick an illegal value."""
        from datetime import date

        from parrot.clients.google.reel.profiles import VideoModelProfile

        pathological = VideoModelProfile(
            model_id="test-model",
            surface="gemini_developer",
            backend="veo",
            enabled=True,
            durations_seconds=[4, 6],
            resolutions=["1080p"],
            resolution_min_duration={"1080p": 8},  # no duration in [4, 6] satisfies this
            supports_starting_frame=False,
            supports_reference_guidance=False,
            native_audio="none",
            person_generation_values=["allow_adult"],
            source="test",
            checked_on=date(2026, 9, 17),
        )
        with pytest.raises(ReelValidationError) as exc_info:
            select_generation_duration(pathological, 4.0, "1080p", has_starting_frame=False)
        assert exc_info.value.code is ReelErrorCode.UNSUPPORTED_OPTION


# ---------------------------------------------------------------------------
# GeneratedReelClip
# ---------------------------------------------------------------------------


class TestGeneratedReelClip:
    def test_round_trip_json_mode(self, tmp_path):
        clip = GeneratedReelClip(
            local_path=tmp_path / "scene_0.mp4",
            model="veo-3.1-generate-preview",
            backend="veo",
            submitted_duration_seconds=6.0,
            measured_duration_seconds=6.04,
            has_audio=True,
            provider_operation_id="op-abc123",
        )
        dumped = clip.model_dump(mode="json")
        assert dumped["local_path"] == str(tmp_path / "scene_0.mp4")
        assert dumped["backend"] == "veo"
        assert dumped["provider_operation_id"] == "op-abc123"

    def test_omni_clip_has_no_submitted_duration(self, tmp_path):
        clip = GeneratedReelClip(
            local_path=tmp_path / "scene_1.mp4",
            model="gemini-omni-1.1-flash",
            backend="omni",
            measured_duration_seconds=5.2,
            has_audio=True,
        )
        assert clip.submitted_duration_seconds is None
        assert clip.provider_operation_id is None
        assert isinstance(clip.local_path, Path)
