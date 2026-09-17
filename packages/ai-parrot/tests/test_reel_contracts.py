"""
Core-only schema and serialization tests for the video reel request/result contracts.

Covers TASK-3321 (spec M1): legacy `model` alias resolution, scene duration bounds, audio
control conflicts, the sparse reference-image slot representation, and result serialization
into JSON-mode dictionaries compatible with `AIMessage.artifacts`. No provider import is
exercised here -- these are pure Pydantic model tests.
"""

import math

import pytest
from pydantic import ValidationError

from parrot.models.google import (
    ReelArtifact,
    ReelResult,
    ReelSceneResult,
    VideoReelRequest,
    VideoReelScene,
)

# ---------------------------------------------------------------------------
# Legacy `model` alias resolution (AC02)
# ---------------------------------------------------------------------------


def test_legacy_model_alias_absent_uses_default():
    """Neither `model` nor `director_model` supplied: default director model, no warnings."""
    request = VideoReelRequest(prompt="a reel")
    assert request.effective_director_model() == "gemini-2.5-flash"
    assert request.deprecation_warnings() == []


def test_legacy_model_alias_identical_warns():
    """Identical `model`/`director_model` values are accepted with a deprecation warning."""
    request = VideoReelRequest(prompt="a reel", model="gemini-2.5-flash", director_model="gemini-2.5-flash")
    assert request.effective_director_model() == "gemini-2.5-flash"
    assert any("deprecated" in w for w in request.deprecation_warnings())


def test_legacy_model_alias_only_model_resolves_and_warns():
    """`model` alone resolves into `director_model` and is recorded as a deprecation warning."""
    request = VideoReelRequest(prompt="a reel", model="gemini-2.5-flash")
    assert request.director_model == "gemini-2.5-flash"
    assert request.effective_director_model() == "gemini-2.5-flash"
    assert any("deprecated" in w for w in request.deprecation_warnings())


def test_legacy_model_alias_conflict_rejected():
    """Differing `model`/`director_model` values raise a validation error."""
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="a reel", model="model-a", director_model="model-b")


@pytest.mark.parametrize("field", ["model", "director_model", "image_model", "video_model"])
def test_legacy_model_alias_explicit_null_rejected(field):
    """Explicit null (as opposed to an omitted key) for any model field raises."""
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="a reel", **{field: None})


@pytest.mark.parametrize("field", ["model", "director_model", "image_model", "video_model"])
def test_legacy_model_alias_blank_rejected(field):
    """A blank/whitespace-only model field raises."""
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="a reel", **{field: "   "})


def test_director_model_only_no_warning():
    """Setting only `director_model` (no legacy `model`) never records a deprecation warning."""
    request = VideoReelRequest(prompt="a reel", director_model="gemini-2.5-flash")
    assert request.effective_director_model() == "gemini-2.5-flash"
    assert request.deprecation_warnings() == []


def test_scene_video_model_inherits_from_reel_when_absent():
    """A scene without `video_model` is None, ready to inherit the reel/registry default."""
    scene = VideoReelScene(background_prompt="bg", video_prompt="vid", duration=5.0)
    assert scene.video_model is None


# ---------------------------------------------------------------------------
# Scene duration bounds (AC04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_duration", [math.nan, math.inf, -math.inf, 0, -1.0, 8.001, 100.0])
def test_scene_duration_bounds_rejects_out_of_range(bad_duration):
    """NaN/inf/zero/negative/>8 second edit targets are all rejected."""
    with pytest.raises(ValidationError):
        VideoReelScene(background_prompt="bg", video_prompt="vid", duration=bad_duration)


def test_scene_duration_default_is_five_seconds():
    """A scene built without an explicit duration defaults to 5.0 seconds."""
    scene = VideoReelScene(background_prompt="bg", video_prompt="vid")
    assert scene.duration == 5.0


@pytest.mark.parametrize("good_duration", [0.001, 1.0, 4.0, 5.0, 6.0, 8.0])
def test_scene_duration_bounds_accepts_in_range(good_duration):
    """Any finite duration in (0, 8] is accepted."""
    scene = VideoReelScene(background_prompt="bg", video_prompt="vid", duration=good_duration)
    assert scene.duration == good_duration


def test_scene_video_model_blank_rejected():
    """An explicit blank `video_model` on a scene is rejected; only null means inherit."""
    with pytest.raises(ValidationError):
        VideoReelScene(background_prompt="bg", video_prompt="vid", video_model="   ")


def test_scene_video_model_explicit_override_accepted():
    """A non-blank `video_model` override on a scene is accepted verbatim."""
    scene = VideoReelScene(background_prompt="bg", video_prompt="vid", video_model="gemini-omni-1.1-flash")
    assert scene.video_model == "gemini-omni-1.1-flash"


