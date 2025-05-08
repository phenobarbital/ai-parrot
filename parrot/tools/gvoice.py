import asyncio
from pathlib import Path
from typing import Optional
import os
import re
from xml.sax.saxutils import escape
from datetime import datetime
import aiofiles
# Use v1 for wider feature set including SSML
from google.cloud import texttospeech_v1 as texttospeech
from google.oauth2 import service_account
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
from navconfig import BASE_DIR
from parrot.conf import GOOGLE_TTS_SERVICE

class PodcastInput(BaseModel):
    """Input for podcast generator tool."""
    text: str = Field(description="The text content to convert to speech")

class GoogleVoiceTool(BaseTool):
    """Generate a podcast-style audio file from Text using Google Cloud Text-to-Speech."""
    name: str = "generate_podcast_style_audio_file"
    description: str = (
        "Generates a podcast-style audio file from a given text script using Google Cloud Text-to-Speech."
        " Use this tool if the user requests a podcast, an audio summary, or a narrative of the findings "
        " First, ensure you have a clear and concise text summary of the information to be narrated. You might need to generate this summary based on your analysis or previous steps."
        " Provide the text *as-is* without enclosing on backticks or backquotes."
    )
    voice_model: str = "en-US-Neural2-F"  # "en-US-Studio-O"
    voice_gender: str = "FEMALE"
    language_code: str = "en-US"
    output_format: str = "OGG_OPUS"  # OGG format is more podcast-friendly
    _key_service: Optional[str]

    # Add a proper args_schema for tool-calling compatibility
    args_schema: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The text content to convert to speech"
            }
        },
        "required": ["query"]
    }

    def __init__(self,
        voice_model: str = "en-US-Neural2-F",
        output_format: str = "OGG_OPUS",
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
            default_path = BASE_DIR / "env" / "google" / "tts-service.json"
            if os.path.exists(default_path):
                self._key_service = str(default_path)
                print(f"Using default credentials path: {self._key_service}")
            else:
                print(f"Warning: No credentials found in config or at default path {default_path}")
        else:
            print(f"Using credentials from config: {self._key_service}")

        if self.voice_gender == 'FEMALE':
            self.voice_model = "en-US-Neural2-F"
        elif self.voice_gender == 'MALE':
            self.voice_model = "en-US-Neural2-M"
        else:
            self.voice_model = "en-US-Neural2-G"

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
                ssml += f'<p>{escape(line)}</p>'

        ssml += "</speak>"
        return ssml

    async def _generate_podcast(self, query: str) -> dict:
        """Main method to generate a podcast from query."""
        try:
            if self._key_service and Path(self._key_service).exists():
                try:
                    credentials = service_account.Credentials.from_service_account_file(
                        self._key_service
                    )
                except Exception as cred_error:
                    print(f"Error loading credentials: {cred_error}")

            if isinstance(query, str):
                try:
                    # Try to parse as JSON
                    import json
                    query_dict = json.loads(query)
                    if "output_file" in query_dict:
                        print(f"Output file specified in query: {query_dict['output_file']}")
                        print(f"Output directory exists: {os.path.isdir(os.path.dirname(query_dict['output_file']))}")
                except json.JSONDecodeError:
                    print("Query is plain text, not JSON")

            print("1. Converting Markdown to SSML...")
            if self.is_markdown(query):
                ssml_text = self.markdown_to_ssml(query)
            else:
                ssml_text = self.text_to_ssml(query)
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
            # Generate a unique filename based on the current timestamp
            output_filename = f"podcast_{timestamp}.ogg"  # Default output filename
            # default to OGG
            encoding = texttospeech.AudioEncoding.OGG_OPUS
            if self.output_format == "OGG_OPUS":
                encoding = texttospeech.AudioEncoding.OGG_OPUS
                output_filename = f"podcast_{timestamp}.ogg"
            elif self.output_format == "MP3":
                encoding = texttospeech.AudioEncoding.MP3
                output_filename = f"podcast_{timestamp}.mp3"
            elif self.output_format == "LINEAR16":
                encoding = texttospeech.AudioEncoding.LINEAR16
                output_filename = f"podcast_{timestamp}.wav"
            elif self.output_format == "WEBM_OPUS":
                encoding = texttospeech.AudioEncoding.WEBM_OPUS
                output_filename = f"podcast_{timestamp}.webm"
            elif self.output_format == "FLAC":
                encoding = texttospeech.AudioEncoding.FLAC
                output_filename = f"podcast_{timestamp}.flac"
            elif self.output_format == "OGG_VORBIS":
                encoding = texttospeech.AudioEncoding.OGG_VORBIS
                output_filename = f"podcast_{timestamp}.ogg"

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
            # Get the absolute path for the output file
            output_dir: Path = BASE_DIR.joinpath('static', 'audio', 'podcasts')
            if output_dir.exists() is False:
                # Create the directory if it doesn't exist
                output_dir.mkdir(parents=True, exist_ok=True)
            output_filepath = output_dir.joinpath(output_filename)
            print(f"5. Saving audio content to: {output_filepath}")
            async with aiofiles.open(output_filepath, 'wb') as audio_file:
                await audio_file.write(response.audio_content)
            print("6. Audio content saved successfully.")
            return {
                "file_path": output_filepath,
                "output_format": self.output_format,
                "language_code": self.language_code,
                "voice_model": self.voice_model,
                "timestamp": timestamp,
                "filename": output_filename
            }
        except Exception as e:
            import traceback
            print(f"Error in _generate_podcast: {e}")
            print(traceback.format_exc())
            return {"error": str(e)}

    async def _arun(self, query: str) -> dict:
        """
        Generates a podcast-style audio file from Markdown text using
        Google Cloud Text-to-Speech.

        Args:
            markdown_summary: The input text in Markdown format.
            output_filename: The desired name for the output audio file (e.g., "my_podcast.ogg").
            language_code: The language code (e.g., "en-US", "es-ES").
            voice_name: The specific voice model name. Find names here:
                        https://cloud.google.com/text-to-speech/docs/voices

        Returns:
            A dictionary containing the absolute path to the saved audio file
            under the key "file_path", or an error message under "error".
        """
        try:
            return await self._generate_podcast(query)
        except Exception as e:
            import traceback
            print(f"Error in GoogleVoiceTool._arun: {e}")
            print(traceback.format_exc())
            return {"error": str(e)}

    def _run(self, query: str) -> dict:
        """
        Synchronous method to generate a podcast-style audio file from Markdown text.
        This method is not recommended for production use due to blocking I/O.
        """
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If the event loop is already running, use run_until_complete
            return loop.run_until_complete(self._generate_podcast(query))
        else:
            # If not, use run
            return loop.run(self._generate_podcast(query))
