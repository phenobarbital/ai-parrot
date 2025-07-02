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
from parrot.conf import GOOGLE_TTS_SERVICE


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

class GoogleVoiceTool(BaseTool):
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
    output_dir: Optional[Path] = None

    # Add a proper args_schema for tool-calling compatibility
    args_schema: Type[BaseModel] = PodcastInput

    def __init__(self,
        voice_model: str = "en-US-Neural2-F",
        output_format: str = "OGG_OPUS",
        language_code: str = "en-US",
        output_dir: str = None,
        name: str = "podcast_generator_tool",
        **kwargs
    ):
        """Initialize the GoogleVoiceTool."""

        super().__init__(**kwargs)

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

        # Set the output directory
        self.output_dir = Path(output_dir) if output_dir else BASE_DIR.joinpath("static", "documents", "podcasts")
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def is_markdown(self, text: str) -> bool:
        """Determine if the text appears to be Markdown formatted."""
        if not text or not isinstance(text, str):
            return False

        # Corrección: Separar los caracteres problemáticos y el rango
        if re.search(r"^[#*_>`\[\d-]", text.strip()[0]):  # Check if first char is a Markdown marker
            return True

        # Check for common Markdown patterns
        if re.search(r"#{1,6}\s+", text):  # Headers
            return True
        if re.search(r"\*\*.*?\*\*", text):  # Bold
            return True
        if re.search(r"_.*?_", text):  # Italic
            return True
        if re.search(r"`.*?`", text):  # Code
            return True
        if re.search(r"\[.*?\]\(.*?\)", text):  # Links
            return True
        if re.search(r"^\s*[\*\-\+]\s+", text, re.MULTILINE):  # Unordered lists
            return True
        if re.search(r"^\s*\d+\.\s+", text, re.MULTILINE):  # Ordered lists
            return True
        if re.search(r"```.*?```", text, re.DOTALL):  # Code blocks
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

    async def _generate_podcast(self, payload: PodcastInput) -> dict:
        """Main method to generate a podcast from query."""
        # define voice gender:
        if payload.voice_gender:
            self.voice_gender = payload.voice_gender
        # Select voice based on language_code:
        if payload.language_code:
            self.language_code = payload.language_code
        if self.language_code == "es-ES":
            if self.voice_gender == "MALE":
                self.voice_model = "es-ES-Polyglot-1"
            else:
                self.voice_model = "es-ES-Neural2-H"
        elif self.language_code == "en-US":
            if self.voice_gender == "MALE":
                self.voice_model = "en-US-Neural2-D"
            else:
                self.voice_model = "en-US-Neural2-F"
        elif self.language_code == "fr-FR":
            if self.voice_gender == "MALE":
                self.voice_model = "fr-FR-Neural2-G"
            else:
                self.voice_model = "fr-FR-Neural2-F"
        elif self.language_code == "de-DE":
            if self.voice_gender == "MALE":
                self.voice_model = "de-DE-Neural2-G"
            else:
                self.voice_model = "de-DE-Neural2-F"
        elif self.language_code in ("cmn-CN", "zh-CN"):
            if self.voice_gender == "MALE":
                self.voice_model = "cmn-CN-Standard-B"
            else:
                self.voice_model = "cmn-CN-Standard-D"
        try:
            if self._key_service and Path(self._key_service).exists():
                try:
                    credentials = service_account.Credentials.from_service_account_file(
                        self._key_service
                    )
                except Exception as cred_error:
                    print(f"Error loading credentials: {cred_error}")

            print("1. Converting Markdown to SSML...")
            if self.is_markdown(payload.text):
                ssml_text = self.markdown_to_ssml(payload.text)
            else:
                ssml_text = self.text_to_ssml(payload.text)
            print(f"Generated SSML:\n{ssml_text}\n") # Uncomment for debugging
            print(
                f"2. Initializing Text-to-Speech client (Voice: {self.voice_model})..."
            )
            if not os.path.exists(self._key_service):
                raise FileNotFoundError(
                    f"Service account file not found: {self._key_service}"
                )
            credentials = service_account.Credentials.from_service_account_file(
                self._key_service
            )
            # Initialize the Text-to-Speech client with the service account credentials
            # Use the v1 API for wider feature set including SSML
            client = texttospeech.TextToSpeechClient(credentials=credentials)
            synthesis_input = texttospeech.SynthesisInput(ssml=ssml_text)
            # Select the voice parameters
            voice = texttospeech.VoiceSelectionParams(
                language_code=self.language_code,
                name=self.voice_model
            )
            # Select the audio format (OGG with OPUS codec)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = payload.file_prefix or "podcast"
            # Generate a unique filename based on the current timestamp
            output_filename = f"podcast_{timestamp}.ogg"  # Default output filename
            # default to OGG
            if payload.output_format:
                output_format = payload.output_format.upper()
            else:
                output_format = self.output_format.upper()
            encoding = texttospeech.AudioEncoding.OGG_OPUS
            if output_format == "OGG_OPUS":
                encoding = texttospeech.AudioEncoding.OGG_OPUS
                ext = "ogg"
            elif output_format == "MP3":
                encoding = texttospeech.AudioEncoding.MP3
                ext = "mp3"
            elif output_format == "LINEAR16":
                encoding = texttospeech.AudioEncoding.LINEAR16
                ext = "wav"
            elif output_format in ("WEBM_OPUS", "WEBM", "WEBM_OPUS_V2"):
                encoding = texttospeech.AudioEncoding.WEBM_OPUS
                ext = "webm"
            elif output_format == "FLAC":
                encoding = texttospeech.AudioEncoding.FLAC
                ext = "flac"
            elif output_format == "OGG_VORBIS":
                encoding = texttospeech.AudioEncoding.OGG_VORBIS
                ext = "ogg"
            else:
                raise ValueError(
                    f"Unsupported output format: {output_format}. "
                    "Supported formats are: OGG_OPUS, MP3, LINEAR16, WEBM_OPUS, FLAC, OGG_VORBIS."
                )
            output_filename = f"{prefix}_{timestamp}.{ext}"

            audio_config = texttospeech.AudioConfig(
                audio_encoding=encoding,
                speaking_rate=1.0,
                pitch=0.0
            )
            print("3. Synthesizing speech...")
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            print("4. Speech synthesized successfully.")
            output_filepath = self.output_dir.joinpath(output_filename)
            print(f"5. Saving audio content to: {output_filepath}")
            async with aiofiles.open(output_filepath, 'wb') as audio_file:
                await audio_file.write(response.audio_content)
            print("6. Audio content saved successfully.")
            return {
                "status": "success",
                "message": "Podcast audio generated successfully.",
                "text": payload.text,
                "ssml": ssml_text,
                "output_format": output_format,
                "language_code": self.language_code,
                "voice_model": self.voice_model,
                "voice_gender": self.voice_gender,
                "timestamp": timestamp,
                "file_path": self.output_dir,
                "filename": output_filepath
            }
        except Exception as e:
            print(f"Error in _generate_podcast: {e}")
            print(traceback.format_exc())
            return {"error": str(e)}

    async def _arun(
        self,
        text: str,
        voice_gender: Optional[str] = None,
        voice_model: Optional[str] = None,
        language_code: Optional[str] = None,
        output_format: Optional[str] = None,
        file_prefix: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        LangChain will call this with keyword args matching PodcastInput, e.g.:
          _arun(text="Hello", voice_gender="MALE", output_format="MP3", …)

        We rebuild a PodcastInput object internally so that we benefit from Pydantic’s
        validation and type‐casting, then delegate to _generate_podcast().
        """
        try:
            # 1) Build a dict of everything LangChain passed us
            payload_dict = {
                "text": text,
                "voice_gender": voice_gender,
                "voice_model": voice_model,
                "language_code": language_code,
                "output_format": output_format,
                "file_prefix": file_prefix
            }
            # 2) Let Pydantic validate & coerce
            payload = PodcastInput(**{k: v for k, v in payload_dict.items() if v is not None})
            # 3) Call the “real” generator
            return await self._generate_podcast(payload)
        except Exception as e:
            print(f"❌ Error in GoogleVoiceTool._arun: {e}")
            print(traceback.format_exc())
            return {"error": str(e)}

    # Mirror the same signature for the synchronous runner:
    def _run(
        self,
        text: Union[str, Dict[str, Any]],
        voice_gender: Optional[str] = None,
        voice_model: Optional[str] = None,
        language_code: Optional[str] = None,
        output_format: Optional[str] = None,
        file_prefix: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Synchronous entrypoint. If text_or_json is a JSON string, we load it first.
        Otherwise, assume it’s already a dict of the correct shape.
        """
        try:
            if isinstance(text, str):
                data = json.loads(text)
                # We expect a JSON‐dict with keys matching PodcastInput
            elif isinstance(text, dict):
                data = text
            else:
                return {"error": "Invalid payload type. Must be JSON string or dict."}
            # Validate with PodcastInput
            payload = PodcastInput(**data)
        except Exception as e:
            return {"error": f"Invalid input: {e}"}

        loop = asyncio.get_event_loop()
        if loop.is_running():
            return loop.run_until_complete(self._generate_podcast(payload))
        else:
            return loop.run_until_complete(self._generate_podcast(payload))
