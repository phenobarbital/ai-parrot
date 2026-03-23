"""
Google Text-to-Speech Tool migrated to use AbstractTool framework with async support.
"""
import asyncio
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Literal
from datetime import datetime
from xml.sax.saxutils import escape
import traceback
import aiofiles
import markdown
import bs4
from google.cloud import texttospeech_v1 as texttospeech
from google.oauth2 import service_account
from pydantic import BaseModel, Field, field_validator
from .abstract import AbstractTool


# Markdown cleaning utilities
MD_REPLACEMENTS = [
    # inline code: `print("hi")`   →  print("hi")
    (r"`([^`]*)`", r"\1"),
    # bold / italic: **text** or *text* or _text_  →  text
    (r"\*\*([^*]+)\*\*", r"\1"),
    (r"[_*]([^_*]+)[_*]", r"\1"),
    # strikethrough: ~~text~~
    (r"~~([^~]+)~~", r"\1"),
    # links: [label](url)  →  label
    (r"\[([^\]]+)\]\([^)]+\)", r"\1"),
]


def strip_markdown(text: str) -> str:
    """Remove the most common inline Markdown markers."""
    for pattern, repl in MD_REPLACEMENTS:
        text = re.sub(pattern, repl, text)
    return text


def markdown_to_plain(md: str) -> str:
    """Convert Markdown to plain text via HTML parsing."""
    html = markdown.markdown(md, extensions=["extra", "smarty"])
    return ''.join(bs4.BeautifulSoup(html, "html.parser").stripped_strings)


class GoogleTTSArgs(BaseModel):
    """Arguments schema for GoogleTTSTool."""

    text: str = Field(
        ...,
        description="The text content (plaintext or Markdown) to convert to speech"
    )
    voice_model: Optional[str] = Field(
        None,
        description="Specific Google voice model name (e.g., 'en-US-Neural2-F'). If None, selects based on language and gender"
    )
    voice_gender: Literal["MALE", "FEMALE"] = Field(
        "FEMALE",
        description="Voice gender preference when voice_model is not specified"
    )
    language_code: str = Field(
        "en-US",
        description="BCP-47 language code (e.g., 'en-US', 'es-ES', 'fr-FR')"
    )
    output_format: Literal["OGG_OPUS", "MP3", "LINEAR16", "MULAW", "ALAW", "PCM"] = Field(
        "OGG_OPUS",
        description="Audio output format"
    )
    file_prefix: str = Field(
        "podcast",
        description="Prefix for the output filename (timestamp and extension added automatically)"
    )
    speaking_rate: float = Field(
        1.0,
        description="Speaking rate (0.25 to 4.0, where 1.0 is normal speed)",
        ge=0.25,
        le=4.0
    )
    pitch: float = Field(
        0.0,
        description="Voice pitch (-20.0 to 20.0 semitones, where 0.0 is normal)",
        ge=-20.0,
        le=20.0
    )
    use_ssml: bool = Field(
        True,
        description="Whether to convert Markdown/text to SSML for better speech synthesis"
    )

    @field_validator('text')
    @classmethod
    def validate_text(cls, v):
        if not v or not v.strip():
            raise ValueError("Text content cannot be empty")
        return v

    @field_validator('language_code')
    @classmethod
    def validate_language_code(cls, v):
        # Basic validation for BCP-47 format
        if not re.match(r'^[a-z]{2,3}(-[A-Z]{2})?$', v):
            raise ValueError("Language code must be in BCP-47 format (e.g., 'en-US', 'es-ES')")
        return v


