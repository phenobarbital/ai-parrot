"""
Google Related Models to be used in GenAI.
"""

from typing import Any, Literal, List, Dict, Optional
from enum import Enum
from datetime import datetime
import json
import math
from pydantic import BaseModel, Field, field_validator, model_validator, PrivateAttr


class GoogleVoiceModel(str, Enum):
    """
    Available models for Gemini Live API.

    Native Audio models support bidirectional voice streaming.
    See: https://ai.google.dev/gemini-api/docs/live
    """

    # Latest Native Audio models
    GEMINI_2_5_FLASH_NATIVE_AUDIO_LATEST = "gemini-2.5-flash-native-audio-preview-12-2025"
    GEMINI_2_5_FLASH_NATIVE_AUDIO_DEC_2025 = "gemini-2.5-flash-native-audio-preview-12-2025"
    GEMINI_2_5_FLASH_NATIVE_AUDIO_SEP_2025 = "gemini-2.5-flash-native-audio-preview-09-2025"
    GEMINI_2_5_FLASH_PREVIEW_TTS = "gemini-2.5-flash-preview-tts"
    GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"
    # Aliases
    DEFAULT = "gemini-2.5-flash-native-audio-preview-12-2025"

    @classmethod
    def all_models(cls) -> List[str]:
        """Get all available model strings."""
        return [m.value for m in cls if m.name not in ("DEFAULT",)]


# NEW: Enum for all valid TTS voice names
class TTSVoice(str, Enum):
    """Google TTS voices."""

    ACHERNAR = "achernar"
    ACHIRD = "achird"
    ALGENIB = "algenib"
    ALGIEBA = "algieba"
    ALNILAM = "alnilam"
    AOEDE = "aoede"
    AUTONOE = "autonoe"
    CALLIRRHOE = "callirrhoe"
    CHARON = "charon"
    DESPINA = "despina"
    ENCELADUS = "enceladus"
    ERINOME = "erinome"
    FENRIR = "fenrir"
    GACRUX = "gacrux"
    IAPETUS = "iapetus"
    KORE = "kore"
    LAOMEDEIA = "laomedeia"
    LEDA = "leda"
    ORUS = "orus"
    PUCK = "puck"
    PULCHERRIMA = "pulcherrima"
    RASALGETHI = "rasalgethi"
    SADACHBIA = "sadachbia"
    SADALTAGER = "sadaltager"
    SCHEDAR = "schedar"
    SULAFAT = "sulafat"
    UMBRIEL = "umbriel"
    VINDEMIATRIX = "vindemiatrix"
    ZEPHYR = "zephyr"