# ---------------------------------------------------------------------------
# Audio-control conflicts (AC06)
# ---------------------------------------------------------------------------


def test_native_mode_rejects_speech():
    """`audio_mode='native'` conflicts with narration/`speech`."""
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="a reel", audio_mode="native", speech=["line one"])


def test_muted_mode_rejects_music_controls():
    """`audio_mode='muted'` conflicts with music_prompt/genre/mood."""
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="a reel", audio_mode="muted", music_prompt="upbeat synth")


def test_native_mode_rejects_music_required():
    """`audio_mode='native'` conflicts with `music_policy='required'`."""
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="a reel", audio_mode="native", music_policy="required")


def test_native_mode_without_conflicts_is_accepted():
    """`audio_mode='native'` with no speech/music controls validates cleanly."""
    request = VideoReelRequest(prompt="a reel", audio_mode="native")
    assert request.audio_mode == "native"


@pytest.mark.parametrize("policy", ["off", "optional", "required"])
def test_music_policy_values_accepted_in_separate_mode(policy):
    """All three music policy values are valid under the default `separate` audio mode."""
    request = VideoReelRequest(prompt="a reel", music_policy=policy)
    assert request.music_policy == policy


def test_music_policy_invalid_value_rejected():
    """An unknown music_policy literal value is rejected."""
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="a reel", music_policy="sometimes")


def test_separate_mode_allows_speech_and_music():
    """The default `separate` audio mode allows speech and music controls together."""
    request = VideoReelRequest(
        prompt="a reel",
        speech=["hello"],
        music_prompt="ambient",
        music_policy="required",
    )
    assert request.audio_mode == "separate"


# ---------------------------------------------------------------------------
# Format/transition literal tightening
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("transition", ["cut", "crossfade"])
def test_transition_type_accepts_known_values(transition):
    request = VideoReelRequest(prompt="a reel", transition_type=transition)
    assert request.transition_type == transition


def test_transition_type_rejects_unknown_value():
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="a reel", transition_type="fade-to-black")


@pytest.mark.parametrize("output_format", ["mp4", "webm"])
def test_output_format_accepts_known_values(output_format):
    request = VideoReelRequest(prompt="a reel", output_format=output_format)
    assert request.output_format == output_format


def test_output_format_rejects_unknown_value():
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="a reel", output_format="avi")


# ---------------------------------------------------------------------------
# storage_config JSON decoding (multipart use)
# ---------------------------------------------------------------------------


def test_storage_config_json_string_decoded_to_object():
    """A JSON-encoded string (as arrives via multipart FormData) is decoded to a dict."""
    request = VideoReelRequest(prompt="a reel", storage_config='{"bucket": "reels", "prefix": "jobs/"}')
    assert request.storage_config == {"bucket": "reels", "prefix": "jobs/"}


def test_storage_config_object_passthrough():
    """A storage_config already given as a dict is accepted unchanged."""
    request = VideoReelRequest(prompt="a reel", storage_config={"bucket": "reels"})
    assert request.storage_config == {"bucket": "reels"}


# ---------------------------------------------------------------------------
# Sparse, lossless reference-image slot representation (shared with the HTTP task)
# ---------------------------------------------------------------------------


def test_sparse_reference_images_preserve_holes():
    """A None entry in `reference_images` is preserved as an empty slot at its index."""
    request = VideoReelRequest(prompt="a reel", reference_images=["/a.png", None, "/c.png"])
    assert request.reference_images == ["/a.png", None, "/c.png"]
    assert request.image_for_scene(0) == "/a.png"
    assert request.image_for_scene(1) is None
    assert request.image_for_scene(2) == "/c.png"


def test_sparse_reference_images_out_of_range_index_is_none():
    """Indices beyond the slot list (e.g. a director-produced scene with no image) return None."""
    request = VideoReelRequest(prompt="a reel", reference_images=["/a.png"])
    assert request.image_for_scene(5) is None


def test_reference_images_absent_image_for_scene_returns_none():
    """`image_for_scene` is safe to call even when no images were supplied at all."""
    request = VideoReelRequest(prompt="a reel")
    assert request.image_for_scene(0) is None


def test_reference_images_blank_slot_rejected():
    """A blank string slot (as opposed to null) is rejected -- only null represents an empty slot."""
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="a reel", reference_images=["/a.png", "   "])


def test_reference_images_preserved_for_director_produced_scenes():
    """Slot indices stay addressable by `image_for_scene` even when `scenes` was not supplied,
    i.e. the request relies on the director to produce scenes after validation."""
    request = VideoReelRequest(prompt="a reel", reference_images=[None, "/only-second.png"])
    assert request.scenes is None
    assert request.image_for_scene(0) is None
    assert request.image_for_scene(1) == "/only-second.png"


