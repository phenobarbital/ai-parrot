from typing import AsyncIterator, Dict, List, Optional, Union, Any
import base64
import io
import json
import mimetypes
import uuid
from pathlib import Path
import time
from logging import getLogger
from enum import Enum
from PIL import Image
from datamodel.parsers.json import json_decoder  # pylint: disable=E0611 # noqa
from navconfig import config
from tenacity import (
    AsyncRetrying,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from openai import AsyncOpenAI
from openai import APIConnectionError, RateLimitError, APIError
from .abstract import AbstractClient
from ..models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    CompletionUsage
)
from ..models.openai import OpenAIModel


getLogger('httpx').setLevel('WARNING')
getLogger('httpcore').setLevel('WARNING')
getLogger('openai').setLevel('INFO')


class OpenAIClient(AbstractClient):
    """Client for interacting with OpenAI's API."""

    agent_type: str = "openai"
    model: str = OpenAIModel.GPT4_TURBO.value

    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://api.openai.com/v1",
        **kwargs
    ):
        self.api_key = api_key or config.get('OPENAI_API_KEY')
        self.base_url = base_url
        self.base_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        super().__init__(**kwargs)
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=base_url,
            timeout=config.get('OPENAI_TIMEOUT', 60),
        )

    async def __aenter__(self):
        """Initialize the client context."""
        # OpenAI client doesn't need explicit session management like aiohttp
        return self

    async def _upload_file(
        self,
        file_path: Union[str, Path],
        purpose: str = 'fine-tune'
    ) -> None:
        """Upload a file to OpenAI."""
        with open(file_path, 'rb') as file:
            await self.client.files.create(
                file=file,
                purpose=purpose
            )

    async def _chat_completion(self, model: str, messages: Any, **kwargs):
        retry_policy = AsyncRetrying(
            retry=retry_if_exception_type((APIConnectionError, RateLimitError, APIError)),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(5),
            reraise=True
        )
        async for attempt in retry_policy:
            with attempt:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    **kwargs
                )
                return response

    async def ask(
        self,
        prompt: str,
        model: Union[str, OpenAIModel] = OpenAIModel.GPT4_TURBO,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Optional[type] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AIMessage:
        """Ask OpenAI a question with optional conversation memory."""

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        # Extract model value if it's an enum
        model_str = model.value if isinstance(model, Enum) else model

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # Upload files if they are path-like objects
        if files:
            for file in files:
                if isinstance(file, str):
                    file = Path(file)
                if isinstance(file, Path):
                    await self._upload_file(file)

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Track tool calls for the response
        all_tool_calls = []

        # Prepare tools and special arguments
        tools = self._prepare_tools() if self.tools else None
        args = {}

        # Handle search models
        if model in [OpenAIModel.GPT_4O_MINI_SEARCH, OpenAIModel.GPT_4O_SEARCH]:
            args['web_search_options'] = {
                "web_search": True,
                "web_search_model": "gpt-4o-mini"
            }

        if tools:
            args['tools'] = tools
            args['tool_choice'] = "auto"
            args['parallel_tool_calls'] = True

        # Add structured output if specified
        if structured_output:
            if hasattr(structured_output, 'model_json_schema'):
                args['response_format'] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": structured_output.__name__.lower(),
                        "schema": structured_output.model_json_schema()
                    }
                }

        # Make initial request
        response = await self._chat_completion(
            model=model_str,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature or self.temperature,
            stream=False,
            **args
        )

        result = response.choices[0].message

        # Handle tool calls in a loop
        while result.tool_calls:
            messages.append({
                "role": "assistant",
                "content": result.content,
                "tool_calls": [
                    tc.model_dump() for tc in result.tool_calls
                ]
            })
            # Process and add tool results
            for tool_call in result.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = self._json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = json_decoder(tool_call.function.arguments)

                # Create ToolCall object and execute
                tc = ToolCall(
                    id=tool_call.id,
                    name=tool_name,
                    arguments=tool_args
                )

                try:
                    start_time = time.time()
                    tool_result = await self._execute_tool(tool_name, tool_args)
                    execution_time = time.time() - start_time

                    tc.result = tool_result
                    tc.execution_time = execution_time

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": str(tool_result)
                    })
                except Exception as e:
                    tc.error = str(e)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": str(e)
                    })

                all_tool_calls.append(tc)

            # Continue conversation with tool results
            response = await self._chat_completion(
                model=model_str,
                messages=messages,
                max_tokens=max_tokens or self.max_tokens,
                temperature=temperature or self.temperature,
                stream=False,
                **args
            )
            result = response.choices[0].message

        # Add final assistant message
        messages.append({
            "role": "assistant",
            "content": result.content
        })

        # Handle structured output
        final_output = None
        if structured_output:
            try:
                if hasattr(structured_output, 'model_validate_json'):
                    final_output = structured_output.model_validate_json(result.content)
                elif hasattr(structured_output, 'model_validate'):
                    parsed_json = self._json.loads(result.content)
                    final_output = structured_output.model_validate(parsed_json)
                else:
                    final_output = self._json.loads(result.content)
            except Exception:
                final_output = result.content


        # Update conversation memory
        tools_used = [tc.name for tc in all_tool_calls]
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt,
            turn_id,
            original_prompt,
            str(final_output) if final_output else None,
            tools_used
        )

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_openai(
            response=response,
            input_text=original_prompt,
            model=model_str,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != result.content else None
        )

        # Add tool calls to the response
        ai_message.tool_calls = all_tool_calls

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: Union[str, OpenAIModel] = OpenAIModel.GPT4_TURBO,
        max_tokens: int = None,
        temperature: float = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Stream OpenAI's response with optional conversation memory."""

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())

        # Extract model value if it's an enum
        model_str = model.value if isinstance(model, Enum) else model

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # Upload files if they are path-like objects
        if files:
            for file in files:
                if isinstance(file, str):
                    file = Path(file)
                if isinstance(file, Path):
                    await self._upload_file(file)

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Prepare tools (Note: streaming with tools is more complex)
        tools = self._prepare_tools() if self.tools else None
        args = {}

        if tools:
            args['tools'] = tools
            args['tool_choice'] = "auto"

        # Create streaming response
        response_stream = await self.client.chat.completions.create(
            model=model_str,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature or self.temperature,
            stream=True,
            **args
        )

        assistant_content = ""
        async for chunk in response_stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                text_chunk = chunk.choices[0].delta.content
                assistant_content += text_chunk
                yield text_chunk

        # Update conversation memory if content was generated
        if assistant_content:
            messages.append({
                "role": "assistant",
                "content": assistant_content
            })
            # Update conversation memory
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages,
                system_prompt,
                turn_id,
                prompt,
                assistant_content,
                []
            )

    async def batch_ask(self, requests) -> List[AIMessage]:
        """Process multiple requests in batch."""
        # OpenAI doesn't have a native batch API like Claude, so we process sequentially
        # In a real implementation, you might want to use asyncio.gather for concurrency
        results = []
        for request in requests:
            result = await self.ask(**request)
            results.append(result)
        return results

    def _encode_image_for_openai(self, image: Union[Path, bytes, Image.Image]) -> Dict[str, Any]:
        """Encode image for OpenAI's vision API."""
        if isinstance(image, Path):
            if not image.exists():
                raise FileNotFoundError(f"Image file not found: {image}")
            mime_type, _ = mimetypes.guess_type(str(image))
            mime_type = mime_type or "image/jpeg"
            with open(image, "rb") as f:
                encoded_data = base64.b64encode(f.read()).decode('utf-8')

        elif isinstance(image, bytes):
            mime_type = "image/jpeg"
            encoded_data = base64.b64encode(image).decode('utf-8')

        elif isinstance(image, Image.Image):
            buffer = io.BytesIO()
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGB")
            image.save(buffer, format="JPEG")
            encoded_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
            mime_type = "image/jpeg"

        else:
            raise ValueError("Image must be a Path, bytes, or PIL.Image object.")

        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{encoded_data}"}
        }

    async def ask_to_image(
        self,
        prompt: str,
        image: Union[Path, bytes, Image.Image],
        reference_images: Optional[List[Union[Path, bytes, Image.Image]]] = None,
        model: str = "gpt-4-turbo",
        max_tokens: int = None,
        temperature: float = None,
        structured_output: Optional[type] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """Ask OpenAI a question about an image with optional conversation memory."""
        turn_id = str(uuid.uuid4())

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, None, user_id, session_id, None
        )

        content = [{"type": "text", "text": prompt}]

        primary_image_content = self._encode_image_for_openai(image)
        content.insert(0, primary_image_content)

        if reference_images:
            for ref_image in reference_images:
                ref_image_content = self._encode_image_for_openai(ref_image)
                content.insert(0, ref_image_content)

        new_message = {"role": "user", "content": content}

        if messages and messages[-1]["role"] == "user":
            messages[-1] = new_message
        else:
            messages.append(new_message)

        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature or self.temperature,
        )

        result = response.choices[0].message

        final_output = None
        if structured_output:
            try:
                final_output = structured_output.model_validate_json(result.content)
            except Exception:
                final_output = result.content

        assistant_message = {
            "role": "assistant", "content": [{"type": "text", "text": result.content}]
        }
        messages.append(assistant_message)

        # Extract assistant response text for conversation memory
        assistant_response_text = ""
        for content_block in result.get("content", []):
            if content_block.get("type") == "text":
                assistant_response_text += content_block.get("text", "")

        # Update conversation memory
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt,
            turn_id,
            prompt,
            assistant_response_text,
            []
        )

        usage = response.usage.model_dump() if response.usage else {}

        ai_message = AIMessageFactory.from_openai(
            response=result.model_dump(),
            input_text=f"[Image Analysis]: {prompt}",
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output
        )

        ai_message.usage = CompletionUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            extra_usage=usage
        )

        ai_message.provider = "openai"

        return ai_message