class MusicGenre(str, Enum):
    """
    Music Genres supported by Lyria.
    """

    ACID_JAZZ = "Acid Jazz"
    AFROBEAT = "Afrobeat"
    ALTERNATIVE_COUNTRY = "Alternative Country"
    BAROQUE = "Baroque"
    BENGAL_BAUL = "Bengal Baul"
    BHANGRA = "Bhangra"
    BLUEGRASS = "Bluegrass"
    BLUES_ROCK = "Blues Rock"
    BOSSA_NOVA = "Bossa Nova"
    BREAKBEAT = "Breakbeat"
    CELTIC_FOLK = "Celtic Folk"
    CHILLOUT = "Chillout"
    CHIPTUNE = "Chiptune"
    CLASSIC_ROCK = "Classic Rock"
    CONTEMPORARY_RNB = "Contemporary R&B"
    CUMBIA = "Cumbia"
    DEEP_HOUSE = "Deep House"
    DISCO_FUNK = "Disco Funk"
    DRUM_AND_BASS = "Drum & Bass"
    DUBSTEP = "Dubstep"
    EDM = "EDM"
    ELECTRO_SWING = "Electro Swing"
    FUNK_METAL = "Funk Metal"
    G_FUNK = "G-funk"
    GARAGE_ROCK = "Garage Rock"
    GLITCH_HOP = "Glitch Hop"
    GRIME = "Grime"
    HYPERPOP = "Hyperpop"
    INDIAN_CLASSICAL = "Indian Classical"
    INDIE_ELECTRONIC = "Indie Electronic"
    INDIE_FOLK = "Indie Folk"
    INDIE_POP = "Indie Pop"
    IRISH_FOLK = "Irish Folk"
    JAM_BAND = "Jam Band"
    JAMAICAN_DUB = "Jamaican Dub"
    JAZZ_FUSION = "Jazz Fusion"
    LATIN_JAZZ = "Latin Jazz"
    LO_FI_HIP_HOP = "Lo-Fi Hip Hop"
    MARCHING_BAND = "Marching Band"
    MERENGUE = "Merengue"
    NEW_JACK_SWING = "New Jack Swing"
    MINIMAL_TECHNO = "Minimal Techno"
    MOOMBAHTON = "Moombahton"
    NEO_SOUL = "Neo-Soul"
    ORCHESTRAL_SCORE = "Orchestral Score"
    PIANO_BALLAD = "Piano Ballad"
    POLKA = "Polka"
    POST_PUNK = "Post-Punk"
    PSYCHEDELIC_ROCK_60S = "60s Psychedelic Rock"
    PSYTRANCE = "Psytrance"
    RNB = "R&B"
    REGGAE = "Reggae"
    REGGAETON = "Reggaeton"
    RENAISSANCE_MUSIC = "Renaissance Music"
    SALSA = "Salsa"
    SHOEGAZE = "Shoegaze"
    SKA = "Ska"
    SURF_ROCK = "Surf Rock"
    SYNTHPOP = "Synthpop"
    TECHNO = "Techno"
    TRANCE = "Trance"
    TRAP_BEAT = "Trap Beat"
    TRIP_HOP = "Trip Hop"
    VAPORWAVE = "Vaporwave"
    WITCH_HOUSE = "Witch house"


class MusicMood(str, Enum):
    """
    Music Moods/Descriptions supported by Lyria.
    """

    ACOUSTIC_INSTRUMENTS = "Acoustic Instruments"
    AMBIENT = "Ambient"
    BRIGHT_TONES = "Bright Tones"
    CHILL = "Chill"
    CRUNCHY_DISTORTION = "Crunchy Distortion"
    DANCEABLE = "Danceable"
    DREAMY = "Dreamy"
    ECHO = "Echo"
    EMOTIONAL = "Emotional"
    ETHEREAL_AMBIENCE = "Ethereal Ambience"
    EXPERIMENTAL = "Experimental"
    FAT_BEATS = "Fat Beats"
    FUNKY = "Funky"
    GLITCHY_EFFECTS = "Glitchy Effects"
    HUGE_DROP = "Huge Drop"
    LIVE_PERFORMANCE = "Live Performance"
    LO_FI = "Lo-fi"
    OMINOUS_DRONE = "Ominous Drone"
    PSYCHEDELIC = "Psychedelic"
    RICH_ORCHESTRATION = "Rich Orchestration"
    SATURATED_TONES = "Saturated Tones"
    SUBDUED_MELODY = "Subdued Melody"
    SUSTAINED_CHORDS = "Sustained Chords"
    SWIRLING_PHASERS = "Swirling Phasers"
    TIGHT_GROOVE = "Tight Groove"
    UNSETTLING = "Unsettling"
    UPBEAT = "Upbeat"
    VIRTUOSO = "Virtuoso"
    WEIRD_NOISES = "Weird Noises"


class MusicGenerationRequest(BaseModel):
    """Request payload for Lyria music generation."""

    prompt: str = Field(..., description="Text description of the desired music.")
    genre: Optional[MusicGenre] = Field(None, description="Music genre.")
    mood: Optional[MusicMood] = Field(None, description="Music mood.")
    bpm: int = Field(90, ge=60, le=200, description="Beats per minute (60-200).")
    temperature: float = Field(1.0, ge=0.0, le=3.0, description="Creativity (0.0-3.0).")
    density: float = Field(0.5, ge=0.0, le=1.0, description="Note density (0.0-1.0).")
    brightness: float = Field(0.5, ge=0.0, le=1.0, description="Tonal brightness (0.0-1.0).")
    timeout: int = Field(300, ge=10, le=600, description="Max generation duration in seconds.")