# ---------------------------------------------------------------------------
# Result models: URL round trip and JSON-mode serialization (AC10)
# ---------------------------------------------------------------------------


def test_artifact_download_url_is_string_not_path():
    """`ReelArtifact.download_url` is a plain string field, never coerced to a Path."""
    artifact = ReelArtifact(
        artifact_id="artifact-1",
        storage_backend="fs",
        storage_key="jobs/1/reel.mp4",
        mime_type="video/mp4",
        size_bytes=1024,
        download_url="https://cdn.example.com/reel.mp4?sig=abc123&exp=999",
    )
    assert isinstance(artifact.download_url, str)
    assert artifact.download_url == "https://cdn.example.com/reel.mp4?sig=abc123&exp=999"


def test_artifact_download_url_query_preserved_through_json_round_trip():
    """The exact query string survives a Pydantic model_dump(mode='json') round trip."""
    original_url = "https://cdn.example.com/reel.mp4?sig=a%2Fb&exp=999&list=1,2,3"
    artifact = ReelArtifact(
        artifact_id="artifact-1",
        storage_backend="s3",
        storage_key="jobs/1/reel.mp4",
        mime_type="video/mp4",
        size_bytes=2048,
        download_url=original_url,
    )
    dumped = artifact.model_dump(mode="json")
    assert dumped["download_url"] == original_url

    reloaded = ReelArtifact.model_validate(dumped)
    assert reloaded.download_url == original_url


def test_reel_result_serializes_to_artifacts_compatible_dict():
    """`ReelResult.model_dump(mode='json')` yields a plain dict, matching `AIMessage.artifacts`
    (a `List[Dict[str, Any]]`)."""
    scene_result = ReelSceneResult(
        index=0,
        video_model="veo-3.1-generate-preview",
        backend="veo",
        status="succeeded",
        requested_duration_seconds=5.0,
        submitted_duration_seconds=6.0,
        measured_duration_seconds=6.02,
        final_duration_seconds=5.0,
        provider_operation_id="op-123",
    )
    artifact = ReelArtifact(
        artifact_id="artifact-1",
        storage_backend="fs",
        storage_key="jobs/1/reel.mp4",
        mime_type="video/mp4",
        size_bytes=4096,
        download_url="https://cdn.example.com/reel.mp4?sig=xyz",
    )
    result = ReelResult(
        final_artifact=artifact,
        requested_models={"director": None, "image": "gemini-3.1-flash-image-preview", "video": None},
        effective_models={
            "director": "gemini-2.5-flash",
            "image": "gemini-3.1-flash-image-preview",
            "video": "veo-3.1-generate-preview",
        },
        director_unused=False,
        api_surface="gemini_developer",
        sdk_version="2.23.0",
        audio_mode="separate",
        music_status="off",
        scenes=[scene_result],
        partial=False,
        warnings=[],
        final_duration_seconds=5.0,
    )

    dumped = result.model_dump(mode="json")

    assert isinstance(dumped, dict)
    assert isinstance(dumped["scenes"], list)
    assert all(isinstance(item, dict) for item in dumped["scenes"])
    assert dumped["final_artifact"]["download_url"] == "https://cdn.example.com/reel.mp4?sig=xyz"
    assert dumped["scenes"][0]["index"] == 0
    assert dumped["scenes"][0]["status"] == "succeeded"

    # AIMessage.artifacts is List[Dict[str, Any]] -- the final artifact must fit that shape.
    artifacts_entry = dumped["final_artifact"]
    assert isinstance(artifacts_entry, dict)


def test_reel_result_director_unused_when_scenes_supplied():
    """`director_unused=True` records that scenes were caller-supplied, director not invoked."""
    result = ReelResult(
        final_artifact=None,
        requested_models={"director": None, "image": "img", "video": None},
        effective_models={"director": None, "image": "img", "video": "veo-3.1-generate-preview"},
        director_unused=True,
        api_surface="gemini_developer",
        sdk_version="2.23.0",
        audio_mode="separate",
        music_status="skipped",
        scenes=[],
        partial=False,
        warnings=[],
        final_duration_seconds=None,
    )
    dumped = result.model_dump(mode="json")
    assert dumped["director_unused"] is True
    assert dumped["effective_models"]["director"] is None


def test_reel_scene_result_skipped_preserves_original_index():
    """A skipped scene under `partial_failure_policy='skip'` keeps its original index and error."""
    scene_result = ReelSceneResult(
        index=2,
        video_model="veo-3.1-generate-preview",
        backend="veo",
        status="skipped",
        requested_duration_seconds=5.0,
        error_code="safety_blocked",
        error_message="Content filtered by provider safety system.",
    )
    dumped = scene_result.model_dump(mode="json")
    assert dumped["index"] == 2
    assert dumped["status"] == "skipped"
    assert dumped["error_code"] == "safety_blocked"
