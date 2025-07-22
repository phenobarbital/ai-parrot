import sys
import asyncio
from datetime import datetime
from typing import AsyncIterator, List, Optional, Union, Any
import logging
import time
from enum import Enum
from pathlib import Path
import mimetypes
import io
import uuid
import wave
from PIL import Image
import ffmpeg
from pydub import AudioSegment
from google import genai
from google.genai.types import (
    GenerateContentConfig,
    Part,
    ModelContent,
    UserContent,
)
from google.genai import types
from navconfig import config, BASE_DIR
from .abstract import AbstractClient, MessageResponse
from .models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    StructuredOutputConfig,
    OutputFormat,
    CompletionUsage,
    ImageGenerationPrompt,
    SpeakerConfig,
    SpeechGenerationPrompt,
    VideoGenerationPrompt,
    BoundingBox,
    ObjectDetectionResult
)


logging.getLogger(
    name='PIL.TiffImagePlugin'
).setLevel(logging.ERROR)  # Suppress TiffImagePlugin warnings


class GoogleModel(Enum):
    """Enum for Google AI models."""
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE_PREVIEW = "gemini-2.5-flash-lite-preview-06-17"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_0_FLASH = "gemini-2.0-flash-001"
    IMAGEN_3 = "imagen-3.0-generate-002"
    IMAGEN_4 = "imagen-4.0-generate-preview-06-06"
    GEMINI_2_0_IMAGE_GENERATION = "gemini-2.0-flash-preview-image-generation"
    GEMINI_2_5_FLASH_TTS = "gemini-2.5-flash-preview-tts"
    GEMINI_2_5_PRO_TTS = "gemini-2.5-pro-preview-tts"
    VEO_3_0 = "veo-3.0-generate-preview"
    VEO_2_0 = "veo-2.0-generate-001"

# NEW: Enum for all valid TTS voice names
class TTSVoice(str, Enum):
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
    ZUBENELGENUBI = "zubenelgenubi"


