import sys
import asyncio
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Union
import logging
import time
from pathlib import Path
import io
import uuid
from PIL import Image
from google import genai
from google.genai.types import (
    GenerateContentConfig,
    Part,
    ModelContent,
    UserContent,
)
from google.genai import types
from navconfig import config, BASE_DIR
from .abstract import AbstractClient, StreamingRetryConfig
from ..models import (
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
    ObjectDetectionResult,
    GoogleModel,
    TTSVoice
)


logging.getLogger(
    name='PIL.TiffImagePlugin'
).setLevel(logging.ERROR)  # Suppress TiffImagePlugin warnings
logging.getLogger(
    name='google_genai'
).setLevel(logging.WARNING)  # Suppress GenAI warnings

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
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
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
            stateless (bool): If True, don't use conversation memory (stateless mode).
        """
        model = model.value if isinstance(model, GoogleModel) else model
        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        # Prepare conversation context using unified memory system
        conversation_history = None
        messages = []

        # Use the abstract method to prepare conversation context
        if stateless:
            # For stateless mode, skip conversation memory
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            conversation_history = None
        else:
            # Use the unified conversation context preparation from AbstractClient
            messages, conversation_history, system_prompt = await self._prepare_conversation_context(
                prompt, files, user_id, session_id, system_prompt
            )

        # Prepare structured output configuration
        output_config = self._get_structured_config(structured_output)

        # Prepare conversation history for Google GenAI format
        history = []
        # Construct history directly from the 'messages' array, which should be in the correct format
        # The last message in 'messages' is the current prompt, which should not be part of history.
        # It's passed separately in `send_message`.
        if messages:
            for msg in messages[:-1]: # Exclude the current user message (last in list)
                role = msg['role'].lower()
                # Assuming content is already in the format [{"type": "text", "text": "..."}]
                # or other GenAI Part types if files were involved.
                # Here, we only expect text content for history, as images/files are for the current turn.
                if role == 'user':
                    # Content can be a list of dicts (for text/parts) or a single string.
                    # Standardize to list of Parts.
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                        # Add other part types if necessary for history (e.g., function responses)
                    if parts:
                        history.append(UserContent(parts=parts))
                elif role in ['assistant', 'model']:
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                    if parts:
                        history.append(ModelContent(parts=parts))

        generation_config = {
            "max_output_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
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
                final_output = await self._parse_structured_output(
                    response.text,
                    output_config
                )
            except Exception:
                final_output = response.text

        # Extract assistant response text for conversation memory
        assistant_response_text = response.text

        # Update conversation memory with the final response
        final_assistant_message = {
            "role": "model", "content": [
                {"type": "text", "text": response.text}
            ]
        }

        # Update conversation memory with unified system
        if not stateless and conversation_history:
            tools_used = [tc.name for tc in all_tool_calls]
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_history,
                messages + [final_assistant_message],
                system_prompt,
                turn_id,
                original_prompt,
                assistant_response_text,
                tools_used
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
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        retry_config: Optional[StreamingRetryConfig] = None,
        on_max_tokens: Optional[str] = "retry"  # "retry", "notify", "ignore"
    ) -> AsyncIterator[str]:
        """
        Stream Google Generative AI's response using AsyncIterator.
        Note: Tool calling is not supported in streaming mode with this implementation.

        Args:
            on_max_tokens: How to handle MAX_TOKENS finish reason:
                - "retry": Automatically retry with increased token limit
                - "notify": Yield a notification message and continue
                - "ignore": Silently continue (original behavior)
        """
        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())
        # Default retry configuration
        if retry_config is None:
            retry_config = StreamingRetryConfig()

        # Use the unified conversation context preparation from AbstractClient
        messages, conversation_history, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

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


        # Retry loop for MAX_TOKENS and other errors
        current_max_tokens = max_tokens or self.max_tokens
        retry_count = 0

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
            ]

        while retry_count <= retry_config.max_retries:
            try:
                generation_config = {
                    "max_output_tokens": current_max_tokens,
                    "temperature": temperature or self.temperature,
                }

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
                max_tokens_reached = False

                async for chunk in await chat.send_message_stream(prompt):
                    # Check for MAX_TOKENS finish reason
                    if (hasattr(chunk, 'candidates') and
                        chunk.candidates and
                        len(chunk.candidates) > 0):

                        candidate = chunk.candidates[0]
                        if (hasattr(candidate, 'finish_reason') and
                            str(candidate.finish_reason) == 'FinishReason.MAX_TOKENS'):
                            max_tokens_reached = True

                            # Handle MAX_TOKENS based on configuration
                            if on_max_tokens == "notify":
                                yield f"\n\n⚠️ **Response truncated due to token limit ({current_max_tokens} tokens). The response may be incomplete.**\n"
                            elif on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                                # We'll handle retry after the loop
                                break

                    # Yield the text content
                    if chunk.text:
                        assistant_content += chunk.text
                        yield chunk.text

                # If MAX_TOKENS reached and we should retry
                if max_tokens_reached and on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                    if retry_count < retry_config.max_retries:
                        # Increase token limit for retry
                        new_max_tokens = int(current_max_tokens * retry_config.token_increase_factor)

                        # Notify user about retry
                        yield f"\n\n🔄 **Response reached token limit ({current_max_tokens}). Retrying with increased limit ({new_max_tokens})...**\n\n"

                        current_max_tokens = new_max_tokens
                        retry_count += 1

                        # Wait before retry
                        await self._wait_with_backoff(retry_count, retry_config)
                        continue
                    else:
                        # Max retries reached
                        yield f"\n\n❌ **Maximum retries reached. Response may be incomplete due to token limits.**\n"

                # If we get here, streaming completed successfully (or we're not retrying)
                break

            except Exception as e:
                if retry_count < retry_config.max_retries:
                    error_msg = f"\n\n⚠️ **Streaming error (attempt {retry_count + 1}): {str(e)}. Retrying...**\n\n"
                    yield error_msg

                    retry_count += 1
                    await self._wait_with_backoff(retry_count, retry_config)
                    continue
                else:
                    # Max retries reached, yield error and break
                    yield f"\n\n❌ **Streaming failed after {retry_config.max_retries} retries: {str(e)}**\n"
                    break

        # Update conversation memory
        if assistant_content:
            final_assistant_message = {
                "role": "assistant", "content": [
                    {"type": "text", "text": assistant_content}
                ]
            }
            # Extract assistant response text for conversation memory
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_history,
                messages + [final_assistant_message],
                system_prompt,
                turn_id,
                prompt,
                assistant_content,
                []
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
        image: Union[Path, bytes],
        reference_images: Optional[Union[List[Path], List[bytes]]] = None,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
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

        messages, conversation_session, _ = await self._prepare_conversation_context(
            prompt, None, user_id, session_id, None
        )

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

        # --- Multi-Modal Content Preparation ---
        if isinstance(image, Path):
            if not image.exists():
                raise FileNotFoundError(
                    f"Image file not found: {image}"
                )
            # Load the primary image
            primary_image = Image.open(image)
        elif isinstance(image, bytes):
            primary_image = Image.open(io.BytesIO(image))
        elif isinstance(image, Image.Image):
            primary_image = image
        else:
            raise ValueError(
                "Image must be a Path, bytes, or PIL.Image object."
            )

        # The content for the API call is a list containing images and the final prompt
        contents = [primary_image]
        if reference_images:
            for ref_path in reference_images:
                self.logger.debug(
                    f"Loading reference image from: {ref_path}"
                )
                if isinstance(ref_path, Path):
                    if not ref_path.exists():
                        raise FileNotFoundError(
                            f"Reference image file not found: {ref_path}"
                        )
                    contents.append(Image.open(ref_path))
                elif isinstance(ref_path, bytes):
                    contents.append(Image.open(io.BytesIO(ref_path)))
                elif isinstance(ref_path, Image.Image):
                    # is already a PIL.Image Object
                    contents.append(ref_path)
                else:
                    raise ValueError(
                        "Reference Image must be a Path, bytes, or PIL.Image object."
                    )

        contents.append(prompt) # The text prompt always comes last
        generation_config = {
            "max_output_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
        }
        output_config = self._get_structured_config(structured_output)
        # Vision models generally don't support tools, so we focus on structured output
        if structured_output:
            self.logger.debug("Structured output requested for vision task.")
            output_config = (
                structured_output
                if isinstance(structured_output, StructuredOutputConfig)
                else StructuredOutputConfig(output_type=structured_output)
            )
            if output_config.format == OutputFormat.JSON:
                generation_config["response_mime_type"] = "application/json"
                generation_config["response_schema"] = output_config.output_type
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
            None,
            turn_id,
            original_prompt,
            response.text,
            []
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
            # bytes of the original MP4
            mp4_bytes = self.client.files.download(file=generated_video.video)
            video_path = self._save_video_file(
                mp4_bytes,
                output_directory,
                video_number=n,
                mime_format=mime_format
            )
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

    async def question(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        use_internal_tools: bool = False, # New parameter to control internal tools
    ) -> AIMessage:
        """
        Ask a question to Google's Generative AI in a stateless manner,
        without conversation history and with optional internal tools.

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
            use_internal_tools (bool): If True, Gemini's built-in tools (e.g., Google Search)
                will be made available to the model. Defaults to False.
        """
        self.logger.info(
            f"Initiating RAG pipeline for prompt: '{prompt[:50]}...'"
        )

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        output_config = self._get_structured_config(structured_output)

        generation_config = {
            "max_output_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        if structured_output:
            if isinstance(structured_output, type):
                generation_config["response_mime_type"] = "application/json"
                generation_config["response_schema"] = structured_output
            elif isinstance(structured_output, StructuredOutputConfig):
                if structured_output.format == OutputFormat.JSON:
                    generation_config["response_mime_type"] = "application/json"
                    generation_config["response_schema"] = structured_output.output_type

        tools = None
        if use_internal_tools:
            tools = self._build_tools("builtin_tools") # Only built-in tools
            self.logger.debug(
                f"Enabled internal tool usage."
            )

        # Build contents for the stateless call
        contents = []
        if files:
            for file_path in files:
                # In a real scenario, you'd handle file uploads to Gemini properly
                # This is a placeholder for file content
                contents.append(
                    {
                        "part": {
                            "inline_data": {
                                "mime_type": "application/octet-stream",
                                "data": "BASE64_ENCODED_FILE_CONTENT"
                            }
                        }
                    }
                )

        # Add the user prompt as the first part
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        all_tool_calls = [] # To capture any tool calls made by internal tools

        final_config = GenerateContentConfig(
            system_instruction=system_prompt,
            tools=tools,
            **generation_config
        )

        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config
        )

        # Handle potential internal tool calls if they are part of the direct generate_content response
        # Gemini can sometimes decide to use internal tools even without explicit function calling setup
        # if the tools are broadly enabled (e.g., through a general 'tool' parameter).
        # This part assumes Gemini's 'generate_content' directly returns tool calls if it uses them.
        if use_internal_tools and response.candidates and response.candidates[0].content.parts:
            function_calls = [
                part.function_call
                for part in response.candidates[0].content.parts
                if hasattr(part, 'function_call') and part.function_call
            ]
            if function_calls:
                tool_call_objects = []
                for fc in function_calls:
                    tc = ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
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

                for tc, result in zip(tool_call_objects, tool_results):
                    tc.execution_time = execution_time / len(tool_call_objects)
                    if isinstance(result, Exception):
                        tc.error = str(result)
                    else:
                        tc.result = result

                all_tool_calls.extend(tool_call_objects)
                pass # We're not doing a multi-turn here for stateless

        final_output = None
        if structured_output:
            try:
                final_output = await self._parse_structured_output(
                    response.text,
                    output_config
                )
            except Exception:
                final_output = response.text

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
        ai_message.provider = "google_genai"

        return ai_message

    async def summarize_text(
        self,
        text: str,
        max_length: int = 500,
        min_length: int = 100,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Generates a summary for a given text in a stateless manner.

        Args:
            text (str): The text content to summarize.
            max_length (int): The maximum desired character length for the summary.
            min_length (int): The minimum desired character length for the summary.
            model (Union[str, GoogleModel]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        self.logger.info(
            f"Generating summary for text: '{text[:50]}...'"
        )

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        # Define the specific system prompt for summarization
        system_prompt = f"""
