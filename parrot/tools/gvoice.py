import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Type, Union
import os
import re
from xml.sax.saxutils import escape
from datetime import datetime
import traceback
import json
import markdown
import bs4
import aiofiles
# Use v1 for wider feature set including SSML
from google.cloud import texttospeech_v1 as texttospeech
from google.oauth2 import service_account
from pydantic import BaseModel, Field, ConfigDict
from langchain.tools import BaseTool
from navconfig import BASE_DIR
from .abstract import BaseAbstractTool
from ..conf import GOOGLE_TTS_SERVICE


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

INLINE_CODE_RE = re.compile(r"`([^`]*)`")

def strip_markdown(text: str) -> str:
    """Remove the most common inline Markdown markers."""
    for pattern, repl in MD_REPLACEMENTS:
        text = re.sub(pattern, repl, text)
    return text

def markdown_to_plain(md: str) -> str:
    html = markdown.markdown(md, extensions=["extra", "smarty"])
    return ''.join(bs4.BeautifulSoup(html, "html.parser").stripped_strings)

def strip_inline_code(text: str) -> str:
    return INLINE_CODE_RE.sub(r"\1", text)


class PodcastInput(BaseModel):
    """
    Input schema for the GoogleVoiceTool.  Users can supply:
    • text (required): the transcript or Markdown to render.
    • voice_gender: choose “MALE” or “FEMALE” (default is FEMALE).
    • voice_model: a specific voice name if you want to override the default.
    • language_code: e.g. “en-US” or “es-ES” (default is “en-US”).
    • output_format: one of “OGG_OPUS”, “MP3”, “LINEAR16”, etc. (default is “OGG_OPUS”).
    """
    # Add a model_config to prevent additional properties
    model_config = ConfigDict(extra='forbid')
    text: str = Field(..., description="The text (plaintext or Markdown) to convert to speech")
    voice_gender: Optional[str] = Field(
        None,
        description="Optionally override the gender of the chosen voice (MALE or FEMALE)."
    )
    voice_model: Optional[str] = Field(
        None,
        description=(
            "Optionally specify a precise Google voice model name "
            "(e.g. “en-US-Neural2-F”, “en-US-Neural2-M”, etc.)."
        )
    )
    language_code: Optional[str] = Field(
        None,
        description="BCP-47 language code (e.g. “en-US” or “es-ES”). Defaults to en-US."
    )
    output_format: Optional[str] = Field(
        None,
        description=(
            "Audio encoding format: one of [“OGG_OPUS”, “MP3”, “LINEAR16”, “WEBM_OPUS”, “FLAC”, “OGG_VORBIS”]."
        )
    )
    # If you’d like users to control the output filename/location:
    file_prefix: str | None = Field(
        default="document",
        description="Stem for the output file. Timestamp and extension added automatically."
    )