class GoogleGenAIClient(AbstractClient):
    """
    Client for interacting with Google's Generative AI, with support for parallel function calling.
    """
    def __init__(self, **kwargs):
        api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))
        super().__init__(**kwargs)
        self.client = genai.Client(api_key=api_key)

    def _fix_tool_schema(self, schema: dict):
        """Recursively converts schema type values to uppercase for GenAI compatibility."""
        if isinstance(schema, dict):
            for key, value in schema.items():
                if key == 'type' and isinstance(value, str):
                    schema[key] = value.upper()
                else:
                    self._fix_tool_schema(value)
        elif isinstance(schema, list):
            for item in schema:
                self._fix_tool_schema(item)
        return schema

    async def __aenter__(
        self
    ):
        """Initialize the client context."""
        # Google GenAI doesn't need explicit session management
        return self

    def _analyze_prompt_for_tools(self, prompt: str) -> List[str]:
        """
        Analyze the prompt to determine which tools might be needed.
        This is a placeholder for more complex logic that could analyze the prompt.
        """
        prompt_lower = prompt.lower()
        # Keywords that suggest need for built-in tools
        search_keywords = [
            'search',
            'find',
            'lookup',
            'google',
            'web',
            'internet',
            'latest',
            'current',
            'news'
        ]
        function_keywords = []
        if self.tools:
            function_keywords = [
                tool.name.lower() for tool in self.tools.values()
            ]
            function_keywords.extend(
                [tool.description.lower() for tool in self.tools.values()]
            )

        has_search_intent = any(keyword in prompt_lower for keyword in search_keywords)
        has_function_intent = any(keyword in prompt_lower for keyword in function_keywords)
        if has_search_intent and not has_function_intent:
            return "builtin_tools"
        else:
            # Mixed intent - prefer custom functions if available, otherwise builtin
            return "custom_functions" if self.tools else "builtin_tools"

    def _build_tools(self, tool_type: str) -> Optional[List[types.Tool]]:
        """Build tools based on the specified type."""
        if tool_type == "custom_functions" and self.tools:
            function_declarations = [
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=self._fix_tool_schema(tool.input_schema.copy())
                )
                for tool in self.tools.values()
            ]
            return [
                types.Tool(function_declarations=function_declarations)
            ]

        elif tool_type == "builtin_tools":
            return [
                types.Tool(google_search=types.GoogleSearch()),
            ]

        return None

    async def ask(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        force_tool_usage: Optional[str] = None,
        stateless: bool = False
    ) -> AIMessage:
        """
        Ask a question to Google's Generative AI with support for parallel tool calls.

        Args:
            prompt (str): The input prompt for the model.
            model (Union[str, GoogleModel]): The model to use, defaults to GEMINI_2_5_FLASH.
            max_tokens (int): Maximum number of tokens in the response.
            temperature (float): Sampling temperature for response generation.
            files (Optional[List[Union[str, Path]]]): Optional files to include in the request.
            system_prompt (Optional[str]): Optional system prompt to guide the model.
            structured_output (Union[type, StructuredOutputConfig]): Optional structured output configuration.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
            force_tool_usage (Optional[str]): Force usage of specific tools, if needed.
                ("custom_functions", "builtin_tools", or None)
        """
        model = model.value if isinstance(model, GoogleModel) else model
        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # Handle enhanced structured output
        if isinstance(structured_output, StructuredOutputConfig):
            config = structured_output
        else:
            # Backward compatibility - assume JSON
            config = StructuredOutputConfig(
                output_type=structured_output,
                format=OutputFormat.JSON
            ) if structured_output else None

        # Prepare conversation history, is a list of Content objects
        history = []
        for msg in messages:
            content = msg['content']
            if not content:
                continue
            part = Part(text=content[0].get("text", ""))
            role = msg['role'].lower()
            if role == 'user':
                history.append(UserContent(parts=[part]))
            elif role == 'model':
                history.append(ModelContent(parts=[part]))
            else:
                # Handle other roles or raise an error if needed
                print(f"Unknown role: {role}")

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        if structured_output:
            if isinstance(structured_output, type):
                # Pydantic model passed directly
                generation_config["response_mime_type"] = "application/json"
                generation_config["response_schema"] = structured_output
            elif isinstance(structured_output, StructuredOutputConfig):
                if structured_output.format == OutputFormat.JSON:
                    generation_config["response_mime_type"] = "application/json"
                    generation_config["response_schema"] = structured_output.output_type

        # Tool selection
        tools = None
        tool_type = None
        if not structured_output:
            tool_type = force_tool_usage or self._analyze_prompt_for_tools(
                prompt
            )
            tools = self._build_tools(tool_type)
            self.logger.debug(
                f"Selected tool type: {tool_type}"
            )

        # Track tool calls for the response
        all_tool_calls = []

        # Build contents for conversation
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            if role in ["user", "model"]:
                text_parts = [part["text"] for part in msg["content"] if "text" in part]
                if text_parts:
                    contents.append({
                        "role": role,
                        "parts": [{"text": " ".join(text_parts)}]
                    })

        # Add the current prompt
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        chat = None
        final_config = GenerateContentConfig(
            system_instruction=system_prompt,
            tools=tools,
            **generation_config
        )
        if stateless:
            # Create the model instance
            response = await self.client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=final_config
            )
        else:
            # Start the chat session
            chat = self.client.aio.chats.create(
                model=model,
                history=history
            )
            # Make the primary call using the stateful chat session
            response = await chat.send_message(
                message=prompt,
                config=final_config
            )

        # Handle parallel function calls
        if (tool_type == "custom_functions" and
            response.candidates and
            response.candidates[0].content.parts):

            function_calls = [
                part.function_call
                for part in response.candidates[0].content.parts
                if hasattr(part, 'function_call') and part.function_call
            ]

            if function_calls:
                tool_call_objects = []
                # Execute all tool calls concurrently
                for fc in function_calls:
                    tc = ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",  # Generate ID for tracking
                        name=fc.name,
                        arguments=dict(fc.args)
                    )
                    tool_call_objects.append(tc)

                start_time = time.time()
                tool_execution_tasks = [
                    self._execute_tool(fc.name, dict(fc.args)) for fc in function_calls
                ]
                tool_results = await asyncio.gather(
                    *tool_execution_tasks,
                    return_exceptions=True
                )
                execution_time = time.time() - start_time

                # Update ToolCall objects with results
                for tc, result in zip(tool_call_objects, tool_results):
                    tc.execution_time = execution_time / len(tool_call_objects)
                    if isinstance(result, Exception):
                        tc.error = str(result)
                    else:
                        tc.result = result

                all_tool_calls.extend(tool_call_objects)

                # Prepare the function responses as Part objects
                function_response_parts = []
                for fc, result in zip(function_calls, tool_results):
                    if isinstance(result, Exception):
                        response_content = f"Error: {str(result)}"
                    else:
                        response_content = str(result)  # Ensure it's a string

                    # Create proper Part object for function response
                    function_response_parts.append(
                        Part(
                            function_response=types.FunctionResponse(
                                name=fc.name,
                                response={"result": response_content}
                            )
                        )
                    )

                # Send the tool results back to the model using proper format
                if chat:
                    response = await chat.send_message(
                        function_response_parts
                    )

        # Handle structured output
        final_output = None
        if structured_output:
            try:
                if hasattr(structured_output, 'model_validate_json'):
                    final_output = structured_output.model_validate_json(response.text)
                elif hasattr(structured_output, 'model_validate'):
                    parsed_json = self._json.loads(response.text)
                    final_output = structured_output.model_validate(parsed_json)
                else:
                    final_output = self._json.loads(response.text)
            except Exception:
                final_output = response.text

        # Update conversation memory with the final response
        final_assistant_message = {
            "role": "model", "content": [
                {"type": "text", "text": response.text}
            ]
        }
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages + [final_assistant_message],
            system_prompt
        )

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != response.text else None,
            tool_calls=all_tool_calls
        )

        # Override provider to distinguish from Vertex AI
        ai_message.provider = "google_genai"

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream Google Generative AI's response using AsyncIterator.
        Note: Tool calling is not supported in streaming mode with this implementation.
        """
        model = model.value if isinstance(model, GoogleModel) else model

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # Prepare conversation history, is a list of Content objects
        history = []
        for msg in messages:
            content = msg['content']
            if not content:
                continue
            part = Part(text=content[0].get("text", ""))
            role = msg['role'].lower()
            if role == 'user':
                history.append(UserContent(parts=[part]))
            elif role == 'model':
                history.append(ModelContent(parts=[part]))
            else:
                # Handle other roles or raise an error if needed
                print(f"Unknown role: {role}")

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        tools = None
        if self.tools:
            # Convert to newer API format - create proper Tool objects
            function_declarations = []

            # Add custom function tools
            for tool in self.tools.values():
                function_declarations.append(
                    types.FunctionDeclaration(
                        name=tool.name,
                        description=tool.description,
                        parameters=self._fix_tool_schema(tool.input_schema.copy())
                    )
                )

            # Create a single Tool object with all function declarations plus built-in tools
            tools = [
                types.Tool(function_declarations=function_declarations),
                # types.Tool(google_search=types.GoogleSearch),
                # types.Tool(code_execution=types.ToolCodeExecution)
            ]

        # Start the chat session
        chat = self.client.aio.chats.create(
            model=model,
            history=history,
            config=GenerateContentConfig(
                system_instruction=system_prompt,
                tools=tools,
                **generation_config
            )
        )

        assistant_content = ""
        async for chunk in await chat.send_message_stream(prompt):
            if chunk.text:
                assistant_content += chunk.text
                yield chunk.text

        # Update conversation memory
        if assistant_content:
            final_assistant_message = {
                "role": "assistant", "content": [
                    {"type": "text", "text": assistant_content}
                ]
            }
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages + [final_assistant_message],
                system_prompt
            )

    async def batch_ask(self, requests) -> List[AIMessage]:
        """Process multiple requests in batch."""
        # Google GenAI doesn't have a native batch API, so we process sequentially
        results = []
        for request in requests:
            result = await self.ask(**request)
            results.append(result)
        return results

    async def ask_to_image(
        self,
        prompt: str,
        image_path: Path,
        reference_images: Optional[List[Path]] = None,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        structured_output: Union[type, StructuredOutputConfig] = None,
        count_objects: bool = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Ask a question to Google's Generative AI using a stateful chat session.
        """
        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, None, user_id, session_id, None
        )

        history = []
        for msg in messages:
            content_text = msg['content'][0].get("text") if msg.get('content') else ""
            if not content_text:
                continue
            part = Part(text=content_text)
            role = msg['role'].lower()
            if role == 'user':
                history.append(UserContent(parts=[part]))
            elif role == 'model' or role == 'assistant':
                history.append(ModelContent(parts=[part]))

        # --- Multi-Modal Content Preparation ---
        self.logger.debug(f"Loading primary image from: {image_path}")
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        # Load the primary image
        primary_image = Image.open(image_path)

        # The content for the API call is a list containing images and the final prompt
        contents = [primary_image]
        if reference_images:
            for ref_path in reference_images:
                self.logger.debug(
                    f"Loading reference image from: {ref_path}"
                )
                contents.append(Image.open(ref_path))

        contents.append(prompt) # The text prompt always comes last
        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }
        # Vision models generally don't support tools, so we focus on structured output
        if structured_output:
            self.logger.debug("Structured output requested for vision task.")
            config = (
                structured_output
                if isinstance(structured_output, StructuredOutputConfig)
                else StructuredOutputConfig(output_type=structured_output)
            )
            if config.format == OutputFormat.JSON:
                generation_config["response_mime_type"] = "application/json"
                generation_config["response_schema"] = config.output_type
        elif count_objects:
            # Default to JSON for structured output if not specified
            generation_config["response_mime_type"] = "application/json"
            generation_config["response_schema"] = ObjectDetectionResult
            structured_output = ObjectDetectionResult

        # Create the stateful chat session
        chat = self.client.aio.chats.create(model=model, history=history)
        final_config = GenerateContentConfig(**generation_config)

        # Make the primary multi-modal call
        self.logger.debug(f"Sending {len(contents)} parts to the model.")
        response = await chat.send_message(
            message=contents,
            config=final_config
        )

        # --- Response Handling ---
        final_output = None
        if structured_output:
            try:
                if not isinstance(structured_output, StructuredOutputConfig):
                    structured_output = StructuredOutputConfig(
                        output_type=structured_output,
                        format=OutputFormat.JSON
                    )
                final_output = await self._parse_structured_output(
                    response.text,
                    structured_output
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to parse structured output from vision model: {e}"
                )
                final_output = response.text

        final_assistant_message = {
            "role": "model", "content": [
                {"type": "text", "text": response.text}
            ]
        }
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages + [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"[Image Analysis]: {prompt}"}
                    ]
                },
                final_assistant_message
            ],
            None
        )

        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != response.text else None,
            tool_calls=[]
        )
        ai_message.provider = "google_genai"
        return ai_message

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
            raw_response = {} # Initialize an empty dict for the raw response

            if image_response.generated_images:
                self.logger.info(
                    f"Successfully generated {len(image_response.generated_images)} image(s)."
                )
                raw_response['generated_images'] = []
                for i, generated_image in enumerate(image_response.generated_images):
                    pil_image = generated_image.image
                    pil_images.append(pil_image)

                    raw_response['generated_images'].append({
                        'uri': getattr(generated_image, 'uri', None),
                        'seed': getattr(generated_image, 'seed', None)
                    })

                    if output_directory:
                        output_directory.mkdir(parents=True, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        file_path = output_directory / f"generated_image_{timestamp}_{i}.jpeg"
                        pil_image.save(file_path)
                        saved_image_paths.append(file_path)
                        self.logger.info(
                            f"Saved image to {file_path}"
                        )

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

    def _save_audio_file(self, audio_data: bytes, output_path: Path, mime_format: str):
        """
        Saves the audio data to a file in the specified format.
        """
        if mime_format == "audio/wav":
            # Save as WAV using the wave module
            output_path = output_path.with_suffix('.wav')
            with wave.open(str(output_path), mode="wb") as wf:
                wf.setnchannels(1)  # Mono  # noqa
                wf.setsampwidth(2)   # 16-bit  # noqa
                wf.setcomptype("NONE", "not compressed")  # noqa
                wf.setframerate(24000) # 24kHz sample rate  # noqa
                wf.writeframes(audio_data)  # noqa
        elif mime_format in ("audio/mpeg", "audio/webm"):
            # choose extension and pydub format name
            ext = "mp3" if mime_format == "audio/mpeg" else "webm"
            fp = output_path.with_suffix(f'.{ext}')

            # wrap raw PCM bytes in a BytesIO so pydub can read them
            raw = io.BytesIO(audio_data)
            seg = AudioSegment.from_raw(
                raw,
                sample_width=2,
                frame_rate=24000,
                channels=1
            )
            # export using the appropriate container/codec
            seg.export(str(fp), format=ext)

        else:
            raise ValueError(f"Unsupported mime_format: {mime_format!r}")

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
    ) -> AIMessage:
        """
        Generates speech from text using either a single voice or multiple voices.
        """
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

        try:
            start_time = time.time()
            response = await self.client.aio.models.generate_content(
                model=model,
                contents=prompt_data.prompt,
                config=config,
            )
            execution_time = time.time() - start_time

            audio_data = response.candidates[0].content.parts[0].inline_data.data
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

            usage = CompletionUsage(
                execution_time=execution_time,
                # Speech API does not return token counts
                input_tokens=len(prompt_data.prompt), # Approximation
            )

            ai_message = AIMessageFactory.from_speech(
                output=audio_data, # The raw PCM audio data
                files=saved_file_paths,
                input=prompt_data.prompt,
                model=model,
                provider="google_genai",
                usage=usage,
                user_id=user_id,
                session_id=session_id,
                raw_response=None # Response object isn't easily serializable
            )
            return ai_message

        except Exception as e:
            self.logger.error(f"Speech generation failed: {e}")
            raise

    def _save_video_file(
        self,
        file_ref,
        output_dir: Path,
        video_number: int = 1,
        mime_format: str = 'video/mp4'
    ) -> Path:
        """
        Download the GenAI video (always MP4), then either:
        - Write it straight out if mime_format is video/mp4
        - Otherwise, transcode via ffmpeg to the requested container/codec
        Returns the Path to the saved file.

        """
        # 1) Download into memory
        # bytes of the original MP4
        mp4_bytes = self.client.files.download(file=file_ref)

        # 2) Prep output path
        output_dir.mkdir(parents=True, exist_ok=True)
        ext = mimetypes.guess_extension(mime_format) or '.mp4'
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = output_dir / f"generated_video_{timestamp}_{video_number}{ext}"

        # 3) Straight-dump for MP4
        if mime_format == "video/mp4":
            out_path.write_bytes(mp4_bytes)
            self.logger.info(
                f"Saved MP4 to {out_path}"
            )
            return out_path

        # 4) Transcode via ffmpeg for other formats
        try:
            if mime_format == 'video/avi':
                video_format = 'avi'
                vcodec = 'libxvid'  # H.264 codec for AVI
                acodec = 'mp2'       # MP2 audio codec for AVI
            elif mime_format == 'video/webm':
                video_format = 'webm'
                vcodec = 'libvpx'  # VP8 video codec for WebM
                acodec = 'libopus'
            elif mime_format == 'video/mpeg':
                video_format = 'mpeg'
                vcodec = 'mpeg2video'  # MPEG-2 video codec
                acodec = 'mp2'       # MP2 audio codec
            else:
                raise ValueError(
                    f"Unsupported mime_format for video transcoding: {mime_format!r}"
                )
            # 1. Set up the FFmpeg process
            process = (
                ffmpeg  # pylint: disable=E1101 # noqa
                .input('pipe:', format='mp4')  # pylint: disable=E1101 # noqa
                .output(
                    'pipe:',
                    format=video_format,  # Output container format
                    vcodec=vcodec,      # video codec
                    acodec=acodec      # audio codec
                )
                .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
            )
            # 2. Pipe the mp4 bytes in and get the webm bytes out
            out_bytes, err = process.communicate(input=mp4_bytes)
            process.wait()
            if err:
                self.logger.error("FFmpeg Error:", err.decode())
            with open(out_path, 'wb') as f:
                f.write(out_bytes)
            self.logger.info(
                f"Saved {mime_format} to {out_path}"
            )
            return out_path
        except Exception as e:
            self.logger.error(
                f"Error saving {mime_format} to {out_path}: {e}"
            )
            return None


    async def generate_videos(
        self,
        prompt: VideoGenerationPrompt,
        reference_image: Optional[Path] = None,
        output_directory: Optional[Path] = None,
        mime_format: str = "video/mp4",
        model: Union[str, GoogleModel] = GoogleModel.VEO_3_0,
    ) -> AIMessage:
        """
        Generate a video using the specified model and prompt.
        """
        if prompt.model:
            model = prompt.model
        model = model.value if isinstance(model, GoogleModel) else model
        if model not in [GoogleModel.VEO_2_0.value, GoogleModel.VEO_3_0.value]:
            raise ValueError(
                "Generate Videos are only supported with VEO 2.0 or VEO 3.0 models."
            )
        self.logger.info(
            f"Starting Video generation with model: {model}"
        )
        if output_directory:
            output_directory.mkdir(parents=True, exist_ok=True)
        else:
            output_directory = BASE_DIR.joinpath('static', 'generated_videos')
        args = {
            "prompt": prompt.prompt,
            "model": model,
        }

        if reference_image:
            # if a reference image is used, only Veo2 is supported:
            self.logger.info(
                f"Veo 3.0 does not support reference images, using VEO 2.0 instead."
            )
            model = GoogleModel.VEO_2_0.value
            self.logger.info(
                f"Using reference image: {reference_image}"
            )
            if not reference_image.exists():
                raise FileNotFoundError(
                    f"Reference image not found: {reference_image}"
                )
            # Load the reference image
            ref_image = Image.open(reference_image)
            args['image'] = types.Image(image_bytes=ref_image)

        start_time = time.time()
        operation = self.client.models.generate_videos(
            **args,
            config=types.GenerateVideosConfig(
                aspect_ratio=prompt.aspect_ratio or "16:9",  # Default to 16:9
                negative_prompt=prompt.negative_prompt,  # Optional negative prompt
                number_of_videos=prompt.number_of_videos,  # Number of videos to generate
            )
        )

        print("Video generation job started. Waiting for completion...", end="")
        spinner_chars = ['|', '/', '-', '\\']
        check_interval = 10  # Check status every 10 seconds
        spinner_index = 0

        # This loop checks the job status every 10 seconds
        while not operation.done:
            # This inner loop runs the spinner animation for the check_interval
            for _ in range(check_interval):
                # Write the spinner character to the console
                sys.stdout.write(
                    f"\rVideo generation job started. Waiting for completion... {spinner_chars[spinner_index]}"
                )
                sys.stdout.flush()
                spinner_index = (spinner_index + 1) % len(spinner_chars)
                time.sleep(1) # Animate every second

            # After 10 seconds, get the updated operation status
            operation = self.client.operations.get(operation)

        print("\rVideo generation job completed.          ", end="")

        for n, generated_video in enumerate(operation.result.generated_videos):
            # Download the generated videos
            video_path = self._save_video_file(
                generated_video.video,
                output_directory,
                video_number=n,
                mime_format=mime_format
            )
            # self.client.files.download(file=generated_video.video)
            # video_path = output_directory.joinpath(
            #     f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{n}.mp4"
            # )
            # generated_video.video.save(video_path)

            # self.logger.info(
            #     f"Saved Video to {video_path}"
            # )

        execution_time = time.time() - start_time
        usage = CompletionUsage(
            execution_time=execution_time,
            # Video API does not return token counts
            input_tokens=len(prompt.prompt), # Approximation
        )

        ai_message = AIMessageFactory.from_video(
            output=operation, # The raw Video object
            files=[video_path],
            input=prompt.prompt,
            model=model,
            provider="google_genai",
            usage=usage,
            user_id=None,
            session_id=None,
            raw_response=None # Response object isn't easily serializable
        )
        return ai_message