class LyriaModel(str, Enum):
    """Available Lyria models for music generation."""

    LYRIA_002 = "lyria-002"
    LYRIA_REALTIME = "lyria-realtime-exp"


class MusicBatchRequest(BaseModel):
    """Request payload for Lyria batch music generation (Vertex AI)."""

    prompt: str = Field(..., min_length=1, description="Text description of the desired music in US English.")
    negative_prompt: Optional[str] = Field(
        None, description="Elements to exclude from generation (e.g., 'drums, vocals')."
    )
    seed: Optional[int] = Field(None, description="Deterministic seed for reproducible output.")
    sample_count: int = Field(1, ge=1, le=4, description="Number of audio samples to generate (1-4).")


class MusicBatchResponse(BaseModel):
    """Response from Lyria batch API."""

    audio_content: str = Field(..., description="Base64-encoded WAV audio")
    mime_type: str = Field(default="audio/wav")


class AspectRatio(str, Enum):
    """
    Supported aspect ratios for Gemini Image Generation.
    """

    RATIO_1_1 = "1:1"
    RATIO_2_3 = "2:3"
    RATIO_3_2 = "3:2"
    RATIO_3_4 = "3:4"
    RATIO_4_3 = "4:3"
    RATIO_4_5 = "4:5"
    RATIO_5_4 = "5:4"
    RATIO_9_16 = "9:16"
    RATIO_16_9 = "16:9"
    RATIO_21_9 = "21:9"


class ImageResolution(str, Enum):
    """
    Supported resolutions for Gemini Image Generation.
    NOTE: Not all models enforce this, purely advisory/typed.
    """

    RES_1K = "1K"
    RES_2K = "2K"
    RES_4K = "4K"


class FictionalSpeaker(BaseModel):
    """Configuration for a fictional character in the generated script."""

    name: str = Field(..., description="The name of the fictional speaker (e.g., 'Alex', 'Dr. Evans').")
    characteristic: str = Field(
        ...,
        description="A descriptive personality trait for the voice model, e.g., 'charismatic and engaging', 'skeptical and cautious', 'bored'.",
    )
    role: Literal["interviewer", "interviewee"] = Field(..., description="The role of the speaker in the conversation.")
    gender: Literal["female", "male", "neutral"] = Field(
        default="neutral",
        description="The gender of the speaker.",
    )


class ConversationalScriptConfig(BaseModel):
    """
    Configuration for generating a conversational script with fictional characters.
    """

    report_text: str = Field(..., description="The main text content of the script.")
    speakers: List[FictionalSpeaker] = Field(..., description="A list of fictional speakers to include in the script.")
    context: str = Field(
        ..., description="Background context for the conversation, e.g., 'Discussing recent scientific discoveries'."
    )
    length: int = Field(1000, description="Desired length of the script in words.")
    system_prompt: Optional[str] = Field(
        None, description="An optional system prompt to guide the AI's behavior during script generation."
    )
    system_instruction: Optional[str] = Field(
        None,
        description="An optional system instruction to provide additional context or constraints for the script generation.",
    )


# Define the gender type for clarity and validation
Gender = Literal["female", "male", "neutral"]


class VoiceProfile(BaseModel):
    """
    Represents a single pre-built generative voice, mapping its name
    to its known characteristics and gender.
    """

    voice_name: str = Field(..., description="The official name of the voice (e.g., 'Erinome').")
    characteristic: str = Field(..., description="The primary characteristic of the voice (e.g., 'Clear', 'Upbeat').")
    gender: Gender = Field(..., description="The perceived gender of the voice.")