Your job is to produce a final summary from the following text and identify the main theme.
- The summary should be concise and to the point.
- The summary should be no longer than {max_length} characters and no less than {min_length} characters.
- The summary should be in a single paragraph.
"""

        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        # Build contents for the stateless call. The 'prompt' is the text to be summarized.
        contents = [{
            "role": "user",
            "parts": [{"text": text}]
        }]

        final_config = GenerateContentConfig(
            system_instruction=system_prompt,
            tools=None,  # No tools needed for summarization
            **generation_config
        )

        # Make a stateless call to the model
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config
        )

        # Create the AIMessage response using the factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
            tool_calls=[]
        )
        ai_message.provider = "google_genai"

        return ai_message

    async def translate_text(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.2,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Translates a given text from a source language to a target language.

        Args:
            text (str): The text content to translate.
            target_lang (str): The ISO code for the target language (e.g., 'es', 'fr').
            source_lang (Optional[str]): The ISO code for the source language.
                If None, the model will attempt to detect it.
            model (Union[str, GoogleModel]): The model to use. Defaults to GEMINI_2_5_FLASH,
                which is recommended for speed.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        self.logger.info(
            f"Translating text to '{target_lang}': '{text[:50]}...'"
        )

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        # Construct the system prompt for translation
        if source_lang:
            prompt_instruction = (
                f"Translate the following text from {source_lang} to {target_lang}. "
                "Only return the translated text, without any additional comments or explanations."
            )
        else:
            prompt_instruction = (
                f"First, detect the source language of the following text. Then, translate it to {target_lang}. "
                "Only return the translated text, without any additional comments or explanations."
            )

        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        # Build contents for the stateless API call
        contents = [{
            "role": "user",
            "parts": [{"text": text}]
        }]

        final_config = GenerateContentConfig(
            system_instruction=prompt_instruction,
            tools=None,  # No tools needed for translation
            **generation_config
        )

        # Make a stateless call to the model
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config
        )

        # Create the AIMessage response using the factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
            tool_calls=[]
        )
        ai_message.provider = "google_genai"

        return ai_message

    async def extract_key_points(
        self,
        text: str,
        num_points: int = 5,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH, # Changed to GoogleModel
        temperature: Optional[float] = 0.3,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Extract *num_points* bullet-point key ideas from *text* (stateless).
        """
        self.logger.info(
            f"Extracting {num_points} key points from text: '{text[:50]}...'"
        )

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        system_instruction = ( # Changed to system_instruction for Google GenAI
            f"Extract the {num_points} most important key points from the following text.\n"
            "- Present each point as a clear, concise bullet point (•).\n"
            "- Focus on the main ideas and significant information.\n"
            "- Each point should be self-contained and meaningful.\n"
            "- Order points by importance (most important first)."
        )

        # Build contents for the stateless API call
        contents = [{
            "role": "user",
            "parts": [{"text": text}]
        }]

        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        final_config = GenerateContentConfig(
            system_instruction=system_instruction,
            tools=None, # No tools needed for this task
            **generation_config
        )

        # Make a stateless call to the model
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config
        )

        # Create the AIMessage response using the factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None, # No structured output explicitly requested
            tool_calls=[] # No tool calls for this method
        )
        ai_message.provider = "google_genai" # Set provider

        return ai_message

    async def analyze_sentiment(
        self,
        text: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Perform sentiment analysis on *text* and return a structured explanation (stateless).
        """
        self.logger.info(
            f"Analyzing sentiment for text: '{text[:50]}...'"
        )

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        system_instruction = ( # Changed to system_instruction for Google GenAI
            "Analyze the sentiment of the following text and provide a structured response.\n"
            "Your response must include:\n"
            "1. Overall sentiment (Positive, Negative, Neutral, or Mixed)\n"
            "2. Confidence level (High, Medium, Low)\n"
            "3. Key emotional indicators found in the text\n"
            "4. Brief explanation of your analysis\n\n"
            "Format your answer clearly with numbered sections."
        )

        # Build contents for the stateless API call
        contents = [{
            "role": "user",
            "parts": [{"text": text}]
        }]

        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        final_config = GenerateContentConfig(
            system_instruction=system_instruction,
            tools=None, # No tools needed for this task
            **generation_config
        )

        # Make a stateless call to the model
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config
        )

        # Create the AIMessage response using the factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None, # No structured output explicitly requested
            tool_calls=[] # No tool calls for this method
        )
        ai_message.provider = "google_genai" # Set provider

        return ai_message
