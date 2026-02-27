from typing import Any, AsyncIterator, List, Optional, Union
import sys
import logging
import asyncio
import contextlib
from datetime import datetime
from functools import partial
import time
import json
from pathlib import Path
import base64
import io
import uuid
import aiohttp
import aiofiles
from PIL import Image
from google.genai import types
from google.genai.types import (
    Part,
    ModelContent,
    UserContent
)
from navconfig import BASE_DIR
from ...models import (
    AIMessage,
    AIMessageFactory,
    CompletionUsage,
    ImageGenerationPrompt,
    SpeakerConfig,
    SpeechGenerationPrompt,
    VideoGenerationPrompt,
    VideoGenInput,
    VideoResolution,
)
from ...models.google import (
    GoogleModel,
    TTSVoice,
    MusicGenre,
    MusicMood,
    AspectRatio,
    ImageResolution,
    ConversationalScriptConfig,
    FictionalSpeaker,
    ALL_VOICE_PROFILES,
    VideoReelRequest,
    VideoReelScene
)
from ...exceptions import SpeechGenerationError  # pylint: disable=E0611
try:
    from moviepy import (
        VideoFileClip,
        AudioFileClip,
        CompositeAudioClip,
        concatenate_videoclips,
        vfx
    )
except ImportError:
    pass