# This list is based on the official documentation for Google's generative voices.
ALL_VOICE_PROFILES: List[VoiceProfile] = [
    VoiceProfile(voice_name="Zephyr", characteristic="Bright", gender="female"),
    VoiceProfile(voice_name="Puck", characteristic="Upbeat", gender="male"),
    VoiceProfile(voice_name="Charon", characteristic="Informative", gender="male"),
    VoiceProfile(voice_name="Kore", characteristic="Firm", gender="female"),
    VoiceProfile(voice_name="Fenrir", characteristic="Excitable", gender="male"),
    VoiceProfile(voice_name="Leda", characteristic="Youthful", gender="female"),
    VoiceProfile(voice_name="Orus", characteristic="Firm", gender="male"),
    VoiceProfile(voice_name="Aoede", characteristic="Breezy", gender="female"),
    VoiceProfile(voice_name="Callirrhoe", characteristic="Easy-going", gender="female"),
    VoiceProfile(voice_name="Autonoe", characteristic="Bright", gender="female"),
    VoiceProfile(voice_name="Enceladus", characteristic="Breathy", gender="male"),
    VoiceProfile(voice_name="Iapetus", characteristic="Clear", gender="male"),
    VoiceProfile(voice_name="Umbriel", characteristic="Easy-going", gender="male"),
    VoiceProfile(voice_name="Algieba", characteristic="Smooth", gender="male"),
    VoiceProfile(voice_name="Despina", characteristic="Smooth", gender="female"),
    VoiceProfile(voice_name="Erinome", characteristic="Clear", gender="female"),
    VoiceProfile(voice_name="Algenib", characteristic="Gravelly", gender="male"),
    VoiceProfile(voice_name="Rasalgethi", characteristic="Informative", gender="male"),
    VoiceProfile(voice_name="Laomedeia", characteristic="Upbeat", gender="female"),
    VoiceProfile(voice_name="Achernar", characteristic="Soft", gender="female"),
    VoiceProfile(voice_name="Alnilam", characteristic="Firm", gender="female"),
    VoiceProfile(voice_name="Schedar", characteristic="Even", gender="female"),
    VoiceProfile(voice_name="Gacrux", characteristic="Mature", gender="female"),
    VoiceProfile(voice_name="Pulcherrima", characteristic="Forward", gender="female"),
    VoiceProfile(voice_name="Achird", characteristic="Friendly", gender="female"),
    VoiceProfile(voice_name="Zubenelgenubi", characteristic="Casual", gender="male"),
    VoiceProfile(voice_name="Vindemiatrix", characteristic="Gentle", gender="female"),
    VoiceProfile(voice_name="Sadachbia", characteristic="Lively", gender="female"),
    VoiceProfile(voice_name="Sadaltager", characteristic="Knowledgeable", gender="male"),
    VoiceProfile(voice_name="Sulafat", characteristic="Warm", gender="female"),
]


class VoiceRegistry:
    """
    A comprehensive registry for managing and querying available voice profiles.
    """

    def __init__(self, profiles: List[VoiceProfile]):
        """Initializes the registry with a list of voice profiles."""
        self._voices: Dict[str, VoiceProfile] = {profile.voice_name.lower(): profile for profile in profiles}

    def find_voice_by_name(self, name: str) -> Optional[VoiceProfile]:
        """
        Finds a voice profile by its name (case-insensitive).

        Args:
            name: The name of the voice to find (e.g., 'Erinome', 'puck').
        Returns:
            A VoiceProfile object if found, otherwise None.
        """
        return self._voices.get(name.lower())

    def get_all_voices(self) -> List[VoiceProfile]:
        """Returns a list of all voice profiles in the registry."""
        return list(self._voices.values())

    def get_voices_by_gender(self, gender: Gender) -> List[VoiceProfile]:
        """
        Filters and returns all voices matching the specified gender.

        Args:
            gender: The gender to filter by ('female', 'male', or 'neutral').
        Returns:
            A list of matching VoiceProfile objects.
        """
        return [profile for profile in self._voices.values() if profile.gender == gender]

    def get_voices_by_characteristic(self, characteristic: str) -> List[VoiceProfile]:
        """
        Filters and returns all voices with a specific characteristic (case-insensitive).

        Args:
            characteristic: The characteristic to search for (e.g., 'Clear', 'upbeat').
        Returns:
            A list of matching VoiceProfile objects.
        """
        search_char = characteristic.lower()
        return [profile for profile in self._voices.values() if profile.characteristic.lower() == search_char]