class GoogleVoiceTool(BaseAbstractTool):
    """Generate a podcast-style audio file from Text using Google Cloud Text-to-Speech."""
    name: str = "podcast_generator_tool"
    description: str = (
        "Generates a podcast-style audio file from a given text (plain or markdown) script using Google Cloud Text-to-Speech."
        " Use this tool if the user requests a podcast, an audio summary, or a narrative of your findings."
        " The user must supply a JSON object matching the PodcastInput schema."
    )
    voice_model: str = "en-US-Neural2-F"  # "en-US-Studio-O"
    voice_gender: str = "FEMALE"
    language_code: str = "en-US"
    output_format: str = "OGG_OPUS"  # OGG format is more podcast-friendly
    _key_service: Optional[str]

    # Add a proper args_schema for tool-calling compatibility
    args_schema: Type[BaseModel] = PodcastInput

    def __init__(
        self,
        *args,
        voice_model: str = "en-US-Neural2-F",
        output_format: str = "OGG_OPUS",
        language_code: str = "en-US",
        **kwargs
    ):
        """Initialize the GoogleVoiceTool."""

        super().__init__(*args, **kwargs)

        # Using the config from conf.py, but with additional verification
        self._key_service = GOOGLE_TTS_SERVICE

        # If not found in the config, try a default location
        if self._key_service is None:
            default_path = BASE_DIR.joinpath("env", "google", "tts-service.json")
            if default_path.exists():
                self._key_service = str(default_path)
                print(f"🔑 Using default credentials path: {self._key_service}")
            else:
                print(
                    f"⚠️ Warning: No TTS credentials found in config or at {default_path}"
                )
        else:
            print(f"🔑 Using credentials from config: {self._key_service}")

        # Set the defaults from constructor arguments
        self.voice_model = voice_model
        self.output_format = output_format
        self.language_code = language_code or "en-US"

    def _default_output_dir(self) -> Path:
        """Get default output directory for Podcasts files."""
        return self.static_dir.joinpath('documents', 'podcasts')

    def _generate_payload(self, **kwargs) -> PodcastInput:
        """Generate a PodcastInput payload from the provided arguments."""
        # Filter out None values to let Pydantic use defaults
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        return PodcastInput(**filtered_kwargs)

    def is_markdown(self, text: str) -> bool:
        """Determine if the text appears to be Markdown formatted."""
        if not text or not isinstance(text, str):
            return False

        # Check if first char is a Markdown marker
        if re.search(r"^[#*_>`\[\d-]", text.strip()[0]):
            return True

        # Check for common Markdown patterns
        patterns = [
            r"#{1,6}\s+",  # Headers
            r"\*\*.*?\*\*",  # Bold
            r"_.*?_",  # Italic
            r"`.*?`",  # Code
            r"\[.*?\]\(.*?\)",  # Links
            r"^\s*[\*\-\+]\s+",  # Unordered lists
            r"^\s*\d+\.\s+",  # Ordered lists
            r"```.*?```",  # Code blocks
        ]

        for pattern in patterns:
            flags = re.MULTILINE if pattern.startswith('^') else 0
            if re.search(pattern, text, flags):
                return True
        return False

    def text_to_ssml(self, text: str) -> str:
        """Converts plain text to SSML."""
        ssml = f"<speak><p>{escape(text)}</p></speak>"
        return ssml

    def markdown_to_ssml(self, markdown_text: str) -> str:
        """Converts Markdown text to SSML, handling code blocks and ellipses."""

        if markdown_text.startswith("```text"):
            markdown_text = markdown_text[len("```text"):].strip()

        ssml = "<speak>"
        lines = markdown_text.split('\n')
        in_code_block = False

        for line in lines:
            line = line.strip()

            if line.startswith("```"):
                in_code_block = not in_code_block
                if in_code_block:
                    ssml += '<prosody rate="x-slow"><p><code>'
                else:
                    ssml += '</code></p></prosody>'
                continue

            if in_code_block:
                ssml += escape(line) + '<break time="100ms"/>'  # Add slight pauses within code
                continue

            if line == "...":
                ssml += '<break time="500ms"/>'  # Keep the pause for ellipses
                continue

            # Handle Markdown headings
            heading_match = re.match(r"^(#+)\s+(.*)", line)
            if heading_match:
                heading_level = len(heading_match.group(1))  # Number of '#'
                heading_text = heading_match.group(2).strip()
                ssml += f'<p><emphasis level="strong">{escape(heading_text)}</emphasis></p>'
                continue

            if line:
                clean = strip_markdown(line)
                ssml += f'<p>{escape(clean)}</p>'

        ssml += "</speak>"
        return ssml

    def _select_voice_model(self, payload: PodcastInput) -> tuple[str, str]:
        """Select appropriate voice model based on language and gender."""
        # Use payload values or instance defaults
        language_code = payload.language_code or self.language_code
        voice_gender = payload.voice_gender or self.voice_gender

        # If specific voice model provided, use it
        if payload.voice_model:
            return payload.voice_model, voice_gender

        # Select voice based on language and gender
        voice_models = {
            "es-ES": {
                "MALE": "es-ES-Polyglot-1",
                "FEMALE": "es-ES-Neural2-H"
            },
            "en-US": {
                "MALE": "en-US-Neural2-D",
                "FEMALE": "en-US-Neural2-F"
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
            }
        }

        return voice_models.get(language_code, {}).get(voice_gender, self.voice_model), voice_gender

    def _get_audio_encoding_and_extension(self, output_format: str) -> tuple:
        """Get the appropriate audio encoding and file extension for the output format."""
        # Only include formats actually supported by Google Cloud TTS AudioEncoding enum
        format_mapping = {
            "OGG_OPUS": (texttospeech.AudioEncoding.OGG_OPUS, "ogg"),
            "MP3": (texttospeech.AudioEncoding.MP3, "mp3"),
            "LINEAR16": (texttospeech.AudioEncoding.LINEAR16, "wav"),
            "MULAW": (texttospeech.AudioEncoding.MULAW, "wav"),
            "ALAW": (texttospeech.AudioEncoding.ALAW, "wav"),
            "PCM": (texttospeech.AudioEncoding.PCM, "pcm")
        }

        if output_format.upper() not in format_mapping:
            available_formats = ', '.join(format_mapping.keys())
            raise ValueError(
                f"Unsupported output format: {output_format}. "
                f"Google Cloud TTS only supports: {available_formats}."
            )

        return format_mapping[output_format.upper()]

    async def _generate_content(self, payload: PodcastInput) -> Dict[str, Any]:
        """Main method to generate a podcast from query."""
        # Validate credentials
        if not self._key_service or not Path(self._key_service).exists():
            raise FileNotFoundError(
                f"Service account file not found: {self._key_service}"
            )
        # Select voice model and configure language
        voice_model, voice_gender = self._select_voice_model(payload)
        language_code = payload.language_code or self.language_code
        try:
            self.logger.info("1. Converting Markdown to SSML...")
            if self.is_markdown(payload.text):
                ssml_text = self.markdown_to_ssml(payload.text)
            else:
                ssml_text = self.text_to_ssml(payload.text)
            self.logger.info(
                f"2. Initializing Text-to-Speech client (Voice: {voice_model})..."
            )
            # Initialize the Text-to-Speech client with the service account credentials
            credentials = service_account.Credentials.from_service_account_file(
                self._key_service
            )
            # Use the v1 API for wider feature set including SSML
            client = texttospeech.TextToSpeechClient(credentials=credentials)
            synthesis_input = texttospeech.SynthesisInput(ssml=ssml_text)
            # Select the voice parameters
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_model
            )
            # Configure audio format
            output_format = payload.output_format or self.output_format
            encoding, ext = self._get_audio_encoding_and_extension(output_format)

            # Select the audio format (OGG with OPUS codec)
            # Generate filename using base class method
            output_filename = self.generate_filename(
                prefix=payload.file_prefix or "podcast",
                extension=ext,
                include_timestamp=True
            )
            output_filepath = self.output_dir.joinpath(output_filename)
            audio_config = texttospeech.AudioConfig(
                audio_encoding=encoding,
                speaking_rate=1.0,
                pitch=0.0
            )
            self.logger.info("3. Synthesizing speech...")
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            self.logger.info("4. Speech synthesized successfully.")
            self.logger.info(f"5. Saving audio content to: {output_filepath}")
            async with aiofiles.open(output_filepath, 'wb') as audio_file:
                await audio_file.write(response.audio_content)
            self.logger.info("6. Audio content saved successfully.")
            url = self.to_static_url(output_filepath)
            return {
                "status": "success",
                "message": "Podcast audio generated successfully.",
                "text": payload.text,
                "ssml": ssml_text,
                "output_format": output_format,
                "language_code": self.language_code,
                "voice_model": self.voice_model,
                "voice_gender": self.voice_gender,
                "file_path": self.output_dir,
                "filename": output_filepath,
                "url": url,
                "static_url": self.relative_url(url),
            }
        except Exception as e:
            print(f"Error in _generate_podcast: {e}")
            print(traceback.format_exc())
            return {"error": str(e)}
