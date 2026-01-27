"""
Google Related Models to be used in GenAI.
"""
from typing import Literal, List, Dict, Optional
from enum import Enum
from pydantic import BaseModel, Field

class GoogleModel(Enum):
    """Enum for Google AI models."""
    GEMINI_3_PRO_PREVIEW = "gemini-3-pro-preview"
    GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_PREVIEW = "gemini-2.5-flash-preview-09-2025"
    GEMINI_2_5_FLASH_LITE_PREVIEW = "gemini-2.5-flash-lite-preview-09-2025"
    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_0_FLASH = "gemini-2.0-flash-001"
    GEMINI_PRO_LATEST = "gemini-pro-latest"
    GEMINI_FLASH_LATEST = "gemini-flash-latest"
    GEMINI_FLASH_LITE_LATEST = "gemini-flash-lite-latest"
    IMAGEN_3 = "imagen-3.0-generate-002"
    IMAGEN_4 = "imagen-4.0-generate-preview-06-06"
    GEMINI_2_0_IMAGE_GENERATION = "gemini-2.0-flash-preview-image-generation"
    GEMINI_2_5_FLASH_TTS = "gemini-2.5-flash-preview-tts"
    GEMINI_2_5_PRO_TTS = "gemini-2.5-pro-preview-tts"
    GEMINI_2_5_FLASH_IMAGE_PREVIEW = "gemini-2.5-flash-image-preview"
    GEMINI_2_5_FLASH_IMAGE = "gemini-2.5-flash-image"
    GEMINI_3_PRO_IMAGE_PREVIEW = "gemini-3-pro-image-preview"
    VEO_3_0 = "veo-3.0-generate-preview"
    VEO_2_0 = "veo-2.0-generate-001"
    VEO_3_0_FAST = "veo-3.0-fast-generate-001"
    LYRIA = "models/lyria-realtime-exp"

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
    # Aliases
    DEFAULT = "gemini-2.5-flash-native-audio-preview-12-2025"

    @classmethod
    def all_models(cls) -> List[str]:
        """Get all available model strings."""
        return [m.value for m in cls if m.name not in ('DEFAULT',)]

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


class VertexAIModel(Enum):
    """Enum for Vertex AI models."""
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE_PREVIEW = "gemini-2.5-flash-lite-preview-06-17"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_0_FLASH = "gemini-2.0-flash-001"
    IMAGEN_3_FAST = "Imagen 3 Fast"


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
    name: str = Field(
        ...,
        description="The name of the fictional speaker (e.g., 'Alex', 'Dr. Evans')."
    )
    characteristic: str = Field(
        ...,
        description="A descriptive personality trait for the voice model, e.g., 'charismatic and engaging', 'skeptical and cautious', 'bored'."
    )
    role: Literal['interviewer', 'interviewee'] = Field(
        ...,
        description="The role of the speaker in the conversation."
    )
    gender: Literal['female', 'male', 'neutral'] = Field(
        default='neutral',
        description="The gender of the speaker.",
    )


class ConversationalScriptConfig(BaseModel):
    """
    Configuration for generating a conversational script with fictional characters.
    """
    report_text: str = Field(
        ...,
        description="The main text content of the script."
    )
    speakers: List[FictionalSpeaker] = Field(
        ...,
        description="A list of fictional speakers to include in the script."
    )
    context: str = Field(
        ...,
        description="Background context for the conversation, e.g., 'Discussing recent scientific discoveries'."
    )
    length: int = Field(
        1000,
        description="Desired length of the script in words."
    )
    system_prompt: Optional[str] = Field(
        None,
        description="An optional system prompt to guide the AI's behavior during script generation."
    )
    system_instruction: Optional[str] = Field(
        None,
        description="An optional system instruction to provide additional context or constraints for the script generation."
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
# It represents the "HTML table" data you referred to.
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
        self._voices: Dict[str, VoiceProfile] = {
            profile.voice_name.lower(): profile for profile in profiles
        }

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
        return [
            profile for profile in self._voices.values() if profile.gender == gender
        ]

    def get_voices_by_characteristic(self, characteristic: str) -> List[VoiceProfile]:
        """
        Filters and returns all voices with a specific characteristic (case-insensitive).

        Args:
            characteristic: The characteristic to search for (e.g., 'Clear', 'upbeat').
        Returns:
            A list of matching VoiceProfile objects.
        """
        search_char = characteristic.lower()
        return [
            profile for profile in self._voices.values()
            if profile.characteristic.lower() == search_char
        ]