# Reel-wide policy literals (spec §2 Data Models). Strings/literals only — core never imports
# provider enums; the Google satellite package owns capability resolution.
AudioMode = Literal["separate", "native", "muted"]
MusicPolicy = Literal["off", "optional", "required"]
PartialFailurePolicy = Literal["fail", "skip"]
VideoResolution = Literal["720p", "1080p", "4k"]


class VideoReelScene(BaseModel):
    """
    Configuration for a single scene in a video reel.
    """

    background_prompt: str = Field(..., description="Prompt for the background image generation.")
    foreground_prompt: Optional[str] = Field(
        None, description="Optional prompt for a foreground image (e.g., chart, KPI) to be overlayed."
    )
    video_prompt: str = Field(..., description="Prompt for the video generation model (Veo).")
    narration_text: Optional[str] = Field(None, description="Text for the narrator to read for this scene.")
    duration: float = Field(5.0, description="Estimated duration of the scene in seconds.")
    video_model: Optional[str] = Field(
        None,
        description=(
            "Scene video model override. None inherits the reel's `video_model`, which in turn "
            "inherits the API-surface default when it is also None."
        ),
    )
    reference_image: Optional[str] = Field(
        None,
        description=(
            "Path to a reference image for background generation. "
            "When provided, passed to generate_image(reference_images=[...]) "
            "to guide the background visual style."
        ),
    )

    @field_validator("duration")
    @classmethod
    def _validate_duration(cls, v: float) -> float:
        """Reject non-finite, <= 0 or > 8 second edit targets."""
        if not math.isfinite(v):
            raise ValueError("duration must be a finite number of seconds.")
        if not (0 < v <= 8):
            raise ValueError("duration must satisfy 0 < duration <= 8 seconds.")
        return v

    @field_validator("video_model")
    @classmethod
    def _reject_blank_model(cls, v: Optional[str]) -> Optional[str]:
        """None allowed (inherit); empty/whitespace raises."""
        if v is not None and not v.strip():
            raise ValueError("video_model must not be blank; omit it or set it to null to inherit.")
        return v


