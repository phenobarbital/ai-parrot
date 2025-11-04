import asyncio
import json
from typing import AsyncIterator, Dict, List, Optional, Union, Any
from typing import List as TypingList
import base64
import io
import time
from enum import Enum
import uuid
from pathlib import Path
import mimetypes
from PIL import Image
from pydantic import BaseModel, Field
from navconfig import config
from datamodel.exceptions import ParserError  # pylint: disable=E0611 # noqa
from datamodel.parsers.json import json_decoder  # pylint: disable=E0611 # noqa
from .base import AbstractClient, BatchRequest, StreamingRetryConfig
from ..models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    OutputFormat,
    StructuredOutputConfig,
    ObjectDetectionResult
)
from ..models.outputs import (
    SentimentAnalysis,
    ProductReview
)

class ClaudeModel(Enum):
    """Enum for Claude models."""
    SONNET_4 = "claude-sonnet-4-20250514"
    SONNET_4_5 = "claude-sonnet-4-5"
    OPUS_4 = "claude-opus-4-20241022"
    OPUS_4_1 = "claude-opus-4-1"
    SONNET_3_5 = "claude-3-5-sonnet-20241022"
    HAIKU_3_5 = "claude-3-5-haiku-20241022"


class ClaudeClient(AbstractClient):
    """Client for interacting with the Claude API."""
    version: str = "2023-06-01"
    client_type: str = "anthropic"
    client_name: str = "claude"
    use_session: bool = True

    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://api.anthropic.com",
        **kwargs
    ):
        self.api_key = api_key or config.get('ANTHROPIC_API_KEY')
        self.base_url = base_url
        self.base_headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.version
        }
        super().__init__(**kwargs)

    async def ask(
        self,
        prompt: str,
        model: Union[Enum, str] = ClaudeModel.SONNET_4,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
    ) -> AIMessage:
        """Ask Claude a question with optional conversation memory.

        Args:
            use_tools: If None, uses instance default. If True/False, overrides for this call.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # If use_tools is None, use the instance default
        _use_tools = use_tools if use_tools is not None else self.enable_tools

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_history, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        output_config = self._get_structured_config(
            structured_output
        )

        if structured_output:
            schema_instruction = output_config.format_schema_instruction()
            system_prompt = (
                f"{system_prompt}\n\n{schema_instruction}"
                if system_prompt
                else schema_instruction
            )

        payload = {
            "model": model.value if isinstance(model, Enum) else model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
            "messages": messages
        }

        if system_prompt:
            payload["system"] = system_prompt

        if _use_tools and (tools and isinstance(tools, list)):
            for tool in tools:
                self.register_tool(tool)

        if _use_tools:
            payload["tools"] = self._prepare_tools()

        # Track tool calls for the response
        all_tool_calls = []

        # Handle tool calls in a loop
        while True:
            async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
                response.raise_for_status()
                result = await response.json()
                # Check if Claude wants to use a tool
                if result.get("stop_reason") == "tool_use":
                    tool_results = []

                    for content_block in result["content"]:
                        if content_block["type"] == "tool_use":
                            tool_name = content_block["name"]
                            tool_input = content_block["input"]
                            tool_id = content_block["id"]

                            # Create ToolCall object and execute
                            tc = ToolCall(
                                id=tool_id,
                                name=tool_name,
                                arguments=tool_input
                            )

                            try:
                                start_time = time.time()
                                tool_result = await self._execute_tool(tool_name, tool_input)
                                execution_time = time.time() - start_time

                                tc.result = tool_result
                                tc.execution_time = execution_time

                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": str(tool_result)
                                })
                            except Exception as e:
                                tc.error = str(e)
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "is_error": True,
                                    "content": str(e)
                                })

                            all_tool_calls.append(tc)

                    # Add tool results and continue conversation
                    messages.append({"role": "assistant", "content": result["content"]})
                    messages.append({"role": "user", "content": tool_results})
                    payload["messages"] = messages
                else:
                    # No more tool calls, add assistant response and break
                    messages.append({"role": "assistant", "content": result["content"]})
                    break

        # Handle structured output
        final_output = None
        if structured_output:
            # Extract text content from Claude's response
            text_content = "".join(
                content_block["text"]
                for content_block in result["content"]
                if content_block["type"] == "text"
            )
            try:
                if output_config.custom_parser:
                    final_output = await output_config.custom_parser(
                        text_content
                    )
                final_output = await self._parse_structured_output(
                    text_content,
                    output_config
                )
            except Exception:
                final_output = text_content

        # Extract assistant response text for conversation memory
        assistant_response_text = "".join(
            content_block.get("text", "")
            for content_block in result.get("content", [])
            if content_block.get("type") == "text"
        )

        # Update conversation memory with unified system
        tools_used = [tc.name for tc in all_tool_calls]
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_history,
            messages,
            system_prompt,
            turn_id,
            original_prompt,
            assistant_response_text,
            tools_used
        )

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_claude(
            response=result,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output,
            tool_calls=all_tool_calls
        )

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        retry_config: Optional[StreamingRetryConfig] = None,
        on_max_tokens: Optional[str] = "retry",  # "retry", "notify", "ignore"
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncIterator[str]:
        """Stream Claude's response using AsyncIterator with optional conversation memory."""
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        # Default retry configuration
        if retry_config is None:
            retry_config = StreamingRetryConfig()

        messages, conversation_history, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        current_max_tokens = max_tokens or self.max_tokens
        retry_count = 0
        while retry_count <= retry_config.max_retries:
            try:
                payload = {
                    "model": model.value if isinstance(model, Enum) else model,
                    "max_tokens": current_max_tokens,
                    "temperature": temperature or self.temperature,
                    "messages": messages,
                    "stream": True
                }

                if system_prompt:
                    payload["system"] = system_prompt

                payload["tools"] = self._prepare_tools()

                assistant_content = ""
                max_tokens_reached = False
                stop_reason = None
                async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
                    # Handle HTTP errors that might warrant retry
                    if response.status == 429 and retry_config.retry_on_rate_limit:
                        # Rate limit - retry with backoff
                        if retry_count < retry_config.max_retries:
                            yield f"\n\n⚠️ **Rate limited (attempt {retry_count + 1}). Retrying...**\n\n"
                            retry_count += 1
                            await self._wait_with_backoff(retry_count, retry_config)
                            continue
                        else:
                            yield f"\n\n❌ **Rate limit exceeded. Max retries reached.**\n"
                            break
                    elif response.status >= 500 and retry_config.retry_on_server_error:
                        # Server error - retry
                        if retry_count < retry_config.max_retries:
                            yield f"\n\n⚠️ **Server error {response.status} (attempt {retry_count + 1}). Retrying...**\n\n"
                            retry_count += 1
                            await self._wait_with_backoff(retry_count, retry_config)
                            continue
                        else:
                            yield f"\n\n❌ **Server error {response.status}. Max retries reached.**\n"
                            break

                    # Raise for other HTTP errors
                    response.raise_for_status()

                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        if line.startswith('data: '):
                            data = line[6:]
                            if data == '[DONE]':
                                break
                            try:
                                event = json_decoder(data)
                                # Check for max tokens in Claude's streaming response
                                if event.get('type') == 'message_stop':
                                    stop_reason = event.get('stop_reason')
                                    if stop_reason == 'max_tokens':
                                        max_tokens_reached = True
                                elif event.get('type') == 'content_block_delta':
                                    delta = event.get('delta', {})
                                    if delta.get('type') == 'text_delta':
                                        text_chunk = delta.get('text', '')
                                        assistant_content += text_chunk
                                        yield text_chunk
                            except (ParserError, json.JSONDecodeError):
                                continue
                # Check if we reached max tokens
                if max_tokens_reached:
                    if on_max_tokens == "notify":
                        yield f"\n\n⚠️ **Response truncated due to token limit ({current_max_tokens} tokens). The response may be incomplete.**\n"
                    elif on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
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
                    elif on_max_tokens == "ignore":
                        continue  # Just ignore and yield what we have
                # If we get here, streaming completed successfully
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
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_history,
                messages + [{
                    "role": "assistant",
                    "content": [{"type": "text", "text": assistant_content}]
                }],
                system_prompt,
                turn_id,
                original_prompt,
                assistant_content,
                []  # No tools used in streaming
            )

    async def batch_ask(self, requests: List[BatchRequest]) -> List[AIMessage]:
        """Process multiple requests in batch."""
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Prepare batch payload in correct format
        batch_payload = {
            "requests": [
                {
                    "custom_id": req.custom_id,
                    "params": req.params
                }
                for req in requests
            ]
        }

        # Add beta header for Message Batches API
        headers = {"anthropic-beta": "message-batches-2024-09-24"}

        # Create batch
        async with self.session.post(
            f"{self.base_url}/v1/messages/batches",
            json=batch_payload,
            headers=headers
        ) as response:
            response.raise_for_status()
            batch_info = await response.json()
            batch_id = batch_info["id"]

        # Poll for completion
        while True:
            async with self.session.get(
                f"{self.base_url}/v1/messages/batches/{batch_id}",
                headers=headers
            ) as response:
                response.raise_for_status()
                batch_status = await response.json()

                if batch_status["processing_status"] == "ended":
                    break
                elif batch_status["processing_status"] in ["failed", "canceled"]:
                    raise RuntimeError(f"Batch processing failed: {batch_status}")

                await asyncio.sleep(5)  # Wait 5 seconds before polling again

        # Retrieve results - the results_url is provided in the batch status
        results_url = batch_status.get("results_url")
        if results_url:
            async with self.session.get(results_url) as response:
                response.raise_for_status()
                results_text = await response.text()

                # Parse JSONL format and convert to AIMessage
                results = []
                for line in results_text.strip().split('\n'):
                    if line:
                        batch_result = json_decoder(line)
                        # Extract the response from batch format
                        if 'response' in batch_result and 'body' in batch_result['response']:
                            claude_response = batch_result['response']['body']

                            # Create AIMessage from batch result
                            ai_message = AIMessageFactory.from_claude(
                                response=claude_response,
                                input_text="Batch request",
                                model=claude_response.get('model', 'unknown'),
                                turn_id=str(uuid.uuid4())
                            )
                            results.append(ai_message)
                        else:
                            # Fallback for unexpected format
                            results.append(batch_result)

                return results
        else:
            raise RuntimeError("No results URL provided in batch status")

    def _encode_image_for_claude(
        self,
        image: Union[Path, bytes, Image.Image]
    ) -> Dict[str, Any]:
        """Encode image for Claude's vision API."""

        if isinstance(image, Path):
            if not image.exists():
                raise FileNotFoundError(f"Image file not found: {image}")

            # Get mime type
            mime_type, _ = mimetypes.guess_type(str(image))
            if not mime_type or not mime_type.startswith('image/'):
                mime_type = "image/jpeg"  # Default fallback

            # Read and encode the file
            with open(image, "rb") as f:
                encoded_data = base64.b64encode(f.read()).decode('utf-8')

        elif isinstance(image, bytes):
            # Handle raw bytes
            mime_type = "image/jpeg"  # Default, could be improved with image format detection
            encoded_data = base64.b64encode(image).decode('utf-8')

        elif isinstance(image, Image.Image):
            # Handle PIL Image object
            buffer = io.BytesIO()
            # Save as JPEG by default (could be made configurable)
            image_format = "JPEG"
            if image.mode in ("RGBA", "LA", "P"):
                # Convert to RGB for JPEG compatibility
                image = image.convert("RGB")

            image.save(buffer, format=image_format)
            encoded_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
            mime_type = f"image/{image_format.lower()}"

        else:
            raise ValueError("Image must be a Path, bytes, or PIL.Image object.")

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": encoded_data
            }
        }

    async def ask_to_image(
        self,
        prompt: str,
        image: Union[Path, bytes, Image.Image],
        reference_images: Optional[List[Union[Path, bytes, Image.Image]]] = None,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        count_objects: bool = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None
    ) -> AIMessage:
        """
        Ask Claude a question about an image with optional conversation memory.

        Args:
            prompt (str): The question or prompt about the image.
            image (Union[Path, bytes, Image.Image]): The primary image to analyze.
            reference_images (Optional[List[Union[Path, bytes, Image.Image]]]):
                Optional reference images.
            model (Union[ClaudeModel, str]): The Claude model to use.
            max_tokens (int): Maximum tokens for the response.
            temperature (float): Sampling temperature.
            structured_output (Union[type, StructuredOutputConfig]):
                Optional structured output format.
            count_objects (bool):
                Whether to count objects in the image (enables default JSON output).
            user_id (Optional[str]): User identifier for conversation memory.
            session_id (Optional[str]): Session identifier for conversation memory.

        Returns:
            AIMessage: The response from Claude about the image.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        # Get conversation history if available
        conversation_history = None
        messages = []

        # Get conversation context (but don't include files since we handle images separately)
        if user_id and session_id and self.conversation_memory:
            chatbot_key = self._get_chatbot_key()
            # Get or create conversation history
            conversation_history = await self.conversation_memory.get_history(
                user_id,
                session_id,
                chatbot_id=chatbot_key
            )
            if not conversation_history:
                conversation_history = await self.conversation_memory.create_history(
                    user_id,
                    session_id,
                    chatbot_id=chatbot_key
                )

            # Get previous conversation messages for context
            # Convert turns to API message format
            messages = conversation_history.get_messages_for_api()

        output_config = self._get_structured_config(
            structured_output
        )

        # Prepare the content for the current message
        content = []

        # Add the primary image first
        primary_image_content = self._encode_image_for_claude(image)
        content.append(primary_image_content)

        # Add reference images if provided
        if reference_images:
            for ref_image in reference_images:
                ref_image_content = self._encode_image_for_claude(ref_image)
                content.append(ref_image_content)

        # Add the text prompt last
        content.append({
            "type": "text",
            "text": prompt
        })

        # Create the new user message with image content
        new_message = {
            "role": "user",
            "content": content
        }

        # Replace the last message (which was just text) with our multimodal message
        if messages and messages[-1]["role"] == "user":
            messages[-1] = new_message
        else:
            messages.append(new_message)

        # Prepare the payload
        payload = {
            "model": model.value if isinstance(model, ClaudeModel) else model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
            "messages": messages
        }

        # Add system prompt for structured output
        if structured_output:
            structured_system_prompt = "You are a precise assistant that responds only with valid JSON when requested. When asked for structured output, respond with ONLY the JSON object, no additional text, explanations, or markdown formatting."
            if system_prompt:
                payload["system"] = f"{system_prompt}\n\n{structured_system_prompt}"
            else:
                payload["system"] = structured_system_prompt
        elif system_prompt:
            payload["system"] = system_prompt

        if count_objects and not structured_output:
            # Import ObjectDetectionResult from models
            try:
                structured_output = ObjectDetectionResult
            except ImportError:
                # Fallback - define a simple structure if import fails
                class SimpleObjectDetection(BaseModel):
                    """Simple object detection result structure."""
                    analysis: str = Field(description="Detailed analysis of the image")
                    total_count: int = Field(description="Total number of objects detected")
                    objects: TypingList[str] = Field(
                        default_factory=list,
                        description="List of detected objects"
                    )

                structured_output = SimpleObjectDetection
            output_config = StructuredOutputConfig(
                output_type=structured_output,
                format=OutputFormat.JSON
            )

        # Note: Claude's vision models typically don't support tool calling
        # So we skip tool preparation for vision requests
        # Track tool calls (will likely be empty for vision requests)
        all_tool_calls = []

        # Make the API request
        async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
            response.raise_for_status()
            result = await response.json()

        # Handle structured output
        final_output = None
        text_content = ""

        # Extract text content from Claude's response
        for content_block in result.get("content", []):
            if content_block.get("type") == "text":
                text_content += content_block.get("text", "")

        if structured_output:
            try:
                final_output = await self._parse_structured_output(
                    text_content,
                    output_config
                )
            except Exception:
                final_output = text_content
        else:
            final_output = text_content

        # Add assistant response to messages for conversation memory
        assistant_message = {"role": "assistant", "content": result["content"]}
        messages.append(assistant_message)

        # Update conversation memory
        tools_used = [tc.name for tc in all_tool_calls]
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_history,
            messages + [{"role": "assistant", "content": result["content"]}],
            system_prompt,
            turn_id,
            f"[Image Analysis]: {original_prompt}",  # Include image context in the stored prompt
            text_content,
            tools_used
        )



        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_claude(
            response=result,
            input_text=f"[Image Analysis]: {original_prompt}",
            model=model.value if isinstance(model, ClaudeModel) else model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output,
            tool_calls=all_tool_calls
        )

        # Ensure text field is properly set for property access
        if not structured_output:
            ai_message.response = final_output

        return ai_message

    async def summarize_text(
        self,
        text: str,
        max_length: int = 500,
        min_length: int = 100,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
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
            model (Union[ClaudeModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        self.logger.info(
            f"Generating summary for text: '{text[:50]}...'"
        )

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())

        # Define the specific system prompt for summarization
        system_prompt = f"""Your job is to produce a final summary from the following text and identify the main theme.
