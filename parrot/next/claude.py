import asyncio
import json
from typing import AsyncIterator, Dict, List, Optional, Union, Any
import base64
import io
import time
from enum import Enum
import uuid
from pathlib import Path
import mimetypes
from PIL import Image
from pydantic import BaseModel, Field
from typing import List as TypingList
from navconfig import config
from datamodel.exceptions import ParserError  # pylint: disable=E0611 # noqa
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from .abstract import AbstractClient, MessageResponse, BatchRequest
from .models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    CompletionUsage,
    OutputFormat,
    StructuredOutputConfig,
    ObjectDetectionResult
)

class ClaudeModel(Enum):
    """Enum for Claude models."""
    SONNET_4 = "claude-sonnet-4-20250514"
    OPUS_4 = "claude-opus-4-20241022"
    SONNET_3_5 = "claude-3-5-sonnet-20241022"
    HAIKU_3_5 = "claude-3-5-haiku-20241022"


class ClaudeClient(AbstractClient):
    """Client for interacting with the Claude API."""
    version: str = "2023-06-01"
    agent_type: str = "claude"

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
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Optional[type] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AIMessage:
        """Ask Claude a question with optional conversation memory."""
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")


        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt)

        if isinstance(structured_output, StructuredOutputConfig):
            output_config = structured_output
        else:
            # Backward compatibility - assume JSON
            output_config = StructuredOutputConfig(
                output_type=structured_output,
                format=OutputFormat.JSON
            ) if structured_output else None

        payload = {
            "model": model.value if isinstance(model, Enum) else model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages
        }

        if system_prompt:
            payload["system"] = system_prompt

        if self.tools:
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
            text_content = ""
            for content_block in result["content"]:
                if content_block["type"] == "text":
                    text_content += content_block["text"]


        if structured_output:
            try:
                final_output = await self._parse_structured_output(
                    text_content,
                    output_config
                )
            except Exception:
                final_output = text_content

        # Update conversation memory
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt
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
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Stream Claude's response using AsyncIterator with optional conversation memory."""
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        payload = {
            "model": model.value if isinstance(model, Enum) else model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
            "stream": True
        }

        if system_prompt:
            payload["system"] = system_prompt

        if self.tools:
            payload["tools"] = self._prepare_tools()

        assistant_content = ""
        async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
            response.raise_for_status()

            async for line in response.content:
                line = line.decode('utf-8').strip()
                if line.startswith('data: '):
                    data = line[6:]
                    if data == '[DONE]':
                        break
                    try:
                        event = json_decoder(data)
                        if event.get('type') == 'content_block_delta':
                            delta = event.get('delta', {})
                            if delta.get('type') == 'text_delta':
                                text_chunk = delta.get('text', '')
                                assistant_content += text_chunk
                                yield text_chunk
                    except (ParserError, json.JSONDecodeError):
                        continue

        # Update conversation memory
        if assistant_content:
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": assistant_content}]
            })
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages,
                system_prompt
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
                                input_text="Batch request",  # We don't have original prompt in batch
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
        max_tokens: int = 4096,
        temperature: float = 0.1,
        structured_output: Union[type, StructuredOutputConfig] = None,
        count_objects: bool = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Ask Claude a question about an image with optional conversation memory.

        Args:
            prompt (str): The question or prompt about the image.
            image (Union[Path, bytes, Image.Image]): The primary image to analyze.
            reference_images (Optional[List[Union[Path, bytes, Image.Image]]]): Optional reference images.
            model (Union[ClaudeModel, str]): The Claude model to use.
            max_tokens (int): Maximum tokens for the response.
            temperature (float): Sampling temperature.
            structured_output (Union[type, StructuredOutputConfig]): Optional structured output format.
            count_objects (bool): Whether to count objects in the image (enables default JSON output).
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

        # Get conversation context (but don't include files since we handle images separately)
        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, None, user_id, session_id, None
        )

        if isinstance(structured_output, StructuredOutputConfig):
            output_config = structured_output
        else:
            # Backward compatibility - assume JSON
            output_config = StructuredOutputConfig(
                output_type=structured_output,
                format=OutputFormat.JSON
            ) if structured_output else None

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
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages
        }

        if system_prompt:
            payload["system"] = system_prompt


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
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt
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
            ai_message.text = final_output

        return ai_message