class GoogleGeneration:
    """
    Mixin class for Google Generative AI generation capabilities (Image, Video, Audio).
    """
    logger: logging.Logger

    async def generate_images(
        self,
        prompt_data: ImageGenerationPrompt,
        model: Union[str, GoogleModel] = GoogleModel.IMAGEN_3,
        reference_image: Optional[Path] = None,
        output_directory: Optional[Path] = None,
        mime_format: str = "image/jpeg",
        number_of_images: int = 1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        add_watermark: bool = False
    ) -> AIMessage:
        """
        Generates images based on a text prompt using Imagen.
        """
        if prompt_data.model:
            model = GoogleModel.IMAGEN_3.value
        model = model.value if isinstance(model, GoogleModel) else model
        self.logger.info(
            f"Starting image generation with model: {model}"
        )
        if model == GoogleModel.GEMINI_2_0_IMAGE_GENERATION.value:
            image_provider = "google_genai"
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE']
            )
        else:
            image_provider = "google_imagen"

        full_prompt = prompt_data.prompt
        if prompt_data.styles:
            full_prompt += ", " + ", ".join(prompt_data.styles)

        if reference_image:
            self.logger.info(
                f"Using reference image: {reference_image}"
            )
            if not reference_image.exists():
                raise FileNotFoundError(
                    f"Reference image not found: {reference_image}"
                )
            # Load the reference image
            ref_image = Image.open(reference_image)
            full_prompt = [full_prompt, ref_image]

        config = types.GenerateImagesConfig(
            number_of_images=number_of_images,
            output_mime_type=mime_format,
            safety_filter_level="BLOCK_LOW_AND_ABOVE",
            person_generation="ALLOW_ADULT", # Or ALLOW_ALL, etc.
            aspect_ratio=prompt_data.aspect_ratio,
        )

        try:
            start_time = time.time()
            # Use the asynchronous client for image generation
            image_response = await self.client.aio.models.generate_images(
                model=prompt_data.model,
                prompt=full_prompt,
                config=config
            )
            execution_time = time.time() - start_time

            pil_images = []
            saved_image_paths = []
            raw_response = {}  # Initialize an empty dict for the raw response

            if image_response.generated_images:
                self.logger.info(
                    f"Successfully generated {len(image_response.generated_images)} image(s)."
                )
                raw_response['generated_images'] = []
                for _, generated_image in enumerate(image_response.generated_images):
                    pil_image = generated_image.image
                    pil_images.append(pil_image)

                    raw_response['generated_images'].append({
                        'uri': getattr(generated_image, 'uri', None),
                        'seed': getattr(generated_image, 'seed', None)
                    })

                    if output_directory:
                        file_path = self._save_image(pil_image, output_directory)
                        saved_image_paths.append(file_path)

            usage = CompletionUsage(execution_time=execution_time)
            # The primary 'output' is the list of raw PIL.Image objects
            # The new 'images' attribute holds the file paths
            ai_message = AIMessageFactory.from_imagen(
                output=pil_images,
                images=saved_image_paths,
                input=full_prompt,
                model=model,
                user_id=user_id,
                session_id=session_id,
                provider=image_provider,
                usage=usage,
                raw_response=raw_response
            )
            return ai_message

        except Exception as e:
            self.logger.error(f"Image generation failed: {e}")
            raise

    def _find_voice_for_speaker(self, speaker: FictionalSpeaker) -> str:
        """
        Find the best voice for a speaker based on their characteristics and gender.

        Args:
            speaker: The fictional speaker configuration

        Returns:
            Voice name string
        """
        if not self.voice_db:
            self.logger.warning(
                "Voice database not available, using default voice"
            )
            return "erinome"  # Default fallback

        try:
            # First, try to find voices by characteristic
            characteristic_voices = self.voice_db.get_voices_by_characteristic(
                speaker.characteristic
            )

            if characteristic_voices:
                # Filter by gender if possible
                gender_filtered = [
                    v for v in characteristic_voices if v.gender == speaker.gender
                ]
                if gender_filtered:
                    return gender_filtered[0].voice_name.lower()
                else:
                    # Use first voice with matching characteristic regardless of gender
                    return characteristic_voices[0].voice_name.lower()

            # Fallback: find by gender only
            gender_voices = self.voice_db.get_voices_by_gender(speaker.gender)
            if gender_voices:
                self.logger.info(
                    f"Found voice by gender '{speaker.gender}': {gender_voices[0].voice_name}"
                )
                return gender_voices[0].voice_name.lower()

            # Ultimate fallback
            self.logger.warning(
                f"No voice found for speaker {speaker.name}, using default"
            )
            return "erinome"

        except Exception as e:
            self.logger.error(
                f"Error finding voice for speaker {speaker.name}: {e}"
            )
            return "erinome"

    async def create_conversation_script(
        self,
        report_data: ConversationalScriptConfig,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        temperature: float = 0.7,
        use_structured_output: bool = False,
        max_lines: int = 20
    ) -> AIMessage:
        """
        Creates a conversation script using Google's Generative AI.
        Generates a fictional conversational script from a text report using a generative model.
        Generates a complete, TTS-ready prompt for a two-person conversation
        based on a source text report.

        This method is designed to create a script that can be used with Google's TTS system.

        Returns:
            A string formatted for Google's TTS `generate_content` method.
            Example:
            "Make Speaker1 sound tired and bored, and Speaker2 sound excited and happy:

            Speaker1: So... what's on the agenda today?
            Speaker2: You're never going to guess!"
        """
        model = model.value if isinstance(model, GoogleModel) else model
        self.logger.info(
            f"Starting Conversation Script with model: {model}"
        )
        turn_id = str(uuid.uuid4())

        report_text = report_data.report_text
        if not report_text:
            raise ValueError(
                "Report text is required for generating a conversation script."
            )
        # Calculate conversation length
        conversation_length = min(report_data.length // 50, max_lines)
        if conversation_length < 4:
            conversation_length = max_lines
        system_prompt = report_data.system_prompt or "Create a natural and engaging conversation script based on the provided report."
        context = report_data.context or "This conversation is based on a report about a specific topic. The characters will discuss the key findings and insights from the report."
        interviewer = None
        interviewee = None
        for speaker in report_data.speakers:
            if not speaker.name or not speaker.role or not speaker.characteristic:
                raise ValueError(
                    "Each speaker must have a name, role, and characteristic."
                )
            # role (interviewer or interviewee) and characteristic (e.g., friendly, professional)
            if speaker.role == "interviewer":
                interviewer = speaker
            elif speaker.role == "interviewee":
                interviewee = speaker

        if not interviewer or not interviewee:
            raise ValueError("Must have exactly one interviewer and one interviewee.")
        system_instruction = report_data.system_instruction or f"""
You are a scriptwriter. Your task is {system_prompt} for a conversation between {interviewer.name} and {interviewee.name}. "

**Source Report:**"
---
{report_text}
---

**context:**
{context}


**Characters:**
1.  **{interviewer.name}**: The {interviewer.role}. Their personality is **{interviewer.characteristic}**.
2.  **{interviewee.name}**: The {interviewee.role}. Their personality is **{interviewee.characteristic}**.

**Conversation Length:** {conversation_length} lines.
**Instructions:**
- The conversation must be based on the key findings, data, and conclusions of the source report.
- The interviewer should ask insightful questions to guide the conversation.
- The interviewee should provide answers and explanations derived from the report.
- The dialogue should reflect the specified personalities of the characters.
- The conversation should be engaging, natural, and suitable for a TTS system.
- The script should be formatted for TTS, with clear speaker lines.

**Gender–Neutral Output (Strict)**
- Do NOT infer anyone's gender or use third-person gendered pronouns or titles: he, him, his, she, her, hers, Mr., Mrs., Ms., sir, ma’am, etc.
- If a third person must be referenced, use singular they/them/their or repeat the name/role (e.g., “the manager”, “Alex”).
- Do not include gendered stage directions (“in a feminine/masculine voice”).
- First/second person is fine inside dialogue (“I”, “you”), but NEVER use gendered third-person forms.

Before finalizing, scan and fix any gendered terms. If any banned term appears, rewrite that line to comply.

- **IMPORTANT**: Generate ONLY the dialogue script. Do not include headers, titles, or any text other than the speaker lines. The format must be exactly:
{interviewer.name}: [dialogue]
{interviewee.name}: [dialogue]
        """
        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        # Build contents for the stateless API call
        contents = [{
            "role": "user",
            "parts": [{"text": report_text}]
        }]

        final_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
            ],
            tools=None,  # No tools needed for conversation script:
            **generation_config
        )

        # Make a stateless call to the model
        if not self.client:
            self.client = await self.get_client()

        sync_generate_content = partial(
            self.client.models.generate_content,
            model=model,
            contents=contents,
            config=final_config
        )
        # Run the synchronous function in a separate thread
        response = await asyncio.to_thread(sync_generate_content)
        # Extract the generated script text
        script_text = response.text if hasattr(response, 'text') else str(response)
        structured_output = script_text
        if use_structured_output:
            self.logger.info("Creating structured output for TTS system...")
            try:
                # Map speakers to voices
                speaker_configs = []
                for speaker in report_data.speakers:
                    voice = self._find_voice_for_speaker(speaker)
                    speaker_configs.append(
                        SpeakerConfig(name=speaker.name, voice=voice)
                    )
                    self.logger.notice(
                        f"Assigned voice '{voice}' to speaker '{speaker.name}'"
                    )
                structured_output = SpeechGenerationPrompt(
                    prompt=script_text,
                    speakers=speaker_configs
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to create structured output: {e}"
                )
                # Continue without structured output rather than failing

        # Create the AIMessage response using the factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=report_text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=structured_output,
            tool_calls=[]
        )
        ai_message.provider = "google_genai"

        return ai_message

    async def generate_speech(
        self,
        prompt_data: SpeechGenerationPrompt,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_TTS,
        output_directory: Optional[Path] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        mime_format: str = "audio/wav", # or "audio/mpeg", "audio/webm"
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> AIMessage:
        """
        Generates speech from text using either a single voice or multiple voices.
        """
        start_time = time.time()
        if prompt_data.model:
            model = prompt_data.model
        model = model.value if isinstance(model, GoogleModel) else model
        self.logger.info(
            f"Starting Speech generation with model: {model}"
        )

        # Validation of voices and fallback logic before creating the SpeechConfig:
        valid_voices = {v.value for v in TTSVoice}
        processed_speakers = []
        for speaker in prompt_data.speakers:
            final_voice = speaker.voice
            if speaker.voice not in valid_voices:
                self.logger.warning(
                    f"Invalid voice '{speaker.voice}' for speaker '{speaker.name}'. "
                    "Using default voice instead."
                )
                gender = speaker.gender.lower() if speaker.gender else 'female'
                final_voice = 'zephyr' if gender == 'female' else 'charon'
            processed_speakers.append(
                SpeakerConfig(name=speaker.name, voice=final_voice, gender=speaker.gender)
            )

        speech_config = None
        if len(processed_speakers) == 1:
            # Single-speaker configuration
            speaker = processed_speakers[0]
            gender = speaker.gender or 'female'
            default_voice = 'Charon' if gender == 'female' else 'Puck'
            voice = speaker.voice or default_voice
            self.logger.info(f"Using single voice: {voice}")
            speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                ),
                language_code=prompt_data.language or "en-US"  # Default to US English
            )
        else:
            # Multi-speaker configuration
            self.logger.info(
                f"Using multiple voices: {[s.voice for s in processed_speakers]}"
            )
            speaker_voice_configs = [
                types.SpeakerVoiceConfig(
                    speaker=s.name,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=s.voice
                        )
                    )
                ) for s in processed_speakers
            ]
            speech_config = types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=speaker_voice_configs
                ),
                language_code=prompt_data.language or "en-US"  # Default to US English
            )

        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
            system_instruction=system_prompt,
            temperature=temperature
        )
        # Retry logic for network errors
        if not self.client:
            self.client = await self.get_client()
        # chat = self.client.aio.chats.create(model=model, history=None, config=config)
        for attempt in range(max_retries + 1):

            try:
                if attempt > 0:
                    delay = retry_delay * (2 ** (attempt - 1))  # Exponential backoff
                    self.logger.info(
                        f"Retrying speech (attempt {attempt + 1}/{max_retries + 1}) after {delay}s delay..."
                    )
                    await asyncio.sleep(delay)

                sync_generate_content = partial(
                    self.client.models.generate_content,
                    model=model,
                    contents=prompt_data.prompt,
                    config=config
                )
                # Run the synchronous function in a separate thread
                response = await asyncio.to_thread(sync_generate_content)
                # Robust audio data extraction with proper validation
                audio_data = self._extract_audio_data(response)
                if audio_data is None:
                    # Log the response structure for debugging
                    self.logger.error(f"Failed to extract audio data from response")
                    self.logger.debug(f"Response type: {type(response)}")
                    if hasattr(response, 'candidates'):
                        self.logger.debug(f"Candidates count: {len(response.candidates) if response.candidates else 0}")
                        if response.candidates and len(response.candidates) > 0:
                            candidate = response.candidates[0]
                            self.logger.debug(f"Candidate type: {type(candidate)}")
                            self.logger.debug(f"Candidate has content: {hasattr(candidate, 'content')}")
                            if hasattr(candidate, 'content'):
                                content = candidate.content
                                self.logger.debug(f"Content is None: {content is None}")
                                if content:
                                    self.logger.debug(f"Content has parts: {hasattr(content, 'parts')}")
                                    if hasattr(content, 'parts'):
                                        self.logger.debug(f"Parts count: {len(content.parts) if content.parts else 0}")

                    raise SpeechGenerationError(
                        "No audio data found in response. The speech generation may have failed or "
                        "the model may not support speech generation for this request."
                    )

                saved_file_paths = []

                if output_directory:
                    output_directory.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    file_path = output_directory / f"generated_speech_{timestamp}.wav"

                    self._save_audio_file(audio_data, file_path, mime_format)
                    saved_file_paths.append(file_path)
                    self.logger.info(
                        f"Saved speech to {file_path}"
                    )

                execution_time = time.time() - start_time
                usage = CompletionUsage(
                    execution_time=execution_time,
                    # Speech API does not return token counts
                    input_tokens=len(prompt_data.prompt), # Approximation
                )

                ai_message = AIMessageFactory.from_speech(
                    output=audio_data,  # The raw PCM audio data
                    files=saved_file_paths,
                    input=prompt_data.prompt,
                    model=model,
                    provider="google_genai",
                    usage=usage,
                    user_id=user_id,
                    session_id=session_id,
                    raw_response=None  # Response object isn't easily serializable
                )
                return ai_message

            except (
                aiohttp.ClientPayloadError,
                aiohttp.ClientConnectionError,
                aiohttp.ClientResponseError,
                aiohttp.ServerTimeoutError,
                ConnectionResetError,
                TimeoutError,
                asyncio.TimeoutError
            ) as network_error:
                error_msg = str(network_error)

                # Specific handling for differnet network errors
                if "TransferEncodingError" in error_msg:
                    self.logger.warning(
                        f"Transfer encoding error on attempt {attempt + 1}: {error_msg}")
                elif "Connection reset by peer" in error_msg:
                    self.logger.warning(
                        f"Connection reset on attempt {attempt + 1}: Server closed connection")
                elif "timeout" in error_msg.lower():
                    self.logger.warning(
                        f"Timeout error on attempt {attempt + 1}: {error_msg}")
                else:
                    self.logger.warning(
                        f"Network error on attempt {attempt + 1}: {error_msg}"
                    )

                if attempt < max_retries:
                    self.logger.debug(
                        f"Will retry in {retry_delay * (2 ** attempt)}s..."
                    )
                    continue
                else:
                    # Max retries exceeded
                    self.logger.error(
                        f"Speech generation failed after {max_retries + 1} attempts"
                    )
                    raise SpeechGenerationError(
                        f"Speech generation failed after {max_retries + 1} attempts. "
                        f"Last error: {error_msg}. This is typically a temporary network issue - please try again."
                    ) from network_error

            except Exception as e:
                # Non-network errors - don't retry
                error_msg = str(e)
                self.logger.error(
                    f"Speech generation failed with non-retryable error: {error_msg}"
                )

                # Provide helpful error messages based on error type
                if "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                    raise SpeechGenerationError(
                        f"API quota or rate limit exceeded: {error_msg}. Please try again later."
                    ) from e
                elif "permission" in error_msg.lower() or "unauthorized" in error_msg.lower():
                    raise SpeechGenerationError(
                        f"Authorization error: {error_msg}. Please check your API credentials."
                    ) from e
                elif "model" in error_msg.lower():
                    raise SpeechGenerationError(
                        f"Model error: {error_msg}. The model '{model}' may not support speech generation."
                    ) from e
                else:
                    raise SpeechGenerationError(
                        f"Speech generation failed: {error_msg}"
                    ) from e

    def _extract_audio_data(self, response):
        """
        Robustly extract audio data from Google GenAI response.
        Similar to the text extraction pattern used elsewhere in the codebase.
        """
        try:
            # First attempt: Direct access to expected structure
            if (hasattr(response, 'candidates') and
                response.candidates and
                len(response.candidates) > 0 and
                hasattr(response.candidates[0], 'content') and
                response.candidates[0].content and
                hasattr(response.candidates[0].content, 'parts') and
                response.candidates[0].content.parts and
                len(response.candidates[0].content.parts) > 0):

                for part in response.candidates[0].content.parts:
                    # Check for inline_data with audio data
                    if (hasattr(part, 'inline_data') and
                        part.inline_data and
                        hasattr(part.inline_data, 'data') and
                        part.inline_data.data):
                        self.logger.debug("Found audio data in inline_data.data")
                        return part.inline_data.data

                    # Alternative: Check for direct data attribute
                    if hasattr(part, 'data') and part.data:
                        self.logger.debug("Found audio data in part.data")
                        return part.data

                    # Alternative: Check for binary data
                    if hasattr(part, 'binary') and part.binary:
                        self.logger.debug("Found audio data in part.binary")
                        return part.binary

            self.logger.warning("No audio data found in expected response structure")
            return None

        except Exception as e:
            self.logger.error(f"Audio data extraction failed: {e}")
            return None

    async def create_speech(
        self,
        prompt: str,
        voice: Union[str, SpeakerConfig] = "Puck",
        output_path: Optional[Union[str, Path]] = None,
        generate_script: bool = True,
        speaker_count: int = 1,
        language: str = "en-US",
        prompt_instruction: Optional[str] = None,
    ) -> AIMessage:
        """
        Generates speech from text, optionally creating a script first.

        Args:
            prompt: Text to speak or topic for script generation.
            voice: Voice name or SpeakerConfig for single-speaker TTS.
            output_path: Directory or file path to save audio.
            generate_script: If True, uses LLM to generate a conversational
                script from the prompt before synthesizing.
            speaker_count: Number of speakers (1 or 2) for script generation.
            language: BCP-47 language code (e.g. 'en-US').
            prompt_instruction: Optional system prompt passed to the script
                generator to guide tone/style.

        Returns:
            AIMessage with audio data and optional saved file path.
        """
        # 1. Resolve the voice name string for later use.
        voice_name: str = voice.voice if isinstance(voice, SpeakerConfig) else str(voice)

        # Look up additional metadata from the voice registry (best-effort).
        voice_profile = next(
            (p for p in ALL_VOICE_PROFILES if p.voice_name.lower() == voice_name.lower()),
            None,
        )
        voice_gender: str = voice_profile.gender if voice_profile else "neutral"

        # 2. Generate Script (if requested).
        if generate_script:
            self.logger.info(f"Generating conversation script for: {prompt}")

            # Build the required FictionalSpeaker list.
            if speaker_count >= 2:
                speakers = [
                    FictionalSpeaker(
                        name="Alex",
                        characteristic="curious and engaging",
                        role="interviewer",
                        gender="neutral",
                    ),
                    FictionalSpeaker(
                        name="Jordan",
                        characteristic="knowledgeable and clear",
                        role="interviewee",
                        gender="neutral",
                    ),
                ]
            else:
                # Single-speaker: still needs two speakers for the script model,
                # but we will only synthesise the first speaker's lines.
                speakers = [
                    FictionalSpeaker(
                        name="Narrator",
                        characteristic="clear and informative",
                        role="interviewer",
                        gender=voice_gender,
                    ),
                    FictionalSpeaker(
                        name="Guest",
                        characteristic="thoughtful",
                        role="interviewee",
                        gender="neutral",
                    ),
                ]

            script_config = ConversationalScriptConfig(
                report_text=prompt,
                speakers=speakers,
                context=f"A spoken presentation about: {prompt}",
                system_prompt=prompt_instruction,
            )

            script_response = await self.create_conversation_script(
                report_data=script_config,
            )
            text_to_speak = script_response.response
            self.logger.info(f"Script generated ({len(text_to_speak)} chars)")
        else:
            text_to_speak = prompt

        # 3. Build SpeechGenerationPrompt for generate_speech.
        #    Single voice TTS: wrap voice in a one-element speakers list.
        speaker_cfg = SpeakerConfig(name="Speaker", voice=voice_name)
        prompt_data = SpeechGenerationPrompt(
            prompt=text_to_speak,
            speakers=[speaker_cfg],
            language=language,
        )

        # Resolve output_directory from output_path.
        output_directory: Optional[Path] = None
        if output_path is not None:
            p = Path(output_path)
            output_directory = p if p.is_dir() else p.parent

        self.logger.info(f"Synthesising speech with voice: {voice_name}")

        try:
            return await self.generate_speech(
                prompt_data=prompt_data,
                output_directory=output_directory,
            )
        except Exception as e:
            self.logger.error(f"Speech creation failed: {e}")
            raise SpeechGenerationError(f"Failed to create speech: {e}") from e

    async def video_generation(
        self,
        prompt: Union[str, VideoGenInput],
        output_directory: Optional[Union[str, Path]] = None,
        model: Union[str, GoogleModel] = GoogleModel.VEO_3_1,
        aspect_ratio: Union[str, AspectRatio] = AspectRatio.RATIO_16_9,
        negative_prompt: Optional[str] = None,
        number_of_videos: int = 1,
        reference_image: Optional[Union[str, Path, Image.Image]] = None,
        generate_image_first: bool = False,
        image_prompt: Optional[str] = None,
        duration: int = 8,
        resolution: Optional[str] = None,
        person_generation: str = "allow_adult",
        include_audio: bool = True,
        last_frame: Optional[Union[str, Path, Image.Image]] = None,
        reference_images: Optional[List[Union[str, Path, Image.Image]]] = None,
        reference_type: str = "asset",
        extend_video: Optional[Any] = None,
        seed: Optional[int] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Generates videos using Google's Veo models.

        Accepts either a plain ``str`` prompt or a fully-specified
        :class:`~parrot.models.VideoGenInput` object.  Individual kwargs always
        take precedence over fields inside ``VideoGenInput``.

        Supports:
        - Text-to-video (all models)
        - Image-to-video / image animation (all models)
        - First-and-last-frame interpolation (VEO 3.1 only)
        - Reference image guidance — up to 3 images (VEO 3.1 only)
        - Video extension (VEO 3.1 only)
        - Resolution control: 720p / 1080p / 4k (VEO 3.1 only)
        - Audio stripping via moviepy when ``include_audio=False``

        Duration rules:
        - VEO 3.1: 4s / 6s / 8s (default 8)
        - VEO 2.0: 5s / 6s / 8s
        - Must be 8s when using 1080p/4k resolution, reference images, or extension.
        """
        # --- Unpack VideoGenInput when given as structured input -----------------
        if isinstance(prompt, VideoGenInput):
            vin = prompt
            prompt_text = vin.prompt
            # kwargs supplied explicitly override VideoGenInput fields
            negative_prompt = negative_prompt if negative_prompt is not None else vin.negative_prompt
            duration = duration if duration != 8 else vin.duration
            aspect_ratio = aspect_ratio if aspect_ratio != AspectRatio.RATIO_16_9 else vin.aspect_ratio
            resolution = resolution if resolution is not None else vin.resolution
            person_generation = person_generation if person_generation != "allow_adult" else vin.person_generation
            include_audio = include_audio if not include_audio else vin.include_audio
            number_of_videos = number_of_videos if number_of_videos != 1 else vin.number_of_videos
            seed = seed if seed is not None else vin.seed
            reference_type = reference_type if reference_type != "asset" else vin.reference_type
            extend_video = extend_video if extend_video is not None else vin.extend_video
            if not generate_image_first:
                generate_image_first = vin.generate_image_first
            if image_prompt is None:
                image_prompt = vin.image_prompt
            # Image paths from VideoGenInput (only when not already given as kwargs)
            if reference_image is None and vin.image_path:
                reference_image = Path(vin.image_path)
            if last_frame is None and vin.last_frame_path:
                last_frame = Path(vin.last_frame_path)
            if reference_images is None and vin.reference_image_paths:
                reference_images = [Path(p) for p in vin.reference_image_paths]
        else:
            prompt_text = prompt

        # --- Model resolution ---------------------------------------------------
        model_str = model.value if isinstance(model, GoogleModel) else model

        _veo31_models = {GoogleModel.VEO_3_1.value, GoogleModel.VEO_3_1_FAST.value}
        is_veo31 = model_str in _veo31_models

        if not any(m in model_str for m in ["veo", "video"]):
            self.logger.warning(f"Model {model_str!r} may not be a video generation model.")

        # --- Output directory ---------------------------------------------------
        if output_directory:
            out_dir = Path(output_directory)
            out_dir.mkdir(parents=True, exist_ok=True)
        else:
            out_dir = BASE_DIR.joinpath('static', 'generated_videos')
            out_dir.mkdir(parents=True, exist_ok=True)

        # --- Aspect ratio normalisation ----------------------------------------
        ar_str = aspect_ratio.value if isinstance(aspect_ratio, AspectRatio) else str(aspect_ratio)
        # VEO models only support 16:9 and 9:16
        if ar_str not in ("16:9", "9:16"):
            self.logger.warning(
                f"Unsupported aspect ratio {ar_str!r} for VEO models; falling back to '16:9'."
            )
            ar_str = "16:9"

        # --- Reference image (starting frame) ----------------------------------
        ref_img_pil: Optional[Image.Image] = None
        if generate_image_first:
            self.logger.info("Generating reference image for video...")
            img_response = await self.generate_image(
                prompt=image_prompt or prompt_text,
                aspect_ratio=ar_str,
                output_directory=str(out_dir)
            )
            if img_response.images:
                ref_img_pil = Image.open(img_response.images[0])
                self.logger.info(f"Generated reference image: {img_response.images[0]}")
            else:
                self.logger.warning("Failed to generate reference image, proceeding without it.")
        elif reference_image:
            ref_img_pil = self._load_image(reference_image)

        def _pil_to_types_image(img: Image.Image) -> types.Image:
            """Convert PIL Image to ``types.Image`` (JPEG bytes)."""
            buf = io.BytesIO()
            converted = img.convert("RGB") if img.mode in ("RGBA", "P") else img
            converted.save(buf, format="JPEG")
            return types.Image(image_bytes=buf.getvalue(), mime_type="image/jpeg")

        # --- Build GenerateVideosConfig ----------------------------------------
        config_kwargs: dict = {
            "aspect_ratio": ar_str,
            "negative_prompt": negative_prompt,
            "number_of_videos": number_of_videos,
            "person_generation": person_generation,
            "duration_seconds": duration,
        }

        # Resolution — VEO 3.1 only
        if resolution is not None:
            if is_veo31:
                res_str = resolution.value if isinstance(resolution, VideoResolution) else resolution
                # Force duration=8 for 1080p/4k
                if res_str in ("1080p", "4k") and duration != 8:
                    self.logger.warning(
                        f"Resolution {res_str!r} requires duration=8; overriding duration."
                    )
                    config_kwargs["duration_seconds"] = 8
                config_kwargs["resolution"] = res_str
            else:
                self.logger.warning(
                    f"Resolution parameter is not supported by model {model_str!r}; ignoring."
                )

        # Seed — VEO 3.x only
        if seed is not None and is_veo31:
            config_kwargs["seed"] = seed

        # Last frame (interpolation) — VEO 3.1 only
        if last_frame is not None:
            if is_veo31:
                config_kwargs["last_frame"] = _pil_to_types_image(self._load_image(last_frame))
            else:
                self.logger.warning(
                    "last_frame is only supported on VEO 3.1 models; ignoring."
                )

        # Reference images — VEO 3.1 only (requires duration=8)
        ref_image_objects: Optional[List] = None
        if reference_images:
            if is_veo31:
                if len(reference_images) > 3:
                    self.logger.warning("Only up to 3 reference images supported; using first 3.")
                    reference_images = reference_images[:3]
                ref_image_objects = [
                    types.VideoGenerationReferenceImage(
                        image=_pil_to_types_image(self._load_image(img)),
                        reference_type=reference_type,
                    )
                    for img in reference_images
                ]
                # Reference images require duration=8
                config_kwargs["duration_seconds"] = 8
            else:
                self.logger.warning(
                    "reference_images are only supported on VEO 3.1 models; ignoring."
                )

        if ref_image_objects:
            config_kwargs["reference_images"] = ref_image_objects

        config = types.GenerateVideosConfig(**config_kwargs)

        # --- Build generate_videos kwargs --------------------------------------
        gen_kwargs: dict = {
            "model": model_str,
            "prompt": prompt_text,
            "config": config,
        }

        # Starting frame (image-to-video)
        if ref_img_pil is not None:
            gen_kwargs["image"] = _pil_to_types_image(ref_img_pil)

        # Video extension — VEO 3.1 only
        if extend_video is not None:
            if is_veo31:
                gen_kwargs["video"] = extend_video
                # Extension requires 720p
                if resolution and resolution not in ("720p", VideoResolution.RES_720P):
                    self.logger.warning(
                        "Video extension only supports 720p resolution; overriding."
                    )
                    config_kwargs["resolution"] = "720p"
                    config_kwargs["duration_seconds"] = 8
                    gen_kwargs["config"] = types.GenerateVideosConfig(**config_kwargs)
            else:
                self.logger.warning(
                    "Video extension is only supported on VEO 3.1 models; ignoring."
                )

        self.logger.info(
            f"Starting video generation: model={model_str!r}, duration={duration}s, "
            f"resolution={resolution or 'default'}, aspect={ar_str}, audio={include_audio}"
        )

        try:
            client = await self.get_client()

            # LRO — start operation
            operation = await client.aio.models.generate_videos(**gen_kwargs)
            self.logger.info(f"Video generation started: operation={operation.name!r}")

            # Poll
            poll_interval = 10
            while not operation.done:
                self.logger.debug("Waiting for video generation...")
                await asyncio.sleep(poll_interval)
                operation = await client.aio.operations.get(operation)

            if operation.error:
                raise RuntimeError(f"Video generation failed: {operation.error}")

            # Download and save
            generated_paths: List[Path] = []
            for i, vid in enumerate(operation.response.generated_videos):
                video_bytes = await client.aio.files.download(file=vid.video)
                saved_path = await self._async_save_video_file(video_bytes, out_dir, i)

                # Strip audio if requested
                if not include_audio:
                    saved_path = await self._strip_audio(saved_path)

                generated_paths.append(saved_path)

            return AIMessageFactory.from_video(
                output=operation.response,
                files=generated_paths,
                input=prompt_text,
                model=model_str,
                provider="google_genai",
                usage=CompletionUsage(),
                user_id=user_id,
                session_id=session_id,
            )

        except Exception as e:
            self.logger.error(f"Video generation failed: {e}")
            raise

    async def _async_save_video_file(
        self,
        video_bytes: bytes,
        output_directory: Path,
        video_number: int = 0,
        mime_format: str = "video/mp4"
    ) -> Path:
        """Helper to save video bytes efficiently."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"video_{timestamp}_{video_number}.mp4"
        video_path = output_directory / filename

        async with aiofiles.open(video_path, 'wb') as f:
            await f.write(video_bytes)

        self.logger.info(f"Saved video to {video_path}")
        return video_path

    async def _strip_audio(self, video_path: Path) -> Path:
        """Remove the audio track from a video file using moviepy.

        Returns the path to the muted video (overwrites the original file in-place).
        Skips silently if moviepy is not installed.
        """
        try:
            VideoFileClip  # noqa: F821 — imported at top, may be absent
        except NameError:
            self.logger.warning("moviepy not available; could not strip audio from video.")
            return video_path

        def _do_strip(src: Path) -> None:
            clip = VideoFileClip(str(src))
            muted = clip.without_audio()
            tmp = src.with_suffix(".muted.mp4")
            muted.write_videofile(str(tmp), logger=None)
            clip.close()
            muted.close()
            tmp.replace(src)  # atomic rename

        await asyncio.get_running_loop().run_in_executor(None, _do_strip, video_path)
        self.logger.info(f"Stripped audio from {video_path}")
        return video_path

    async def generate_music(
        self,
        prompt: str,
        genre: Optional[Union[str, MusicGenre]] = None,
        mood: Optional[Union[str, MusicMood]] = None,
        bpm: int = 90,
        temperature: float = 1.0,
        density: float = 0.5,
        brightness: float = 0.5,
        timeout: int = 300
    ) -> AsyncIterator[bytes]:
        """
        Generates music using the Lyria model.

        Args:
            prompt: Text description of the music.
            genre: Music genre (see MusicGenre enum).
            mood: Mood description (see MusicMood enum).
            bpm: Beats per minute (60-200)  .
            temperature: Creativity (0.0-3.0).
            density: Note density (0.0-1.0).
            brightness: Tonal brightness (0.0-1.0).
            timeout: Max duration in seconds to keep the connection open.

        Yields:
            Audio chunks (bytes).
        """
        # Lyria RealTime requires the v1alpha API version.
        music_client = await self.get_client(http_options={'api_version': 'v1alpha'})

        # Build prompts
        prompts = [types.WeightedPrompt(text=prompt, weight=1.0)]
        if genre:
            prompts.append(types.WeightedPrompt(text=f"Genre: {genre}", weight=0.8))
        if mood:
            prompts.append(types.WeightedPrompt(text=f"Mood: {mood}", weight=0.8))

        # Config
        config = types.LiveMusicGenerationConfig(
            bpm=bpm,
            temperature=temperature,
            density=density,
            brightness=brightness
        )

        try:
            async with music_client.aio.live.music.connect(model='models/lyria-realtime-exp') as session:
                # Queue to communicate between background receiver and main yielder
                queue = asyncio.Queue()

                async def receive_audio():
                    """Background task to receive audio from session."""
                    msg_count = 0
                    chunk_count = 0
                    try:
                        async for message in session.receive():
                            msg_count += 1
                            if msg_count <= 3:
                                # Log structure of first few messages for debugging
                                self.logger.debug(
                                    f"Lyria msg #{msg_count}: type={type(message).__name__}, "
                                    f"attrs={[a for a in dir(message) if not a.startswith('_')]}"
                                )
                                if hasattr(message, 'server_content'):
                                    sc = message.server_content
                                    if sc:
                                        self.logger.debug(
                                            f"  server_content attrs={[a for a in dir(sc) if not a.startswith('_')]}"
                                        )
                                        if hasattr(sc, 'audio_chunks') and sc.audio_chunks:
                                            self.logger.debug(
                                                f"  audio_chunks count={len(sc.audio_chunks)}, "
                                                f"first chunk attrs={[a for a in dir(sc.audio_chunks[0]) if not a.startswith('_')]}"
                                            )
                                    else:
                                        self.logger.debug("  server_content is None/empty")
                            if message.server_content and message.server_content.audio_chunks:
                                for chunk in message.server_content.audio_chunks:
                                    if chunk.data:
                                        chunk_count += 1
                                        await queue.put(chunk.data)
                            await asyncio.sleep(0.001)  # Yield control
                    except Exception as e:
                        self.logger.error(f"Error receiving music audio: {e}")
                    finally:
                        self.logger.info(
                            f"Lyria receive_audio done: {msg_count} messages, {chunk_count} chunks extracted"
                        )
                        await queue.put(None)  # Signal end

                receiver_task = asyncio.create_task(receive_audio())

                try:
                    # Send config and prompts
                    await session.set_weighted_prompts(prompts=prompts)
                    await session.set_music_generation_config(config=config)
                    self.logger.info("Lyria: prompts and config sent, starting playback...")

                    # Start playback
                    await session.play()
                    self.logger.info("Lyria: playback started, waiting for audio chunks...")

                    # Yield audio chunks
                    start_time = time.time()
                    chunks_received = 0
                    while True:
                        elapsed = time.time() - start_time
                        if elapsed > timeout:
                            self.logger.info(
                                f"Music generation complete: {elapsed:.1f}s "
                                f"({chunks_received} chunks, ~{chunks_received * 2}s audio)"
                            )
                            break

                        try:
                            chunk = await asyncio.wait_for(queue.get(), timeout=5.0)
                        except asyncio.TimeoutError:
                            # No chunk in 5s — loop back to check wall-clock timeout
                            continue

                        if chunk is None:
                            self.logger.info(
                                f"Lyria: stream ended after {chunks_received} chunks"
                            )
                            break
                        chunks_received += 1
                        yield chunk
                finally:
                    receiver_task.cancel()
                    try:
                        await receiver_task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            self.logger.error(f"Music generation failed: {e}")
            raise

    def _load_image(self, image: Union[str, Path, Image.Image]) -> Image.Image:
        """Helper to load image from path or return PIL Image."""
        if isinstance(image, Image.Image):
            return image
        if isinstance(image, (str, Path)):
            path = Path(image).expanduser()
            if path.exists():
                return Image.open(path)
            # handle URL if needed later
        raise ValueError(f"Invalid image input: {image}")

    async def generate_image(
        self,
        prompt: str,
        reference_images: Optional[List[Union[str, Path, Image.Image]]] = None,
        google_search: bool = False,
        aspect_ratio: Union[str, AspectRatio] = AspectRatio.RATIO_16_9,
        resolution: Union[str, ImageResolution] = ImageResolution.RES_2K,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_PRO_IMAGE_PREVIEW,
        output_directory: Optional[str] = None,
        as_base64: bool = False
    ) -> AIMessage:
        """
        Generate images using Google's Gemini/Imagen models.

        Args:
            prompt: Text prompt for image generation.
            reference_images: List of reference images (path or PIL.Image).
            google_search: Whether to use Google Search for grounding (if supported).
            aspect_ratio: Aspect ratio for the generated image.
            resolution: Desired resolution (e.g., '1K', '2K').
            model: Model to use (default: gemini-3-pro-image-preview).
            output_directory: Directory to save generated images.
            as_base64: Whether to include base64 encoded string in the response.

        Returns:
            AIMessage containing the generated image(s).
        """
        client = await self.get_client()

        # 1. Prepare Content
        contents = [prompt]
        if reference_images:
            for img in reference_images:
                try:
                    loaded_img = self._load_image(img)
                    contents.append(loaded_img)
                except Exception as e:
                    self.logger.warning(f"Failed to load reference image {img}: {e}")

        # 2. Prepare Config
        tools = []
        if google_search:
            tools.append({"google_search": {}})

        if isinstance(model, GoogleModel):
            model = model.value

        image_size = resolution.value if isinstance(resolution, ImageResolution) else resolution

        config = types.GenerateContentConfig(
            response_modalities=['TEXT', 'IMAGE'], # Request both for potential text explanation
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
                image_size=image_size
            ),
            tools=tools
        )

        try:
            # 3. Call API
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )

            # 4. Process Response
            generated_images = []
            image_paths = []
            base64_images = []
            text_output = ""

            if output_directory:
                out_dir = Path(output_directory)
                out_dir.mkdir(parents=True, exist_ok=True)

            if response.parts:
                for part in response.parts:
                    if part.text:
                        text_output += part.text + "\n"

                    # Handle Image Part
                    img = None
                    # Check as_image() method which is standard in Google GenAI SDK v0.1+
                    if hasattr(part, 'as_image'):
                        try:
                            img = part.as_image()
                        except Exception:
                            pass
                    elif hasattr(part, 'image'):
                        # Direct image attribute?
                        pass

                    if img:
                        generated_images.append(img)
                        if output_directory:
                            filename = f"gen_{uuid.uuid4().hex[:8]}.png"
                            save_path = out_dir / filename
                            # Use run_in_executor for blocking I/O
                            await asyncio.get_running_loop().run_in_executor(
                                None, img.save, save_path
                            )
                            image_paths.append(str(save_path))

                        if as_base64:
                            buffered = io.BytesIO()
                            if isinstance(img, Image.Image):
                                img.save(buffered, format="PNG")
                            else:
                                # Attempt to save without format argument if it's a custom wrapper
                                # or handle accordingly (e.g. wrapper might not support BytesIO)
                                try:
                                    # If it's the Google wrapper, it might support save(fp) but maybe not format kwarg
                                    img.save(buffered)
                                except Exception:
                                    # Try to convert if it has bytes
                                    if hasattr(img, 'image_bytes'):
                                        buffered.write(img.image_bytes)
                                    elif hasattr(img, 'data'): # Some older or other types
                                        buffered.write(img.data)
                                    else:
                                        self.logger.warning(f"Could not extract bytes from image object type: {type(img)}")

                            if buffered.tell() > 0:
                                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                                base64_images.append(img_str)

            # Construct AIMessage
            # If no text, use a default message
            if not text_output.strip():
                text_output = "Image generated successfully."

            raw_output = generated_images[0] if generated_images else None

            # Construct AIMessage
            message = AIMessage(
                input=prompt,
                output=raw_output,  # Raw output (PIL Image)
                response=text_output,
                model=model,
                provider="google",
                usage=CompletionUsage(total_tokens=0), # Placeholder
                images=[Path(p) for p in image_paths],
                data={"base64_images": base64_images} if base64_images else None
            )
            return message

        except Exception as e:
            self.logger.error(f"Image generation failed: {e}")
            raise

    async def _await_with_progress(
        self,
        coro,
        *,
        label: str,
        timeout: Optional[int],
        log_interval: int = 10,
    ):
        """Await a coroutine while periodically logging progress."""
        if log_interval <= 0:
            log_interval = 10
        task = asyncio.create_task(coro)
        start = time.monotonic()
        try:
            while True:
                if timeout is None:
                    done, _ = await asyncio.wait({task}, timeout=log_interval)
                else:
                    elapsed = time.monotonic() - start
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    done, _ = await asyncio.wait({task}, timeout=min(log_interval, remaining))
                if task in done:
                    return await task
                elapsed = time.monotonic() - start
                self.logger.debug(f"{label} still running... {elapsed:.1f}s elapsed")
        except asyncio.TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise

    async def image_generation(
        self,
        prompt_data: Union[str, ImageGenerationPrompt],
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_IMAGE_PREVIEW,
        temperature: Optional[float] = None,
        prompt_instruction: Optional[str] = None,
        reference_images: List[Union[Optional[Path], Image.Image]] = None,
        output_directory: Optional[Path] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        stateless: bool = True
    ) -> AIMessage:
        """
        Generates images based on a text prompt using Nano-Banana.
        """
        if isinstance(prompt_data, str):
            prompt_data = ImageGenerationPrompt(
                prompt=prompt_data,
                model=model,
            )
        if prompt_data.model:
            model = GoogleModel.GEMINI_2_5_FLASH_IMAGE_PREVIEW.value
        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())
        prompt_data.model = model

        self.logger.info(
            f"Starting image generation with model: {model}"
        )

        messages, conversation_session, _ = await self._prepare_conversation_context(
            prompt_data.prompt, None, user_id, session_id, None
        )

        full_prompt = prompt_data.prompt
        if prompt_data.styles:
            full_prompt += ", " + ", ".join(prompt_data.styles)

        # Prepare conversation history for Google GenAI format
        history = []
        if messages:
            for msg in messages[:-1]: # Exclude the current user message (last in list)
                role = msg['role'].lower()
                if role == 'user':
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                    if parts:
                        history.append(UserContent(parts=parts))
                elif role in ['assistant', 'model']:
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                    if parts:
                        history.append(ModelContent(parts=parts))

        ref_images = []
        if reference_images:
            self.logger.info(
                f"Using reference image: {reference_images}"
            )
            for img_path in reference_images:
                if not img_path.exists():
                    raise FileNotFoundError(
                        f"Reference image not found: {img_path}"
                    )
                # Load the reference image
                ref_images.append(Image.open(img_path))

        config=types.GenerateContentConfig(
            response_modalities=['Text', 'Image'],
            temperature=temperature or self.temperature,
            system_instruction=prompt_instruction
        )

        try:
            start_time = time.time()
            content = [full_prompt, *ref_images] if ref_images else [full_prompt]
            # Use the asynchronous client for image generation
            if stateless:
                response = await self.client.aio.models.generate_content(
                    model=prompt_data.model,
                    contents=content,
                    config=config
                )
            else:
                # Create the stateful chat session
                chat = self.client.aio.chats.create(model=model, history=history, config=config)
                response = await chat.send_message(
                    message=content,
                )
            execution_time = time.time() - start_time

            pil_images = []
            saved_image_paths = []
            raw_response = {}  # Initialize an empty dict for the raw response

            raw_response['generated_images'] = []
            for part in response.candidates[0].content.parts:
                if part.text is not None:
                    raw_response['text'] = part.text
                elif part.inline_data is not None:
                    image = Image.open(io.BytesIO(part.inline_data.data))
                    pil_images.append(image)
                    if output_directory:
                        if isinstance(output_directory, str):
                            output_directory = Path(output_directory).resolve()
                        file_path = self._save_image(image, output_directory)
                        saved_image_paths.append(file_path)
                        raw_response['generated_images'].append({
                            'uri': file_path,
                            'seed': None
                        })

            usage = CompletionUsage(execution_time=execution_time)
            if not stateless:
                await self._update_conversation_memory(
                    user_id,
                    session_id,
                    conversation_session,
                    messages + [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"[Image Analysis]: {full_prompt}"}
                            ]
                        },
                    ],
                    None,
                    turn_id,
                    prompt_data.prompt,
                    response.text,
                    []
                )
            ai_message = AIMessageFactory.from_imagen(
                output=pil_images,
                images=saved_image_paths,
                input=full_prompt,
                model=model,
                user_id=user_id,
                session_id=session_id,
                provider='nano-banana',
                usage=usage,
                raw_response=raw_response
            )
            return ai_message

        except Exception as e:
            self.logger.error(f"Image generation failed: {e}")
            raise

    async def generate_videos(
        self,
        prompt: Union[str, VideoGenerationPrompt],
        reference_image: Optional[Path] = None,
        output_directory: Optional[Path] = None,
        mime_format: str = "video/mp4",
        model: Union[str, GoogleModel] = GoogleModel.VEO_3_1,
    ) -> AIMessage:
        """
        Generate a video using the specified model and prompt (handler-facing method).

        Delegates to :meth:`video_generation` for the actual generation logic.
        Accepts a :class:`~parrot.models.VideoGenerationPrompt` for structured input.
        """
        if isinstance(prompt, VideoGenerationPrompt) and prompt.model:
            model = prompt.model
        model_str = model.value if isinstance(model, GoogleModel) else model

        _valid_models = {
            GoogleModel.VEO_3_1.value,
            GoogleModel.VEO_3_1_FAST.value,
            GoogleModel.VEO_2_0.value,
        }
        if model_str not in _valid_models:
            raise ValueError(
                f"generate_videos: unsupported model {model_str!r}. "
                f"Valid models: {sorted(_valid_models)}"
            )

        prompt_text = prompt.prompt if isinstance(prompt, VideoGenerationPrompt) else prompt
        aspect_ratio = prompt.aspect_ratio if isinstance(prompt, VideoGenerationPrompt) else "16:9"
        negative_prompt = (
            prompt.negative_prompt if isinstance(prompt, VideoGenerationPrompt) else None
        )
        resolution = prompt.resolution if isinstance(prompt, VideoGenerationPrompt) else None
        duration = prompt.duration if isinstance(prompt, VideoGenerationPrompt) else 8
        seed = prompt.seed if isinstance(prompt, VideoGenerationPrompt) else None
        include_audio = (
            prompt.include_audio if isinstance(prompt, VideoGenerationPrompt) else True
        )

        return await self.video_generation(
            prompt=prompt_text,
            model=model_str,
            output_directory=output_directory,
            reference_image=reference_image,
            aspect_ratio=aspect_ratio,
            negative_prompt=negative_prompt or None,
            resolution=resolution,
            duration=duration or 8,
            seed=seed,
            include_audio=include_audio,
        )


    async def generate_video_reel(
        self,
        request: VideoReelRequest,
        output_directory: Optional[Path] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AIMessage:
        """
        Generates a complete video reel from a high-level request.
        Orchestrates:
        1. Scene breakdown (if not provided)
        2. Parallel generation of Music and Scenes (Image -> Video, Audio)
        3. Assembly using MoviePy
        """
        self.logger.info(f"Starting Video Reel Generation: {request.prompt}")
        start_time = time.time()

        if output_directory:
            output_directory.mkdir(parents=True, exist_ok=True)
        else:
            output_directory = BASE_DIR.joinpath('static', 'generated_reels')
            output_directory.mkdir(parents=True, exist_ok=True)

        # 1. Breakdown scenes if needed
        if not request.scenes:
            self.logger.info("Breaking down prompt into scenes...")
            request.scenes = await self._breakdown_prompt_to_scenes(request.prompt)

        # 2. Parallel Generation
        # Task 1: Music
        music_task = asyncio.create_task(
            self._generate_reel_music(request, output_directory)
        )

        # Task 2: Scenes
        scene_video_paths = []
        for i, scene in enumerate(request.scenes):
            try:
                # We await each scene sequentially to maintain order and limit concurrent rate limits
                scene_path = await self._process_scene(scene, i, output_directory, request.aspect_ratio)
                scene_video_paths.append(scene_path)
            except Exception as e:
                self.logger.error(f"Scene {i} failed: {e}")
                scene_video_paths.append(None)

        # Await music
        music_path = await music_task

        # Filter out failed scenes (where video_path is None)
        valid_scene_outputs = [result for result in scene_video_paths if result[0] is not None]

        if not valid_scene_outputs:
            raise RuntimeError("All scene generations failed.")

        # 3. Assembly
        final_video_path = await self._create_reel_assembly(
            valid_scene_outputs,
            music_path,
            output_directory,
            request.transition_type,
            request.output_format
        )

        execution_time = time.time() - start_time

        return AIMessageFactory.from_video(
            output=None, # No single raw output object
            files=[final_video_path],
            input=request.prompt,
            model="google-reel-pipeline",
            provider="google_genai",
            usage=CompletionUsage(execution_time=execution_time),
            user_id=user_id,
            session_id=session_id
        )

    async def _breakdown_prompt_to_scenes(self, prompt: str) -> List[VideoReelScene]:
        """Uses Gemini to parse the user prompt into structured scenes."""
        # Use a lightweight model for this logic task
        model = GoogleModel.GEMINI_2_5_FLASH

        system_instruction = """
        You are a professional video director. Break down the user's request into a series of 3-5 distinct scenes for a short video reel (9:16 vertical format).
        For each scene, provide:
        - `background_prompt`: Detailed visual description for the background image.
        - `foreground_prompt`: (Optional) Text describing a chart, KPI, or specific object to overlay. If not needed, omit.
        - `video_prompt`: Instructions for animating the scene (e.g., "Slow pan up", "Cinematic zoom").
        - `narration_text`: (Optional) A short sentence for the narrator to read.
        - `duration`: Duration in seconds (usually 3-5s).

        Return the result as a JSON array of objects matching this schema.
        """

        # We need structured output
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "background_prompt": {"type": "string"},
                    "foreground_prompt": {"type": "string"},
                    "video_prompt": {"type": "string"},
                    "narration_text": {"type": "string"},
                    "duration": {"type": "number"}
                },
                "required": ["background_prompt", "video_prompt", "duration"]
            }
        }

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=schema
        )

        client = await self.get_client()
        response = await client.aio.models.generate_content(
            model=model.value,
            contents=prompt,
            config=config
        )

        try:
            scenes_data = json.loads(response.text)
            scenes = [VideoReelScene(**s) for s in scenes_data]
            return scenes
        except Exception as e:
            self.logger.error(f"Failed to parse scenes from LLM: {e}")
            # Fallback: create one generic scene
            return [VideoReelScene(
                background_prompt=prompt,
                video_prompt="Cinematic movement",
                duration=5.0
            )]

    async def _process_scene(
        self,
        scene: VideoReelScene,
        index: int,
        output_dir: Path,
        aspect_ratio: AspectRatio
    ) -> Optional[Path]:
        """
        Process a single scene:
        1. Generate Background Image
        2. (Optional) Generate Foreground Image & Composite
        3. Generate Video (Image-to-Video)
        4. (Optional) Generate Narration Audio
        5. Return path to video clip (processed)
        """
        try:
            # 1. Generate Background
            bg_message = await self.generate_image(
                prompt=scene.background_prompt,
                aspect_ratio=aspect_ratio,
                output_directory=str(output_dir) # Saves temporarily
            )
            if not bg_message.images:
                raise RuntimeError(f"Failed to generate background for scene {index}")
            bg_path = bg_message.images[0]

            # 2. Composite Foreground if needed
            final_image_path = bg_path
            if scene.foreground_prompt:
                fg_message = await self.generate_image(
                    prompt=scene.foreground_prompt,
                    aspect_ratio=aspect_ratio, # Match aspect ratio? Or maybe square for overlay? Let's stick to aspect ratio for now.
                    output_directory=str(output_dir)
                )
                if fg_message.images:
                    fg_path = fg_message.images[0]
                    # Composite
                    final_image_path = await self._composite_images(
                        bg_path, fg_path, output_dir, index
                    )

            # 3. Generate Video (Veo)
            video_message = await self.video_generation(
                prompt=scene.video_prompt,
                reference_image=final_image_path,
                model=GoogleModel.VEO_3_1,
                aspect_ratio=aspect_ratio,
                output_directory=output_dir,
                # Reel scenes have their own narration/music, so strip native audio
                include_audio=False,
            )

            if not video_message.files:
                raise RuntimeError(f"Failed to generate video for scene {index}")

            video_path = video_message.files[0]

            # 4. Generate Narration (if needed)
            audio_path = None
            if scene.narration_text:
                speech_message = await self.generate_speech(
                    prompt_data=SpeechGenerationPrompt(
                        prompt=scene.narration_text,
                        speakers=[SpeakerConfig(name="Narrator", voice="zephyr")] # Default narrator changed to zephyr
                    ),
                    output_directory=output_dir
                )
                if speech_message.files:
                    audio_path = speech_message.files[0]

            # Return the video and audio paths so they can be merged in the final assembly
            return (video_path, audio_path)

        except Exception as e:
            self.logger.error(f"Error processing scene {index}: {e}")
            return (None, None)

    def _merge_video_audio(self, video_path: Path, audio_path: Path, output_path: Path):
        """Merges specific narration audio into the video clip."""
        try:
            from moviepy import VideoFileClip, AudioFileClip
            video = VideoFileClip(str(video_path))
            audio = AudioFileClip(str(audio_path))

            final_clip = video.with_audio(audio)
            final_clip.write_videofile(str(output_path), codec="libx264", audio_codec="aac")

            video.close()
            audio.close()
            final_clip.close()
        except ImportError:
            self.logger.error("MoviePy not installed.")
        except Exception as e:
            self.logger.error(f"Failed to merge audio/video: {e}")

    async def _composite_images(self, bg_path: Path, fg_path: Path, output_dir: Path, index: int) -> Path:
        """Overlays foreground image onto background."""
        def _do_composite():
            try:
                bg = Image.open(bg_path).convert("RGBA")
                fg = Image.open(fg_path).convert("RGBA")

                # Let's resize FG to be slightly smaller and centered.
                bg_w, bg_h = bg.size
                target_w = int(bg_w * 0.8)
                ratio = target_w / fg.width
                target_h = int(fg.height * ratio)
                fg = fg.resize((target_w, target_h), Image.Resampling.LANCZOS)

                x = (bg_w - target_w) // 2
                y = (bg_h - target_h) // 2

                bg.paste(fg, (x, y), fg) # Use fg alpha as mask

                out_path = output_dir / f"composite_{index}.png"
                bg.save(out_path, format="PNG")
                return out_path
            except Exception as e:
                self.logger.error(f"Composition failed: {e}")
                return bg_path # Fallback to background only

        return await asyncio.to_thread(_do_composite)

    async def _generate_reel_music(self, request: VideoReelRequest, output_dir: Path) -> Optional[Path]:
        """Generates background music matching the reel duration."""
        try:
            prompt = request.music_prompt or f"Background music for {request.prompt}"
            if request.music_genre:
                prompt += f", Genre: {request.music_genre}"
            if request.music_mood:
                prompt += f", Mood: {request.music_mood}"

            # Calculate needed duration from scenes + buffer for transitions.
            if request.scenes:
                reel_duration = sum(s.duration for s in request.scenes) + 5.0
            else:
                reel_duration = 30.0  # Default if scenes not yet generated

            self.logger.info(
                f"Generating {reel_duration:.0f}s of background music"
            )

            # Use existing generate_music which yields raw PCM bytes
            # We need to collect them and use _save_audio_file to create a valid WAV
            filename = f"music_{uuid.uuid4().hex}"
            file_path = output_dir / filename
            audio_chunks = bytearray()

            async for chunk in self.generate_music(
                prompt=prompt,
                genre=request.music_genre,
                mood=request.music_mood,
                timeout=int(reel_duration)
            ):
                audio_chunks.extend(chunk)

            if not audio_chunks or len(audio_chunks) < 100:
                self.logger.warning("Generated music was empty or too short. Skipping.")
                return None

            # Properly encode raw PCM to WAV
            self._save_audio_file(bytes(audio_chunks), file_path, "audio/wav")
            return file_path.with_suffix('.wav')
        except Exception as e:
            self.logger.error(f"Music generation failed: {e}")
            return None

    async def _create_reel_assembly(
        self,
        scene_outputs: List[tuple[Path, Optional[Path]]],
        music_path: Optional[Path],
        output_dir: Path,
        transition: str,
        output_format: str
    ) -> Path:
        """Stitches everything together using MoviePy.
        scene_outputs: List of tuples containing (video_path, narration_path)
        """
        def _assemble():
            try:
                from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips, vfx, CompositeAudioClip

                clips = []
                for p_idx, (vid_p, narr_p) in enumerate(scene_outputs):
                    clip = VideoFileClip(str(vid_p))
                    
                    # Attach narration to this specific scene if it exists
                    if narr_p and narr_p.exists():
                        scene_audio = AudioFileClip(str(narr_p))
                        clip = clip.with_audio(scene_audio)

                    # Add transition
                    if transition == "crossfade" and p_idx > 0:
                        # Only crossfade if it's not the first clip
                        clip = clip.with_effects([vfx.CrossFadeIn(0.5)])
                    
                    clips.append(clip)

                # Concatenate all scenes into one continuous timeline
                final_video = concatenate_videoclips(clips, method="compose")

                if music_path and music_path.exists():
                    try:
                        music = AudioFileClip(str(music_path))
                        # Loop music if shorter, cut if longer
                        if music.duration < final_video.duration:
                            music = music.with_effects([vfx.Loop(duration=final_video.duration)])
                        else:
                            music = music.subclipped(0, final_video.duration)

                        # Reduce music volume so narration is audible
                        if hasattr(music, 'with_volume_scaled'):
                            music = music.with_volume_scaled(0.3)
                        elif hasattr(music, 'multiply_volume'): # Legacy fallback
                            music = music.multiply_volume(0.3)

                        # Combine audio: keep the assembled scene audio (narrations) and mix music over it
                        if final_video.audio is not None:
                            # Mix narration and background music
                            final_audio = CompositeAudioClip([final_video.audio, music])
                        else:
                            final_audio = music

                        final_video = final_video.with_audio(final_audio)
                    except Exception as me:
                        self.logger.error(f"Failed to add background music: {me}")

                output_filename = f"final_reel_{uuid.uuid4().hex}.{output_format}"
                output_path = output_dir / output_filename

                final_video.write_videofile(
                    str(output_path),
                    codec="libx264" if output_format == "mp4" else "libvpx",
                    audio_codec="aac"
                )

                # Cleanup clips
                for clip in clips:
                    try: clip.close() 
                    except: pass
                if 'music' in locals():
                    try: music.close()
                    except: pass
                try: final_video.close()
                except: pass

                return output_path

            except ImportError:
                self.logger.error("MoviePy not installed.")
                raise
            except Exception as e:
                self.logger.error(f"Assembly failed: {e}")
                raise

        # We need to run this in a thread executor because moviepy is blocking CPU bound
        return await asyncio.to_thread(_assemble)