- The summary should be concise and to the point.
- The summary should be no longer than {max_length} characters and no less than {min_length} characters.
- The summary should be in a single paragraph.
- Focus on the key information and main points.
- Write in clear, accessible language."""

        # Prepare the message for Claude
        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": text}]
        }]

        payload = {
            "model": model.value if isinstance(model, Enum) else model,
            "max_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
            "messages": messages,
            "system": system_prompt
        }

        # Make a stateless call to Claude
        async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
            response.raise_for_status()
            result = await response.json()

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_claude(
            response=result,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
            tool_calls=[]
        )

        return ai_message


    async def translate_text(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        temperature: Optional[float] = 0.2,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Translates a given text from a source language to a target language.

        Args:
            text (str): The text content to translate.
            target_lang (str): The target language name or ISO code (e.g., 'Spanish', 'es', 'French', 'fr').
            source_lang (Optional[str]): The source language name or ISO code.
                If None, Claude will attempt to detect it.
            model (Union[ClaudeModel, str]): The model to use. Defaults to SONNET_4.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        self.logger.info(
            f"Translating text to '{target_lang}': '{text[:50]}...'"
        )

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())

        # Construct the system prompt for translation
        if source_lang:
            system_prompt = f"""You are a professional translator. Translate the following text from {source_lang} to {target_lang}.
