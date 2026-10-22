"""API-specific video model capability registry (FEAT-564, spec module M2).

One :class:`VideoModelProfile` per exact ``(surface, model_id)`` pair — never
substring matching (adding a future model is one verified entry plus a
contract test, per the spec's Module 2 docstring). :class:`VideoProfileRegistry`
resolves and validates a model before any paid provider call, and
:func:`select_generation_duration` picks the smallest legal covering duration.

Vertex GA entries are present but ``enabled=False`` pending the spec's §8 Q5
enablement gate — no Vertex capability claim here is a live-service readiness
claim; each profile's ``source``/``checked_on`` records where the capability
data came from.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, List, Literal, Optional

from pydantic import BaseModel, Field

from .errors import ReelErrorCode, ReelValidationError

ApiSurface = Literal["gemini_developer", "vertex"]

_VEO_DOCS_SOURCE = "https://ai.google.dev/gemini-api/docs/veo"
_OMNI_SDK_SOURCE = (
    "google-genai 2.23.0 offline introspection (sdd/state/FEAT-564/findings/F006-sdk.md); "
    "Omni output duration/MIME are otherwise unverified pending spec §8 Q3"
)
_CHECKED_ON = date(2026, 9, 17)


class VideoModelProfile(BaseModel):
    """Verified capability record for one model on one API surface.

    Args:
        model_id: Exact provider model identifier (never matched by substring).
        surface: The API surface this entry is valid for.
        backend: Which adapter generates clips for this model.
        enabled: Whether this profile may currently be resolved for use.
        durations_seconds: Legal generation durations in seconds, smallest
            first is not required. ``None`` means the backend has no
            user-selectable duration (Omni: provider default).
        resolutions: Resolutions this model accepts. Empty for a backend with
            no user-selectable resolution (Omni).
        resolution_min_duration: Per-resolution minimum legal duration, e.g.
            ``{"1080p": 8, "4k": 8}`` — a high-resolution request is forced to
            the smallest duration satisfying both this bound and the target.
        supports_starting_frame: Whether a starting-frame image is accepted.
        supports_reference_guidance: Whether provider ``reference_images``
            (asset guidance, not a starting frame) are accepted.
        native_audio: Whether the model can produce synchronized audio
            (``"always"``, ``"controllable"`` via a request flag, or
            ``"none"``).
        person_generation_values: Legal lowercase ``person_generation`` wire
            values for this model. Empty when the model has no such control.
        source: Where this capability data was verified.
        checked_on: When the capability data was last verified.
        max_outputs_per_request: Maximum number of videos one provider request
            may return.
    """

    model_id: str = Field(..., description="Exact provider model identifier.")
    surface: ApiSurface = Field(..., description="API surface this entry is valid for.")
    backend: Literal["veo", "omni"] = Field(..., description="Adapter that generates clips for this model.")
    enabled: bool = Field(..., description="Whether this profile may currently be resolved for use.")
    durations_seconds: Optional[List[int]] = Field(
        None, description="Legal generation durations in seconds; None = provider default (Omni)."
    )
    resolutions: List[str] = Field(
        default_factory=list, description="Resolutions accepted; empty when not user-selectable (Omni)."
    )
    resolution_min_duration: Dict[str, int] = Field(
        default_factory=dict, description='Per-resolution minimum legal duration, e.g. {"1080p": 8, "4k": 8}.'
    )
    supports_starting_frame: bool = Field(..., description="Whether a starting-frame image is accepted.")
    supports_reference_guidance: bool = Field(
        ..., description="Whether provider reference_images (asset guidance) are accepted."
    )
    native_audio: Literal["always", "controllable", "none"] = Field(
        ..., description="Whether/how the model can produce synchronized audio."
    )
    person_generation_values: List[str] = Field(
        default_factory=list, description="Legal lowercase person_generation wire values; empty if not applicable."
    )
    source: str = Field(..., description="Where this capability data was verified.")
    checked_on: date = Field(..., description="When the capability data was last verified.")
    max_outputs_per_request: int = Field(
        1,
        ge=1,
        description="Maximum videos one provider request may return (Omni > 1).",
    )


class VideoRequestOptions(BaseModel):
    """Normalised single-request video options validated against a profile."""

    resolution: Optional[str] = None
    duration_seconds: Optional[int] = None
    number_of_videos: int = 1
    has_starting_frame: bool = False
    has_last_frame: bool = False
    reference_image_count: int = 0
    extends_video: bool = False
    audio_mode: str = "separate"


class VideoProfileRegistry:
    """Central registry of verified (surface, model) capability profiles.

    Adding a GA model is one new :class:`VideoModelProfile` entry plus a
    contract test — never a ``"veo-3" in model_id``-style substring check.
    """

    def __init__(self, profiles: Iterable[VideoModelProfile]) -> None:
        self._by_surface_and_id: Dict[tuple[ApiSurface, str], VideoModelProfile] = {}
        self._by_id: Dict[str, List[VideoModelProfile]] = {}
        for profile in profiles:
            self._by_surface_and_id[(profile.surface, profile.model_id)] = profile
            self._by_id.setdefault(profile.model_id, []).append(profile)

    @classmethod
    def default(cls) -> "VideoProfileRegistry":
        """Developer API: Gemini Omni (enabled).

        Vertex: Veo 3.1 standard/Fast GA (``enabled=False``, pending spec §8 Q5).
        """
        veo_common = dict(
            backend="veo",
            durations_seconds=[4, 6, 8],
            supports_starting_frame=True,
            native_audio="controllable",
            person_generation_values=["allow_adult", "allow_all", "dont_allow"],
            source=_VEO_DOCS_SOURCE,
            checked_on=_CHECKED_ON,
        )
        standard_shape = dict(
            resolutions=["720p", "1080p", "4k"],
            resolution_min_duration={"1080p": 8, "4k": 8},
            supports_reference_guidance=True,
        )
        profiles = [
            VideoModelProfile(
                model_id="gemini-omni-1.1-flash",
                surface="gemini_developer",
                backend="omni",
                enabled=True,
                durations_seconds=None,
                resolutions=[],
                resolution_min_duration={},
                supports_starting_frame=False,
                supports_reference_guidance=False,
                native_audio="always",
                person_generation_values=[],
                max_outputs_per_request=4,
                source=_OMNI_SDK_SOURCE,
                checked_on=_CHECKED_ON,
            ),
            VideoModelProfile(
                model_id="veo-3.1-generate-001",
                surface="vertex",
                enabled=False,
                **veo_common,
                **standard_shape,
            ),
            VideoModelProfile(
                model_id="veo-3.1-fast-generate-001",
                surface="vertex",
                enabled=False,
                **veo_common,
                **standard_shape,
            ),
        ]
        return cls(profiles)

    def default_video_model(self, surface: ApiSurface) -> str:
        """Returns the configured default model id for an API surface.

        Args:
            surface: The API surface to resolve a default for.

        Returns:
            The default model id for that surface.

        Raises:
            ReelValidationError: If the surface has no default configured.
        """
        defaults: Dict[ApiSurface, str] = {
            "gemini_developer": "gemini-omni-1.1-flash",
            "vertex": "veo-3.1-generate-001",
        }
        try:
            return defaults[surface]
        except KeyError as exc:
            raise ReelValidationError(
                ReelErrorCode.UNKNOWN_MODEL, f"No default video model configured for surface {surface!r}."
            ) from exc

    def resolve(self, model_id: str, surface: ApiSurface) -> VideoModelProfile:
        """Resolves an exact (model_id, surface) pair to its verified profile.

        Args:
            model_id: The exact provider model identifier requested.
            surface: The API surface the request targets.

        Returns:
            The matching, enabled :class:`VideoModelProfile`.

        Raises:
            ReelValidationError: ``unknown_model`` if no profile exists for
                ``model_id`` on any surface; ``wrong_api_surface`` if it
                exists only on a different surface; ``model_disabled`` if it
                exists on this surface but is not enabled.
        """
        profile = self._by_surface_and_id.get((surface, model_id))
        if profile is not None:
            if not profile.enabled:
                raise ReelValidationError(
                    ReelErrorCode.MODEL_DISABLED,
                    f"Model {model_id!r} on surface {surface!r} is registered but not yet enabled.",
                )
            return profile

        if model_id in self._by_id:
            raise ReelValidationError(
                ReelErrorCode.WRONG_API_SURFACE,
                f"Model {model_id!r} is not registered for surface {surface!r}.",
            )

        raise ReelValidationError(ReelErrorCode.UNKNOWN_MODEL, f"Unknown video model {model_id!r}.")

    def validate_scene(
        self,
        profile: VideoModelProfile,
        *,
        resolution: str,
        audio_mode: str,
        has_starting_frame: bool,
    ) -> None:
        """Validates a scene's requested options against a resolved profile.

        Never silently drops an unsupported option — always raises instead.

        Args:
            profile: The profile resolved via :meth:`resolve`.
            resolution: The requested output resolution.
            audio_mode: The requested ``AudioMode`` (``"separate"``,
                ``"native"`` or ``"muted"``).
            has_starting_frame: Whether the scene supplies a starting frame.

        Raises:
            ReelValidationError: ``unsupported_option`` if the resolution,
                starting frame, or native-audio request is not supported by
                this profile.
        """
        if profile.resolutions and resolution not in profile.resolutions:
            raise ReelValidationError(
                ReelErrorCode.UNSUPPORTED_OPTION,
                f"Model {profile.model_id!r} does not support resolution {resolution!r} "
                f"(supported: {profile.resolutions}).",
            )
        if has_starting_frame and not profile.supports_starting_frame:
            raise ReelValidationError(
                ReelErrorCode.UNSUPPORTED_OPTION,
                f"Model {profile.model_id!r} does not support a starting-frame image.",
            )
        if audio_mode == "native" and profile.native_audio == "none":
            raise ReelValidationError(
                ReelErrorCode.UNSUPPORTED_OPTION,
                f"Model {profile.model_id!r} does not support native audio.",
            )

    def validate_request(self, profile: VideoModelProfile, *, request: VideoRequestOptions) -> None:
        """Validate all options in one provider video request against a profile.

        Raises:
            ReelValidationError: ``unsupported_option`` when the profile cannot
                honour any requested option.
        """
        if request.resolution is not None:
            if not profile.resolutions:
                raise ReelValidationError(
                    ReelErrorCode.UNSUPPORTED_OPTION,
                    f"Model {profile.model_id!r} does not support a user-selectable resolution.",
                )
            self.validate_scene(
                profile,
                resolution=request.resolution,
                audio_mode=request.audio_mode,
                has_starting_frame=request.has_starting_frame,
            )
        elif request.has_starting_frame or request.audio_mode == "native":
            self.validate_scene(
                profile,
                resolution=profile.resolutions[0] if profile.resolutions else "",
                audio_mode=request.audio_mode,
                has_starting_frame=request.has_starting_frame,
            )

        if request.duration_seconds is not None and (
            profile.durations_seconds is None or request.duration_seconds not in profile.durations_seconds
        ):
            raise ReelValidationError(
                ReelErrorCode.UNSUPPORTED_OPTION,
                f"Model {profile.model_id!r} does not support duration {request.duration_seconds!r} seconds.",
            )

        if request.number_of_videos > profile.max_outputs_per_request:
            raise ReelValidationError(
                ReelErrorCode.UNSUPPORTED_OPTION,
                f"Model {profile.model_id!r} supports at most {profile.max_outputs_per_request} videos per request.",
            )

        if request.has_last_frame and profile.backend != "veo":
            raise ReelValidationError(
                ReelErrorCode.UNSUPPORTED_OPTION,
                f"Model {profile.model_id!r} does not support a last-frame image.",
            )

        if request.extends_video and profile.backend != "veo":
            raise ReelValidationError(
                ReelErrorCode.UNSUPPORTED_OPTION,
                f"Model {profile.model_id!r} does not support video extension.",
            )

        if request.reference_image_count > 0 and not profile.supports_reference_guidance:
            raise ReelValidationError(
                ReelErrorCode.UNSUPPORTED_OPTION,
                f"Model {profile.model_id!r} does not support reference images.",
            )


def select_generation_duration(
    profile: VideoModelProfile,
    target_seconds: float,
    resolution: str,
    has_starting_frame: bool,  # noqa: ARG001 - part of the spec's public signature (future-proofing)
) -> Optional[int]:
    """Selects the smallest legal duration that covers ``target_seconds``.

    Applies the profile's ``resolution_min_duration`` floor first (a
    high-resolution request is forced up to that floor regardless of the
    target), then picks the smallest remaining legal duration at or above
    the target — falling back to the largest legal duration if the target
    exceeds every option (should not happen given the 8 s scene-edit cap).

    Args:
        profile: The resolved profile to select a duration from.
        target_seconds: The scene's edit target duration.
        resolution: The requested output resolution.
        has_starting_frame: Whether the scene supplies a starting frame
            (accepted for signature completeness; this profile set's
            duration math does not currently vary on it).

    Returns:
        The chosen legal duration in seconds, or ``None`` when the backend
        has no user-selectable duration (Omni: provider default).

    Raises:
        ReelValidationError: If no legal duration satisfies the resolution's
            minimum-duration floor.
    """
    if profile.durations_seconds is None:
        return None

    min_required = profile.resolution_min_duration.get(resolution)
    candidates = sorted(d for d in profile.durations_seconds if min_required is None or d >= min_required)
    if not candidates:
        raise ReelValidationError(
            ReelErrorCode.UNSUPPORTED_OPTION,
            f"No legal duration for model {profile.model_id!r} at resolution {resolution!r}.",
        )

    for duration in candidates:
        if duration >= target_seconds:
            return duration
    return candidates[-1]