class GoogleVoiceTool(AbstractTool):
    """
    Tool for generating speech audio from text using Google Cloud Text-to-Speech.

    This tool converts text content (including Markdown) into high-quality speech audio
    using Google's neural voice models. It supports multiple languages, voice customization,
    and various audio output formats.

    Features:
    - Automatic Markdown to SSML conversion for natural speech
    - Multiple voice models and languages
    - Configurable speech parameters (rate, pitch)
    - Various audio output formats (OGG, MP3, WAV, etc.)
    - Async processing for better performance
    - Comprehensive error handling and logging
    """

    name = "google_tts_service"
    description = (
        "Generate speech audio from text using Google Cloud Text-to-Speech. "
        "Supports multiple languages, voice models, and output formats. "
        "Can process both plain text and Markdown content with natural speech synthesis."
    )
    args_schema = GoogleTTSArgs

    # Voice model mappings by language and gender
    VOICE_MODELS = {
        "en-US": {
            "MALE": "en-US-Neural2-D",
            "FEMALE": "en-US-Neural2-F"
        },
        "es-ES": {
            "MALE": "es-ES-Polyglot-1",
            "FEMALE": "es-ES-Neural2-H"
        },
        "fr-FR": {
            "MALE": "fr-FR-Neural2-G",
            "FEMALE": "fr-FR-Neural2-F"
        },
        "de-DE": {
            "MALE": "de-DE-Neural2-G",
            "FEMALE": "de-DE-Neural2-F"
        },
        "cmn-CN": {
            "MALE": "cmn-CN-Standard-B",
            "FEMALE": "cmn-CN-Standard-D"
        },
        "zh-CN": {
            "MALE": "cmn-CN-Standard-B",
            "FEMALE": "cmn-CN-Standard-D"
        },
        "ja-JP": {
            "MALE": "ja-JP-Neural2-C",
            "FEMALE": "ja-JP-Neural2-B"
        },
        "ko-KR": {
            "MALE": "ko-KR-Neural2-C",
            "FEMALE": "ko-KR-Neural2-A"
        },
        "pt-BR": {
            "MALE": "pt-BR-Neural2-B",
            "FEMALE": "pt-BR-Neural2-A"
        },
        "it-IT": {
            "MALE": "it-IT-Neural2-C",
            "FEMALE": "it-IT-Neural2-A"
        }
    }

    # Audio format mappings
    FORMAT_MAPPING = {
        "OGG_OPUS": (texttospeech.AudioEncoding.OGG_OPUS, "ogg"),
        "MP3": (texttospeech.AudioEncoding.MP3, "mp3"),
        "LINEAR16": (texttospeech.AudioEncoding.LINEAR16, "wav"),
        "MULAW": (texttospeech.AudioEncoding.MULAW, "wav"),
        "ALAW": (texttospeech.AudioEncoding.ALAW, "wav"),
        "PCM": (texttospeech.AudioEncoding.PCM, "pcm")
    }

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        default_voice_model: str = "en-US-Neural2-F",
        default_language: str = "en-US",
        default_format: str = "OGG_OPUS",
        use_long_audio_synthesis: bool = False,
        **kwargs
    ):
        """
        Initialize the Google TTS Tool.

        Args:
            credentials_path: Path to Google Cloud service account JSON file
            default_voice_model: Default voice model to use
            default_language: Default language code
            default_format: Default audio output format
            use_long_audio_synthesis: Whether to use long audio synthesis for texts >5000 chars
            **kwargs: Additional arguments for AbstractTool
        """
        super().__init__(**kwargs)

        # Set up credentials
        self.credentials_path = credentials_path or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        if not self.credentials_path:
            # Try common paths
            possible_paths = [
                Path.cwd() / "credentials" / "google-tts.json",
                Path.cwd() / "env" / "google" / "tts-service.json",
                Path(__file__).parent.parent / "credentials" / "google-tts.json"
            ]

            for path in possible_paths:
                if path.exists():
                    self.credentials_path = str(path)
                    break

        if not self.credentials_path or not Path(self.credentials_path).exists():
            raise ValueError(
                "Google TTS credentials not found. Please provide credentials_path or set "
                "GOOGLE_APPLICATION_CREDENTIALS environment variable."
            )

        # Configuration
        self.default_voice_model = default_voice_model
        self.default_language = default_language
        self.default_format = default_format
        self.use_long_audio_synthesis = use_long_audio_synthesis

        # Initialize credentials
        try:
            self.credentials = service_account.Credentials.from_service_account_file(
                self.credentials_path
            )
            self.logger.info(f"Google TTS tool initialized with credentials from: {self.credentials_path}")
        except Exception as e:
            raise ValueError(f"Failed to load Google TTS credentials: {e}")

    def _default_output_dir(self) -> Path:
        """Get the default output directory for TTS audio files."""
        return self.static_dir / "audio" / "tts"

    def _is_markdown(self, text: str) -> bool:
        """Determine if the text appears to be Markdown formatted."""
        if not text or not isinstance(text, str):
            return False

        text = text.strip()
        if not text:
            return False

        # Check first character for Markdown markers
        first_char = text[0]
        if first_char in "#*_>`-":
            return True

        # Check if first character is a digit (for numbered lists)
        if first_char.isdigit() and re.match(r'^\d+\.', text):
            return True

        # Check for common Markdown patterns
        markdown_patterns = [
            r"#{1,6}\s+",                    # Headers
            r"\*\*.*?\*\*",                  # Bold
            r"__.*?__",                      # Bold alternative
            r"\*.*?\*",                      # Italic
            r"_.*?_",                        # Italic alternative
            r"`.*?`",                        # Inline code
            r"\[.*?\]\(.*?\)",               # Links
            r"^\s*[\*\-\+]\s+",             # Unordered lists
            r"^\s*\d+\.\s+",                # Ordered lists
            r"```.*?```",                    # Code blocks
            r"^\s*>\s+",                     # Blockquotes
        ]

        for pattern in markdown_patterns:
            if re.search(pattern, text, re.MULTILINE | re.DOTALL):
                return True

        return False

    def _text_to_ssml(self, text: str) -> str:
        """Convert plain text to SSML."""
        escaped_text = escape(text)
        return f"<speak><p>{escaped_text}</p></speak>"

    def _markdown_to_ssml(self, markdown_text: str) -> str:
        """Convert Markdown text to SSML for natural speech synthesis."""
        # Handle code block prefixes
        if markdown_text.startswith("```text"):
            markdown_text = markdown_text[len("```text"):].strip()

        ssml = "<speak>"
        lines = markdown_text.split('\n')
        in_code_block = False

        for line in lines:
            line = line.strip()

            # Handle code blocks
            if line.startswith("```"):
                in_code_block = not in_code_block
                if in_code_block:
                    ssml += '<prosody rate="x-slow"><p>'
                else:
                    ssml += '</p></prosody>'
                continue

            if in_code_block:
                # Speak code slowly with pauses
                ssml += escape(line) + '<break time="200ms"/>'
                continue

            # Handle ellipses for dramatic pauses
            if line == "...":
                ssml += '<break time="1s"/>'
                continue

            # Handle Markdown headings
            heading_match = re.match(r"^(#+)\s+(.*)", line)
            if heading_match:
                heading_level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()

                # Vary emphasis based on heading level
                if heading_level == 1:
                    ssml += f'<p><emphasis level="strong"><prosody rate="slow">{escape(heading_text)}</prosody></emphasis></p><break time="500ms"/>'
                elif heading_level == 2:
                    ssml += f'<p><emphasis level="moderate">{escape(heading_text)}</emphasis></p><break time="300ms"/>'
                else:
                    ssml += f'<p><emphasis level="reduced">{escape(heading_text)}</emphasis></p><break time="200ms"/>'
                continue

            # Handle regular content
            if line:
                # Clean Markdown formatting for speech
                clean_text = strip_markdown(line)
                ssml += f'<p>{escape(clean_text)}</p>'

        ssml += "</speak>"
        return ssml

    def _select_voice_model(self, voice_model: Optional[str], language_code: str, voice_gender: str) -> str:
        """Select appropriate voice model based on parameters."""
        # If specific voice model provided, use it
        if voice_model:
            return voice_model

        # Select voice based on language and gender
        if language_code in self.VOICE_MODELS:
            return self.VOICE_MODELS[language_code].get(voice_gender, self.default_voice_model)

        # Fallback to default
        self.logger.warning(f"No voice model found for {language_code}:{voice_gender}, using default")
        return self.default_voice_model

    def _get_audio_config(self, output_format: str, speaking_rate: float, pitch: float) -> tuple:
        """Get audio encoding configuration and file extension."""
        if output_format not in self.FORMAT_MAPPING:
            available_formats = ', '.join(self.FORMAT_MAPPING.keys())
            raise ValueError(f"Unsupported output format: {output_format}. Available: {available_formats}")

        encoding, extension = self.FORMAT_MAPPING[output_format]

        audio_config = texttospeech.AudioConfig(
            audio_encoding=encoding,
            speaking_rate=speaking_rate,
            pitch=pitch
        )

        return audio_config, extension

    async def _synthesize_speech_short(
        self,
        text_input: str,
        voice_model: str,
        language_code: str,
        audio_config: texttospeech.AudioConfig,
        use_ssml: bool
    ) -> bytes:
        """Synthesize speech for shorter texts using standard API."""
        try:
            # Create async client
            client = texttospeech.TextToSpeechAsyncClient(credentials=self.credentials)

            # Prepare synthesis input
            if use_ssml:
                synthesis_input = texttospeech.SynthesisInput(ssml=text_input)
            else:
                synthesis_input = texttospeech.SynthesisInput(text=text_input)

            # Configure voice
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_model
            )

            # Make async request
            response = await client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )

            return response.audio_content

        except Exception as e:
            raise Exception(f"Speech synthesis failed: {str(e)}")

    async def _synthesize_speech_long(
        self,
        text_input: str,
        voice_model: str,
        language_code: str,
        audio_config: texttospeech.AudioConfig,
        output_gcs_uri: str,
        use_ssml: bool
    ) -> str:
        """Synthesize speech for longer texts using long audio synthesis API."""
        try:
            # Create long audio synthesis client
            client = texttospeech.TextToSpeechLongAudioSynthesizeAsyncClient(
                credentials=self.credentials
            )

            # Prepare synthesis input
            if use_ssml:
                synthesis_input = texttospeech.SynthesisInput(ssml=text_input)
            else:
                synthesis_input = texttospeech.SynthesisInput(text=text_input)

            # Configure voice
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_model
            )

            # Create request
            request = texttospeech.SynthesizeLongAudioRequest(
                input=synthesis_input,
                audio_config=audio_config,
                output_gcs_uri=output_gcs_uri,
                voice=voice
            )

            # Make async request
            operation = await client.synthesize_long_audio(request=request)

            self.logger.info("Waiting for long audio synthesis to complete...")
            response = await operation.result()

            return output_gcs_uri

        except Exception as e:
            raise Exception(f"Long audio synthesis failed: {str(e)}")

    async def _execute(
        self,
        text: str,
        voice_model: Optional[str] = None,
        voice_gender: str = "FEMALE",
        language_code: str = "en-US",
        output_format: str = "OGG_OPUS",
        file_prefix: str = "podcast",
        speaking_rate: float = 1.0,
        pitch: float = 0.0,
        use_ssml: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute text-to-speech conversion (AbstractTool interface).

        Args:
            text: Text content to convert to speech
            voice_model: Specific voice model or None for auto-selection
            voice_gender: Voice gender preference
            language_code: Language code (BCP-47 format)
            output_format: Audio output format
            file_prefix: Output filename prefix
            speaking_rate: Speech rate (0.25-4.0)
            pitch: Voice pitch (-20.0-20.0)
            use_ssml: Whether to use SSML processing
            **kwargs: Additional arguments

        Returns:
            Dictionary with synthesis results and file information
        """
        try:
            self.logger.info(f"Starting TTS synthesis: {len(text)} characters, {language_code}, {voice_gender}")

            # Select voice model
            selected_voice = self._select_voice_model(voice_model, language_code, voice_gender)

            # Get audio configuration
            audio_config, file_extension = self._get_audio_config(output_format, speaking_rate, pitch)

            # Process text based on type and SSML preference
            if use_ssml:
                if self._is_markdown(text):
                    self.logger.info("Converting Markdown to SSML")
                    processed_text = self._markdown_to_ssml(text)
                else:
                    self.logger.info("Converting plain text to SSML")
                    processed_text = self._text_to_ssml(text)
            else:
                processed_text = text

            # Generate output filename
            output_filename = self.generate_filename(
                prefix=file_prefix,
                extension=file_extension,
                include_timestamp=True
            )

            # Ensure output directory exists
            self.output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.output_dir / output_filename
            output_path = self.validate_output_path(output_path)

            # Determine synthesis method based on text length
            char_count = len(processed_text)
            use_long_synthesis = self.use_long_audio_synthesis and char_count > 5000

            if use_long_synthesis:
                self.logger.info(f"Using long audio synthesis for {char_count} characters")
                # Note: Long synthesis requires Google Cloud Storage
                # For now, fall back to standard synthesis
                self.logger.warning("Long audio synthesis requires GCS setup, falling back to standard synthesis")
                use_long_synthesis = False

            # Synthesize speech
            self.logger.info(f"Synthesizing speech with voice: {selected_voice}")

            audio_content = await self._synthesize_speech_short(
                processed_text,
                selected_voice,
                language_code,
                audio_config,
                use_ssml
            )

            # Save audio file
            self.logger.info(f"Saving audio to: {output_path}")
            async with aiofiles.open(output_path, 'wb') as audio_file:
                await audio_file.write(audio_content)

            # Generate URLs
            file_url = self.to_static_url(output_path)
            relative_url = self.relative_url(file_url)

            # Calculate file statistics
            file_size = output_path.stat().st_size
            duration_estimate = len(text.split()) / 2.5  # Rough estimate: ~150 WPM

            result = {
                "filename": output_filename,
                "file_path": str(output_path),
                "file_url": file_url,
                "relative_url": relative_url,
                "file_size": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2),
                "synthesis_info": {
                    "voice_model": selected_voice,
                    "language_code": language_code,
                    "voice_gender": voice_gender,
                    "output_format": output_format,
                    "speaking_rate": speaking_rate,
                    "pitch": pitch,
                    "used_ssml": use_ssml,
                    "was_markdown": use_ssml and self._is_markdown(text),
                    "character_count": len(text),
                    "processed_character_count": len(processed_text),
                    "estimated_duration_seconds": round(duration_estimate * 60, 1)
                },
                "generation_info": {
                    "timestamp": datetime.now().isoformat(),
                    "synthesis_method": "long" if use_long_synthesis else "standard",
                    "output_dir": str(self.output_dir)
                }
            }

            self.logger.info(f"TTS synthesis completed: {file_size} bytes, ~{duration_estimate:.1f} minutes")
            return result

        except Exception as e:
            self.logger.error(f"Error in TTS synthesis: {e}")
            self.logger.error(traceback.format_exc())
            raise

    def execute_sync(
        self,
        text: str,
        voice_model: Optional[str] = None,
        voice_gender: str = "FEMALE",
        language_code: str = "en-US",
        output_format: str = "OGG_OPUS",
        file_prefix: str = "podcast",
        speaking_rate: float = 1.0,
        pitch: float = 0.0,
        use_ssml: bool = True
    ) -> Dict[str, Any]:
        """
        Execute TTS synthesis synchronously.

        Args:
            text: Text content to convert to speech
            voice_model: Specific voice model
            voice_gender: Voice gender preference
            language_code: Language code
            output_format: Audio output format
            file_prefix: Output filename prefix
            speaking_rate: Speech rate
            pitch: Voice pitch
            use_ssml: Whether to use SSML

        Returns:
            Dictionary with synthesis results
        """
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self.execute(
                text=text,
                voice_model=voice_model,
                voice_gender=voice_gender,
                language_code=language_code,
                output_format=output_format,
                file_prefix=file_prefix,
                speaking_rate=speaking_rate,
                pitch=pitch,
                use_ssml=use_ssml
            ))
            return task
        except RuntimeError:
            return asyncio.run(self.execute(
                text=text,
                voice_model=voice_model,
                voice_gender=voice_gender,
                language_code=language_code,
                output_format=output_format,
                file_prefix=file_prefix,
                speaking_rate=speaking_rate,
                pitch=pitch,
                use_ssml=use_ssml
            ))

    def get_available_voices(self, language_code: Optional[str] = None) -> Dict[str, Any]:
        """Get available voice models for a language or all languages."""
        if language_code:
            return self.VOICE_MODELS.get(language_code, {})
        return self.VOICE_MODELS

    def get_supported_formats(self) -> Dict[str, str]:
        """Get supported audio output formats."""
        return {fmt: ext for fmt, (_, ext) in self.FORMAT_MAPPING.items()}

    def preview_ssml(self, text: str) -> str:
        """Preview how text would be converted to SSML."""
        try:
            if self._is_markdown(text):
                return self._markdown_to_ssml(text)
            else:
                return self._text_to_ssml(text)
        except Exception as e:
            self.logger.error(f"Error generating SSML preview: {e}")
            return f"<speak><p>Error generating SSML: {e}</p></speak>"

    def estimate_cost(self, text: str, use_ssml: bool = True) -> Dict[str, Any]:
        """Estimate the cost for TTS synthesis (rough calculation)."""
        # Process text to get accurate character count
        if use_ssml:
            if self._is_markdown(text):
                processed_text = self._markdown_to_ssml(text)
            else:
                processed_text = self._text_to_ssml(text)
        else:
            processed_text = text

        char_count = len(processed_text)

        # Google TTS pricing (as of 2024): $4 per 1M characters for Neural2 voices
        cost_per_million_chars = 4.0
        estimated_cost = (char_count / 1_000_000) * cost_per_million_chars

        return {
            "original_characters": len(text),
            "processed_characters": char_count,
            "estimated_cost_usd": round(estimated_cost, 4),
            "cost_breakdown": f"${cost_per_million_chars}/1M characters for Neural2 voices"
        }