class VideoReelRequest(BaseModel):
    """
    Request configuration for generating a complete video reel.
    """

    _warnings: List[str] = PrivateAttr(default_factory=list)

    prompt: str = Field(..., description="High-level description of the desired video reel.")
    scenes: Optional[List[VideoReelScene]] = Field(
        None, description="List of scenes. If not provided, they will be generated from the prompt."
    )
    speech: Optional[List[str]] = Field(
        None,
        description=(
            "List of speech/narration texts, one per scene. "
            "If provided, each text will be used as narration for the corresponding scene. "
            "If not provided, no narration will be added to the video reel."
        ),
    )
    director_model: Optional[str] = Field(
        None,
        description=(
            "Model used to break the prompt down into scenes. "
            "None resolves to the default director model ('gemini-2.5-flash')."
        ),
    )
    model: Optional[str] = Field(
        None,
        description=(
            "Deprecated alias for `director_model`. Never selects the video model. "
            "Must be identical to `director_model` when both are supplied."
        ),
    )
    image_model: str = Field(
        "gemini-3.1-flash-image-preview",
        description="Model used for both background and foreground image generation.",
    )
    video_model: Optional[str] = Field(
        None,
        description=(
            "Reel-level video model. None resolves to the API-surface Veo 3.1 standard default. "
            "Overridden per scene by `VideoReelScene.video_model`."
        ),
    )
    resolution: VideoResolution = Field("720p", description="Target output resolution for the reel.")
    audio_mode: AudioMode = Field(
        "separate", description="Audio strategy: 'separate', 'native' (model sound) or 'muted'."
    )
    music_policy: MusicPolicy = Field(
        "optional", description="Background music policy: 'off', 'optional' (best-effort) or 'required'."
    )
    partial_failure_policy: PartialFailurePolicy = Field(
        "fail", description="Whether a single failed scene fails the job ('fail') or is skipped ('skip')."
    )
    music_prompt: Optional[str] = Field(None, description="Description for the background music.")
    music_genre: Optional[MusicGenre] = Field(None, description="Genre of the background music.")
    music_mood: Optional[MusicMood] = Field(None, description="Mood of the background music.")
    aspect_ratio: AspectRatio = Field(AspectRatio.RATIO_9_16, description="Aspect ratio for the generated reel.")
    transition_type: Literal["cut", "crossfade"] = Field("crossfade", description="Type of transition between scenes.")
    output_format: Literal["mp4", "webm"] = Field("mp4", description="Output video format.")
    reference_images: Optional[List[Optional[str]]] = Field(
        None,
        description=(
            "Sparse, order-preserving image slots, one per scene index. Populated by "
            "VideoReelHandler from multipart uploads (image_<index> parts or ordered slots). "
            "A null entry means no image was supplied for that slot; indices are preserved "
            "losslessly whether scenes are caller-supplied or director-produced. Image i is "
            "assigned to scene i."
        ),
    )
    storage_backend: Literal["fs", "temp", "s3", "gcs"] = Field(
        "fs",
        description=(
            "Storage backend for generated artifacts. "
            "'fs' for local filesystem, 'temp' for temporary directory, "
            "'s3' for AWS S3, 'gcs' for Google Cloud Storage."
        ),
    )
    storage_config: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Backend-specific configuration (e.g. bucket name, prefix). " "Required for 's3' and 'gcs' backends."
        ),
    )

    @field_validator("scenes", "speech", "storage_config", mode="before")
    @classmethod
    def _parse_json_strings(cls, v):
        """Accept JSON-encoded strings (from FormData) for scenes/speech/storage_config and parse them."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                pass
        return v

    @field_validator("reference_images")
    @classmethod
    def _validate_reference_images(cls, v: Optional[List[Optional[str]]]) -> Optional[List[Optional[str]]]:
        """Reject blank (non-null) slot values; null holes are preserved as empty slots."""
        if v is None:
            return v
        for item in v:
            if item is not None and not (isinstance(item, str) and item.strip()):
                raise ValueError("reference_images entries must be a non-blank path string, or null for an empty slot.")
        return v

    @model_validator(mode="before")
    @classmethod
    def _resolve_legacy_model_alias(cls, data: Any) -> Any:
        """Resolve the deprecated ``model`` alias into ``director_model``.

        ``model`` and ``director_model`` are compared once both are present: differing values
        raise ``ValueError``, identical values are accepted (a deprecation warning is recorded
        in ``_warnings`` once the model is built). An explicit ``null`` or blank string for any
        of ``model``/``director_model``/``image_model``/``video_model`` raises -- only an
        omitted key falls back to the field default.
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for key in ("model", "director_model", "image_model", "video_model"):
            if key not in data:
                continue
            value = data[key]
            if value is None:
                raise ValueError(f"`{key}` must not be explicitly null; omit it to use the default.")
            if isinstance(value, str) and not value.strip():
                raise ValueError(f"`{key}` must not be blank.")

        legacy = data.get("model")
        director = data.get("director_model")
        if legacy is not None and director is not None and legacy != director:
            raise ValueError(
                "`model` (deprecated alias for `director_model`) and `director_model` differ; "
                "supply only one, or make them identical."
            )
        if legacy is not None and director is None:
            data["director_model"] = legacy
        return data

    @model_validator(mode="after")
    def _record_legacy_alias_warning(self) -> "VideoReelRequest":
        """Record a deprecation warning whenever the legacy `model` alias was supplied."""
        if self.model is not None:
            self._warnings.append(f"`model` is deprecated; use `director_model` instead (received {self.model!r}).")
        return self

    @model_validator(mode="after")
    def _validate_audio_controls(self) -> "VideoReelRequest":
        """native/muted reject speech, music_prompt/genre/mood and music_policy='required'."""
        if self.audio_mode in ("native", "muted"):
            conflicts: List[str] = []
            if self.speech:
                conflicts.append("speech")
            if self.music_prompt:
                conflicts.append("music_prompt")
            if self.music_genre is not None:
                conflicts.append("music_genre")
            if self.music_mood is not None:
                conflicts.append("music_mood")
            if self.music_policy == "required":
                conflicts.append("music_policy='required'")
            if conflicts:
                raise ValueError(f"audio_mode={self.audio_mode!r} is incompatible with: {', '.join(conflicts)}")
        return self

    def effective_director_model(self) -> str:
        """Return the director model actually used: `director_model`, or its default."""
        return self.director_model or "gemini-2.5-flash"

    def deprecation_warnings(self) -> List[str]:
        """Return warnings collected during validation (e.g. use of the legacy `model` alias)."""
        return list(self._warnings)

    def image_for_scene(self, index: int) -> Optional[str]:
        """Return the sparse-preserving reference image path for scene `index`, if any.

        Indexes into the flat `reference_images` slot list rather than `scenes`, so it works
        uniformly for caller-supplied scenes and scenes produced later by the director.
        """
        if not self.reference_images or index < 0 or index >= len(self.reference_images):
            return None
        return self.reference_images[index]