Requirements:
- Provide only the translated text, without any additional comments or explanations
- Maintain the original meaning and tone
- Use natural, fluent language in the target language
- Preserve formatting if present (like line breaks, bullet points, etc.)
- If there are proper nouns or technical terms, keep them appropriate for the target language context"""  # noqa
        else:
            system_prompt = f"""You are a professional translator. First, detect the source language of the following text, then translate it to {target_lang}.
Requirements:
- Provide only the translated text, without any additional comments or explanations
- Maintain the original meaning and tone
- Use natural, fluent language in the target language
- Preserve formatting if present (like line breaks, bullet points, etc.)
- If there are proper nouns or technical terms, keep them appropriate for the target language context"""  # noqa

        # Prepare the message for Claude
        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": text}]
        }]

        payload = {
            "model": model.value if isinstance(model, Enum) else model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": messages,
            "system": system_prompt
        }

        # Make a stateless call to Claude
        async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
            response.raise_for_status()
            result = await response.json()

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_claude(
            response=result,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
            tool_calls=[]
        )

        return ai_message


    # Additional helper methods you might want to add

    async def extract_key_points(
        self,
        text: str,
        num_points: int = 5,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        temperature: Optional[float] = 0.3,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Extract key points from a given text.

        Args:
            text (str): The text content to analyze.
            num_points (int): The number of key points to extract.
            model (Union[ClaudeModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        turn_id = str(uuid.uuid4())

        system_prompt = f"""Extract the {num_points} most important key points from the following text.
Requirements:
- Present each point as a clear, concise bullet point
- Focus on the main ideas and significant information
- Each point should be self-contained and meaningful
- Order points by importance (most important first)
- Use bullet points (•) to format the list"""

        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": text}]
        }]

        payload = {
            "model": model.value if isinstance(model, Enum) else model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": messages,
            "system": system_prompt
        }

        async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
            response.raise_for_status()
            result = await response.json()

        return AIMessageFactory.from_claude(
            response=result,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
            tool_calls=[]
        )


    async def analyze_sentiment(
        self,
        text: str,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_structured: bool = False,
    ) -> AIMessage:
        """
        Analyze the sentiment of a given text.

        Args:
            text (str): The text content to analyze.
            model (Union[ClaudeModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        turn_id = str(uuid.uuid4())
        if use_structured:
            system_prompt = """You are a sentiment analysis expert.
Analyze the sentiment of the given text and respond with valid JSON matching this exact schema:
{
  "sentiment": "positive" | "negative" | "neutral" | "mixed",
  "confidence_level": 0.0-1.0,
  "emotional_indicators": ["word1", "phrase2", ...],
  "reason": "explanation of analysis"
}
Respond only with valid JSON, no additional text."""
        else:
            system_prompt = """
Analyze the sentiment of the following text and provide a structured response.
Your response should include:
1. Overall sentiment (Positive, Negative, Neutral, or Mixed)
2. Confidence level (High, Medium, Low)
3. Key emotional indicators found in the text
4. Brief explanation of your analysis
Format your response clearly with these sections.
            """

        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": text}]
        }]

        payload = {
            "model": model.value if isinstance(model, Enum) else model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": messages,
            "system": system_prompt
        }

        async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
            response.raise_for_status()
            result = await response.json()

        structured_output = SentimentAnalysis if use_structured else None
        return AIMessageFactory.from_claude(
            response=result,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=structured_output,
            tool_calls=[]
        )

    async def analyze_product_review(
        self,
        review_text: str,
        product_id: str,
        product_name: str,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Analyze a product review and extract structured information.

        Args:
            review_text (str): The product review text to analyze.
            product_id (str): Unique identifier for the product.
            product_name (str): Name of the product being reviewed.
            model (Union[ClaudeModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        turn_id = str(uuid.uuid4())

        system_prompt = f"""You are a product review analysis expert. Analyze the given product review and respond with valid JSON matching this exact schema:

    {{
    "product_id": "{product_id}",
    "product_name": "{product_name}",
    "review_text": "original review text",
    "rating": 0.0-5.0,
    "sentiment": "positive" | "negative" | "neutral",
    "key_features": ["feature1", "feature2", ...]
    }}

    Extract the rating based on the review content (estimate if not explicitly stated), determine sentiment, and identify key product features mentioned. Respond only with valid JSON, no additional text."""

        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": f"Product ID: {product_id}\nProduct Name: {product_name}\nReview: {review_text}"}]
        }]

        payload = {
            "model": model.value if isinstance(model, Enum) else model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": messages,
            "system": system_prompt
        }

        async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
            response.raise_for_status()
            result = await response.json()

        return AIMessageFactory.from_claude(
            response=result,
            input_text=review_text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=ProductReview,
            tool_calls=[]
        )