class ReelArtifact(BaseModel):
    """Delivered artifact descriptor for a completed video reel."""

    artifact_id: str = Field(..., description="Opaque identifier used by the artifact delivery route.")
    storage_backend: Literal["fs", "temp", "s3", "gcs"] = Field(
        ..., description="Storage backend the artifact bytes live on."
    )
    storage_key: str = Field(..., description="Backend-relative key/path used to resolve the artifact.")
    mime_type: str = Field(..., description="MIME type of the final artifact.")
    size_bytes: int = Field(..., ge=0, description="Size of the artifact in bytes.")
    download_url: Optional[str] = Field(
        None,
        description=(
            "Signed or direct download URL. Always a string, never a Path; query strings are "
            "preserved exactly as issued."
        ),
    )
    expires_at: Optional[datetime] = Field(None, description="Expiry timestamp for `download_url`, if any.")


class ReelSceneResult(BaseModel):
    """Per-scene outcome of reel generation."""

    index: int = Field(..., description="Original scene index; preserved even when the scene is skipped.")
    video_model: str = Field(..., description="Resolved video model actually used for this scene.")
    backend: Literal["veo", "omni"] = Field(..., description="Backend adapter used to generate this scene's clip.")
    status: Literal["succeeded", "failed", "skipped"] = Field(..., description="Outcome of this scene.")
    requested_duration_seconds: float = Field(..., description="Edit target duration requested for this scene.")
    submitted_duration_seconds: Optional[float] = Field(
        None, description="Covering duration actually submitted to the provider."
    )
    measured_duration_seconds: Optional[float] = Field(None, description="Duration measured from the generated media.")
    final_duration_seconds: Optional[float] = Field(
        None, description="Duration retained for this scene in the assembled timeline."
    )
    provider_operation_id: Optional[str] = Field(
        None, description="Provider operation id, kept for reconciliation after ambiguous timeouts."
    )
    error_code: Optional[str] = Field(None, description="Stable ReelErrorCode value, if this scene failed.")
    error_message: Optional[str] = Field(
        None, description="Redacted error message; never includes keys or base64 payloads."
    )


class ReelResult(BaseModel):
    """Typed result of a video reel generation job, stored as `AIMessage.metadata['video_reel']`."""

    final_artifact: Optional[ReelArtifact] = Field(None, description="Delivered artifact, if the job produced one.")
    requested_models: Dict[str, Optional[str]] = Field(
        ..., description="Requested director/image/video models, as given on the request."
    )
    effective_models: Dict[str, Optional[str]] = Field(
        ..., description="Resolved director/image/video models actually used for generation."
    )
    director_unused: bool = Field(
        ..., description="True when scenes were supplied and the director model was never invoked."
    )
    api_surface: str = Field(..., description="API surface used for generation (e.g. 'gemini_developer', 'vertex').")
    sdk_version: str = Field(..., description="google-genai SDK version used for generation.")
    audio_mode: AudioMode = Field(..., description="Audio mode used for this job.")
    music_status: Literal["off", "succeeded", "unavailable", "timeout", "failed", "skipped"] = Field(
        ..., description="Outcome of background music generation."
    )
    scenes: List[ReelSceneResult] = Field(default_factory=list, description="Per-scene results, original order.")
    partial: bool = Field(False, description="True when `partial_failure_policy='skip'` dropped at least one scene.")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings, including deprecation notices.")
    final_duration_seconds: Optional[float] = Field(None, description="Final assembled reel duration in seconds.")
