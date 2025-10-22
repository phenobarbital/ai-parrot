from typing import AsyncIterator, Dict, List, Optional, Union, Any, Tuple, Iterable
import base64
import io
import json
import mimetypes
import uuid
from pathlib import Path
import time
import asyncio
from logging import getLogger
from enum import Enum
from PIL import Image
import pytesseract
from pydantic import BaseModel, ValidationError
from datamodel.parsers.json import json_decoder, json_decoder  # pylint: disable=E0611 # noqa
from navconfig import config, BASE_DIR
from tenacity import (
    AsyncRetrying,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from openai import AsyncOpenAI
from openai import APIConnectionError, RateLimitError, APIError
from .base import AbstractClient
from ..models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    CompletionUsage,
    VideoGenerationPrompt
)
from ..models.openai import OpenAIModel
from ..models.outputs import (
    SentimentAnalysis,
    ProductReview
)
from ..models.detections import (
    DetectionBox,
    ShelfRegion,
    IdentifiedProduct
)


getLogger('httpx').setLevel('WARNING')
getLogger('httpcore').setLevel('WARNING')
getLogger('openai').setLevel('INFO')

# Reasoning models like o3 / o3-pro / o3-mini and o4-mini
# (including deep-research variants) are Responses-only.
RESPONSES_ONLY_MODELS = {
    "o3",
    "o3-pro",
    "o3-mini",
    "o3-deep-research",
    "o4-mini",
    "o4-mini-deep-research",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-5-pro"
}


class OpenAIClient(AbstractClient):
    """Client for interacting with OpenAI's API."""

    client_type: str = "openai"
    model: str = OpenAIModel.GPT4_TURBO.value
    client_name: str = "openai"

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

    async def _download_openai_file(self, file_id: str) -> Optional[bytes]:
        """Download a file from OpenAI's Files API handling various SDK shapes."""
        if not file_id:
            return None

        files_resource = getattr(self.client, "files", None)
        if files_resource is None:
            return None

        candidate_methods = [
            getattr(files_resource, "content", None),
            getattr(files_resource, "retrieve_content", None),
            getattr(files_resource, "download", None),
        ]

        async def _invoke(method, *args, **kwargs):
            if asyncio.iscoroutinefunction(method):
                return await method(*args, **kwargs)
            result = method(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            return result

        arg_permutations = [
            ((file_id,), {}),
            (tuple(), {"id": file_id}),
            (tuple(), {"file_id": file_id}),
            (tuple(), {"file": file_id}),
        ]

        for method in candidate_methods:
            if method is None:
                continue

            result = None
            for args, kwargs in arg_permutations:
                try:
                    result = await _invoke(method, *args, **kwargs)
                    break
                except TypeError:
                    continue
                except Exception:  # pylint: disable=broad-except
                    result = None
                    continue

            if result is None:
                continue

            if isinstance(result, bytes):
                return result

            if isinstance(result, dict):
                if isinstance(result.get("data"), bytes):
                    return result["data"]
                if isinstance(result.get("content"), bytes):
                    return result["content"]

            if hasattr(result, "content"):
                content = result.content
                if asyncio.iscoroutine(content):
                    content = await content
                if isinstance(content, bytes):
                    return content

            if hasattr(result, "read"):
                read_method = result.read
                data = await read_method() if asyncio.iscoroutinefunction(read_method) else read_method()
                if isinstance(data, bytes):
                    return data

            if hasattr(result, "body") and hasattr(result.body, "read"):
                read_method = result.body.read
                data = await read_method() if asyncio.iscoroutinefunction(read_method) else read_method()
                if isinstance(data, bytes):
                    return data

        return None

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
                return await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    **kwargs
                )

    def _is_responses_model(self, model_str: str) -> bool:
        """Return True if the selected model must go through Responses API."""
        # allow aliases/enums already normalized to str
        ms = (model_str or "").strip()
        return ms in RESPONSES_ONLY_MODELS


    def _prepare_responses_args(self, *, messages, args):
        """
        Map your existing args/messages into Responses API fields.

        - Lift the first system message into `instructions` when present
        - Keep the rest as chat-style list under `input`
        - Pass tools/response_format/temperature/max_output_tokens if provided
        """

        def _as_response_content(role: str, content: Any, message: Dict[str, Any]) -> List[Dict[str, Any]]:
            """Translate chat `content` into Responses-style content blocks."""

            def _normalize_text(text_value: Any, *, text_type: str) -> Optional[Dict[str, Any]]:
                if text_value is None:
                    return None
                text = text_value if isinstance(text_value, str) else str(text_value)
                if not text:
                    return None
                return {"type": text_type, "text": text}

            if role == "tool":
                tool_call_id = message.get("tool_call_id")
                # Responses expects tool output blocks
                if isinstance(content, list):
                    normalized_output = "\n".join(
                        str(part) if not isinstance(part, dict) else str(part.get("text") or part.get("output") or "")
                        for part in content
                    )
                else:
                    normalized_output = "" if content is None else str(content)

                block = {
                    "type": "tool_output",
                    "tool_call_id": tool_call_id,
                    "output": normalized_output,
                }
                if message.get("name"):
                    block["name"] = message["name"]
                return [block]

            text_type = "input_text" if role in {"user", "tool_user"} else "output_text"

            parts: List[Dict[str, Any]] = []

            def _append_text(value: Any):
                block = _normalize_text(value, text_type=text_type)
                if block:
                    parts.append(block)

            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        item_type = item.get("type")

                        if item_type in {
                            "input_text",
                            "output_text",
                            "input_image",
                            "input_audio",
                            "tool_output",
                            "tool_call",
                            "input_file",
                            "computer_screenshot",
                            "summary_text",
                        }:
                            parts.append(item)
                            continue

                        if item_type == "text":
                            _append_text(item.get("text"))
                            continue

                        if item_type is None and {"id", "function"}.issubset(item.keys()):
                            parts.append(
                                {
                                    "type": "tool_call",
                                    "id": item.get("id"),
                                    "name": (item.get("function") or {}).get("name"),
                                    "arguments": (item.get("function") or {}).get("arguments"),
                                }
                            )
                            continue

                        parts.append(item)
                    else:
                        _append_text(item)
            else:
                _append_text(content)

            if role == "assistant" and message.get("tool_calls"):
                for tool_call in message["tool_calls"]:
                    if isinstance(tool_call, dict):
                        parts.append(
                            {
                                "type": "tool_call",
                                "id": tool_call.get("id"),
                                "name": (tool_call.get("function") or {}).get("name"),
                                "arguments": (tool_call.get("function") or {}).get("arguments"),
                            }
                        )

            return parts

        instructions = None
        input_msgs = []
        for m in messages:
            role = m.get("role")
            if role == "system" and instructions is None:
                sys_content = m.get("content")
                if isinstance(sys_content, list):
                    instructions = " ".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in sys_content
                    ).strip()
                else:
                    instructions = sys_content
                continue

            content_blocks = _as_response_content(role, m.get("content"), m)
            msg_payload: Dict[str, Any] = {"role": role, "content": content_blocks}

            if m.get("tool_calls"):
                msg_payload["tool_calls"] = m["tool_calls"]
            if m.get("tool_call_id"):
                msg_payload["tool_call_id"] = m["tool_call_id"]
            if m.get("name"):
                msg_payload["name"] = m["name"]

            input_msgs.append(msg_payload)

        req = {
            "instructions": instructions,
            "input": input_msgs,
        }

        if "tools" in args:
            req["tools"] = args["tools"]
        if "tool_choice" in args:
            req["tool_choice"] = args["tool_choice"]
        if "response_format" in args:
            req["response_format"] = args["response_format"]
        if "temperature" in args and args["temperature"] is not None:
            req["temperature"] = args["temperature"]
        if "max_tokens" in args and args["max_tokens"] is not None:
            req["max_output_tokens"] = args["max_tokens"]
        if "parallel_tool_calls" in args:
            req["parallel_tool_calls"] = args["parallel_tool_calls"]
        return req

    async def _responses_completion(self, *, model: str, messages, **args):
        """
        Adapter around OpenAI Responses API that mimics Chat Completions:
        returns an object with `.choices[0].message` where `message` has
        `.content: str` and `.tool_calls: list` (each item has `.id` and `.function.{name,arguments}`).
        """
        # 1) Build request payload from chat-like messages/args
        req = self._prepare_responses_args(messages=messages, args=args)
        req["model"] = model

        # 2) Call Responses API
        resp = await self.client.responses.create(**req)

        # 3) Extract best-effort text
        output_text = getattr(resp, "output_text", None)
        if output_text is None:
            output_text = ""
            for item in getattr(resp, "output", []) or []:
                for part in getattr(item, "content", []) or []:
                    # common shapes the SDK returns
                    if isinstance(part, dict):
                        if part.get("type") == "output_text":
                            output_text += part.get("text", "") or ""
                    elif (text := getattr(part, "text", None)):
                            output_text += text

        # 4) Extract & normalize tool calls
        #    We shape them to look like Chat Completions tool_calls:
        #    {"id":..., "function": {"name": ..., "arguments": "<json string>"}}
        norm_tool_calls = []
        for item in getattr(resp, "output", []) or []:
            for part in getattr(item, "content", []) or []:
                if isinstance(part, dict) and part.get("type") == "tool_call":
                    _id = part.get("id") or part.get("tool_call_id") or str(uuid.uuid4())
                    _name = part.get("name")
                    _args = part.get("arguments", {})
                    # ensure arguments is a JSON string (Chat-style)
                    if not isinstance(_args, str):
                        try:
                            _args = self._json.dumps(_args)
                        except Exception:
                            _args = json.dumps(_args, default=str)

                    # tiny compatibility holders
                    class _Fn:
                        def __init__(self, name, arguments):
                            self.name = name
                            self.arguments = arguments
                    class _ToolCall:
                        def __init__(self, id, function):
                            self.id = id
                            self.function = function

                    norm_tool_calls.append(_ToolCall(_id, _Fn(_name, _args)))

        # 5) Build a Chat-like container
        class _Msg:
            def __init__(self, content, tool_calls):
                self.content = content
                self.tool_calls = tool_calls

        class _Choice:
            def __init__(self, message):
                self.message = message

        class _CompatResp:
            def __init__(self, raw, message):
                self.raw = raw
                self.choices = [_Choice(message)]
                # Usage may or may not exist; keep attribute for downstream code
                self.usage = getattr(raw, "usage", None)

        message = _Msg(output_text or "", norm_tool_calls)
        return _CompatResp(resp, message)

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
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None
    ) -> AIMessage:
        """Ask OpenAI a question with optional conversation memory.

        Args:
            prompt (str): The prompt to send to the model.
            model (Union[str, OpenAIModel], optional): The model to use. Defaults to GPT4_TURBO.
            max_tokens (Optional[int], optional): Maximum tokens for the response. Defaults to None.
            temperature (Optional[float], optional): Sampling temperature. Defaults to None.
            files (Optional[List[Union[str, Path]]], optional): Files to upload. Defaults to None.
            system_prompt (Optional[str], optional): System prompt to prepend. Defaults to None.
            structured_output (Optional[type], optional): Pydantic model for structured output. Defaults to None.
            user_id (Optional[str], optional): User ID for conversation memory. Defaults to None.
            session_id (Optional[str], optional): Session ID for conversation memory. Defaults to None.
            tools (Optional[List[Dict[str, Any]]], optional): Tools to register for this call. Defaults to None.
            use_tools (Optional[bool], optional): Whether to use tools. Defaults to None.

        Returns:
            AIMessage: The response from the model.

        """

        turn_id = str(uuid.uuid4())
        original_prompt = prompt
        _use_tools = use_tools if use_tools is not None else self.enable_tools

        model_str = model.value if isinstance(model, Enum) else model

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        if files:
            for file in files:
                if isinstance(file, str):
                    file = Path(file)
                if isinstance(file, Path):
                    await self._upload_file(file)

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        all_tool_calls = []

        # tools prep
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)
        tools = self._prepare_tools() if (_use_tools) else None

        args = {}
        if model in [OpenAIModel.GPT_4O_MINI_SEARCH, OpenAIModel.GPT_4O_SEARCH]:
            args['web_search_options'] = {
                "web_search": True,
                "web_search_model": "gpt-4o-mini"
            }

        if tools:
            args['tools'] = tools
            args['tool_choice'] = "auto"
            args['parallel_tool_calls'] = True

        if structured_output and hasattr(structured_output, 'model_json_schema'):
            args['response_format'] = {
                "type": "json_schema",
                "json_schema": {
                    "name": structured_output.__name__.lower(),
                    "schema": structured_output.model_json_schema()
                }
            }

        if model_str != 'gpt-5-nano':
            args['max_tokens'] = max_tokens or self.max_tokens
        if temperature:
            args['temperature'] = temperature

        # -------- ROUTING: Responses-only vs Chat -----------
        use_responses = self._is_responses_model(model_str)

        if use_responses:
            response = await self._responses_completion(
                model=model_str,
                messages=messages,
                **args
            )
        else:
            response = await self._chat_completion(
                model=model_str,
                messages=messages,
                stream=False,
                **args
            )

        result = response.choices[0].message

        # ---------- Tool loop (works for both paths) ----------
        while getattr(result, "tool_calls", None):
            messages.append({
                "role": "assistant",
                "content": result.content,
                "tool_calls": [
                    tc.model_dump() if hasattr(tc, "model_dump") else {
                        "id": tc.id,
                        "function": {
                            "name": getattr(tc.function, "name", None),
                            "arguments": getattr(tc.function, "arguments", "{}"),
                        },
                    }
                    for tc in result.tool_calls
                ]
            })

            for tool_call in result.tool_calls:
                tool_name = tool_call.function.name
                try:
                    try:
                        tool_args = self._json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = json_decoder(tool_call.function.arguments)

                    tc = ToolCall(
                        id=getattr(tool_call, "id", ""),
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
                            "tool_call_id": getattr(tool_call, "id", ""),
                            "name": tool_name,
                            "content": str(tool_result)
                        })
                    except Exception as e:
                        tc.error = str(e)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": getattr(tool_call, "id", ""),
                            "name": tool_name,
                            "content": str(e)
                        })

                    all_tool_calls.append(tc)

                except Exception as e:
                    all_tool_calls.append(ToolCall(
                        id=getattr(tool_call, "id", ""),
                        name=tool_name,
                        arguments={"_error": f"malformed tool args: {e}"}
                    ))
                    messages.append({
                        "role": "tool",
                        "tool_call_id": getattr(tool_call, "id", ""),
                        "name": tool_name,
                        "content": f"Error decoding arguments: {e}"
                    })

            # continue via the same routed API
            if use_responses:
                response = await self._responses_completion(
                    model=model_str,
                    messages=messages,
                    **args
                )
            else:
                response = await self._chat_completion(
                    model=model_str,
                    messages=messages,
                    stream=False,
                    **args
                )
            result = response.choices[0].message

        # ---------- Finalization (unchanged) ----------
        messages.append({"role": "assistant", "content": result.content})

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

        tools_used = [tc.name for tc in all_tool_calls]
        assistant_response_text = result.content if isinstance(result.content, str) else self._json.dumps(result.content)
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt,
            turn_id,
            original_prompt,
            assistant_response_text,
            tools_used
        )

        ai_message = AIMessageFactory.from_openai(
            response=response,
            input_text=original_prompt,
            model=model_str,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != result.content else None
        )

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
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None
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
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)
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

    def _encode_image_for_openai(
        self,
        image: Union[Path, bytes, Image.Image],
        low_quality: bool = False
    ) -> Dict[str, Any]:
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
            "image_url": {
                "url": f"data:{mime_type};base64,{encoded_data}",
                "detail": "low" if low_quality else "auto"
            }
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
        no_memory: bool = False,
        low_quality: bool = False
    ) -> AIMessage:
        """Ask OpenAI a question about an image with optional conversation memory."""
        turn_id = str(uuid.uuid4())

        if no_memory:
            messages = []
            conversation_session = None
            system_prompt = None
        else:
            messages, conversation_session, system_prompt = await self._prepare_conversation_context(
                prompt, None, user_id, session_id, None
            )

        content = [{"type": "text", "text": prompt}]

        primary_image_content = self._encode_image_for_openai(image, low_quality=low_quality)
        content.insert(0, primary_image_content)

        if reference_images:
            for ref_image in reference_images:
                ref_image_content = self._encode_image_for_openai(ref_image, low_quality=low_quality)
                content.insert(0, ref_image_content)

        new_message = {"role": "user", "content": content}

        if messages and messages[-1]["role"] == "user":
            messages[-1] = new_message
        else:
            messages.append(new_message)

        response_format = None
        if structured_output:
            if hasattr(structured_output, 'model_json_schema'):
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": structured_output.__name__.lower(),
                        "schema": structured_output.model_json_schema()
                    }
                }
            elif isinstance(structured_output, dict):
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "response",
                        "schema": structured_output
                    }
                }
        else:
            response_format = {"type": "json_object"}

        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature or self.temperature,
            response_format=response_format
        )

        result = response.choices[0].message

        final_output = None
        assistant_response_text = ""
        if structured_output is not None:
            if isinstance(structured_output, dict):
                assistant_response_text = result.content
                try:
                    final_output = self._parse_json_from_text(assistant_response_text)
                except Exception:
                    final_output = assistant_response_text
            else:
                try:
                    final_output = structured_output.model_validate_json(result.content)
                except Exception:
                    try:
                        final_output = structured_output.model_validate(result.content)
                    except ValidationError:
                        final_output = result.content

        assistant_message = {
            "role": "assistant", "content": [{"type": "text", "text": result.content}]
        }
        messages.append(assistant_message)

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
            response=response,
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

    async def summarize_text(
        self,
        text: str,
        max_length: int = 500,
        min_length: int = 100,
        model: Union[OpenAIModel, str] = OpenAIModel.GPT4_TURBO,
        temperature: Optional[float] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Generate a concise summary of *text* (single paragraph, stateless).
        """
        turn_id = str(uuid.uuid4())

        system_prompt = (
            "Your job is to produce a final summary from the following text and "
            "identify the main theme.\n"
            f"- The summary should be concise and to the point.\n"
            f"- The summary should be no longer than {max_length} characters and "
            f"no less than {min_length} characters.\n"
            "- The summary should be in a single paragraph.\n"
            "- Focus on the key information and main points.\n"
            "- Write in clear, accessible language."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

        response = await self._chat_completion(
            model=model.value if isinstance(model, Enum) else model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=temperature or self.temperature,
        )

        result = response.choices[0].message

        return AIMessageFactory.from_openai(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
        )

    async def translate_text(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        model: Union[OpenAIModel, str] = OpenAIModel.GPT4_TURBO,
        temperature: float = 0.2,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Translate *text* from *source_lang* (auto‑detected if None) into *target_lang*.
        """
        turn_id = str(uuid.uuid4())

        if source_lang:
            system_prompt = (
                f"You are a professional translator. Translate the following text "
                f"from {source_lang} to {target_lang}.\n"
                "- Provide only the translated text, without any additional comments "
                "or explanations.\n"
                "- Maintain the original meaning and tone.\n"
                "- Use natural, fluent language in the target language.\n"
                "- Preserve formatting if present (line breaks, bullet points, etc.)."
            )
        else:
            system_prompt = (
                f"You are a professional translator. First detect the source "
                f"language of the following text, then translate it to {target_lang}.\n"
                "- Provide only the translated text, without any additional comments "
                "or explanations.\n"
                "- Maintain the original meaning and tone.\n"
                "- Use natural, fluent language in the target language.\n"
                "- Preserve formatting if present (line breaks, bullet points, etc.)."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

        response = await self._chat_completion(
            model=model.value if isinstance(model, Enum) else model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=temperature,
        )

        return AIMessageFactory.from_openai(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
        )

    async def extract_key_points(
        self,
        text: str,
        num_points: int = 5,
        model: Union[OpenAIModel, str] = OpenAIModel.GPT4_TURBO,
        temperature: float = 0.3,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Extract *num_points* bullet‑point key ideas from *text* (stateless).
        """
        turn_id = str(uuid.uuid4())

        system_prompt = (
            f"Extract the {num_points} most important key points from the following text.\n"
            "- Present each point as a clear, concise bullet point (•).\n"
            "- Focus on the main ideas and significant information.\n"
            "- Each point should be self‑contained and meaningful.\n"
            "- Order points by importance (most important first)."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

        response = await self._chat_completion(
            model=model.value if isinstance(model, Enum) else model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=temperature,
        )

        return AIMessageFactory.from_openai(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
        )

    async def analyze_sentiment(
        self,
        text: str,
        model: Union[OpenAIModel, str] = OpenAIModel.GPT4_TURBO,
        temperature: float = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Perform sentiment analysis on *text* and return a structured explanation.
        """
        turn_id = str(uuid.uuid4())

        system_prompt = (
            "Analyze the sentiment of the following text and provide a structured response.\n"
            "Your response must include:\n"
            "1. Overall sentiment (Positive, Negative, Neutral, or Mixed)\n"
            "2. Confidence level (High, Medium, Low)\n"
            "3. Key emotional indicators found in the text\n"
            "4. Brief explanation of your analysis\n\n"
            "Format your answer clearly with numbered sections."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

        response = await self._chat_completion(
            model=model.value if isinstance(model, Enum) else model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=temperature,
        )

        return AIMessageFactory.from_openai(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
        )

    async def analyze_product_review(
        self,
        review_text: str,
        product_id: str,
        product_name: str,
        model: Union[OpenAIModel, str] = OpenAIModel.GPT4_TURBO,
        temperature: float = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Analyze a product review and extract structured information.

        Args:
            review_text (str): The product review text to analyze.
            product_id (str): Unique identifier for the product.
            product_name (str): Name of the product being reviewed.
            model (Union[OpenAIModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        turn_id = str(uuid.uuid4())

        system_prompt = (
            f"You are a product review analysis expert. Analyze the given product review "
            f"for '{product_name}' (ID: {product_id}) and extract structured information. "
            f"Determine the sentiment (positive, negative, or neutral), estimate a rating "
            f"based on the review content (0.0-5.0 scale), and identify key product features "
            f"mentioned in the review."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Product ID: {product_id}\nProduct Name: {product_name}\nReview: {review_text}"},
        ]

        # Use structured output with response_format
        response = await self._chat_completion(
            model=model.value if isinstance(model, Enum) else model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "product_review_analysis",
                    "schema": ProductReview.model_json_schema(),
                    "strict": True
                }
            }
        )

        return AIMessageFactory.from_openai(
            response=response,
            input_text=review_text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=ProductReview,
        )

    async def image_identification(
        self,
        *,
        image: Union[Path, bytes, Image.Image],
        detections: List[DetectionBox],          # from parrot.models.detections
        shelf_regions: List[ShelfRegion],        # "
        reference_images: Optional[List[Union[Path, bytes, Image.Image]]] = None,
        model: Union[OpenAIModel, str] = OpenAIModel.GPT_4_1_MINI,
        prompt: Optional[str] = None,
        temperature: float = 0.0,
        ocr_hints: bool = True,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_tokens: Optional[int] = None
    ) -> List[IdentifiedProduct]:
        """
        Step-2: Identify products using the detected boxes + reference images.

        Returns a list[IdentifiedProduct] with bbox, type, model, confidence, features,
        reference_match, shelf_location, and position_on_shelf.
        """
        _has_tesseract = True

        def _crop_box(pil_img: Image.Image, box) -> Image.Image:
            # small padding to include context
            pad = 6
            x1 = max(0, box.x1 - pad)
            y1 = max(0, box.y1 - pad)
            x2 = min(pil_img.width,  box.x2 + pad)
            y2 = min(pil_img.height, box.y2 + pad)
            return pil_img.crop((x1, y1, x2, y2))

        def _shelf_and_position(box, regions: List[ShelfRegion]) -> Tuple[str, str]:
            # map to shelf by containment / Y overlap
            best = None
            best_overlap = 0
            for r in regions:
                rx1, ry1, rx2, ry2 = r.bbox.x1, r.bbox.y1, r.bbox.x2, r.bbox.y2
                ix1, iy1 = max(rx1, box.x1), max(ry1, box.y1)
                ix2, iy2 = min(rx2, box.x2), min(ry2, box.y2)
                ov = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                if ov > best_overlap:
                    best_overlap, best = ov, r
            shelf = best.level if best else "unknown"

            # left/center/right inside the shelf bbox
            if best:
                mid = (box.x1 + box.x2) / 2.0
                thirds = (best.bbox.x1 + (best.bbox.x2 - best.bbox.x1) / 3.0,
                        best.bbox.x1 + 2 * (best.bbox.x2 - best.bbox.x1) / 3.0)
                position = "left" if mid < thirds[0] else ("right" if mid > thirds[1] else "center")
            else:
                position = "center"
            return shelf, position

        # --- prepare images ---
        if isinstance(image, (str, Path)):
            pil_image = Image.open(image).convert("RGB")
        elif isinstance(image, bytes):
            pil_image = Image.open(io.BytesIO(image)).convert("RGB")
        else:
            pil_image = image.convert("RGB")

        # crops per detection
        crops = []
        for i, det in enumerate(detections, start=1):
            crop = _crop_box(pil_image, det)
            text_hint = ""
            if ocr_hints and _has_tesseract:
                try:
                    text = pytesseract.image_to_string(crop)
                    text_hint = text.strip()
                except Exception:
                    text_hint = ""
            shelf, pos = _shelf_and_position(det, shelf_regions)
            crops.append({
                "id": i,
                "det": det,
                "shelf": shelf,
                "position": pos,
                "ocr": text_hint,
                "img_content": self._encode_image_for_openai(crop)
            })

        # --- build messages (full image + crops + references) ---
        # Put references first, then the full scene, then each crop.
        content_blocks = []

        # 1) reference images
        if reference_images:
            for ref in reference_images:
                content_blocks.append(self._encode_image_for_openai(ref))

        # 2) full scene
        content_blocks.append(self._encode_image_for_openai(pil_image))

        # 3) one block with per-detection crop + text hint
        #    Images go as separate blocks; the textual metadata goes in one text block.
        meta_lines = ["DETECTIONS:"]
        for c in crops:
            d = c["det"]
            meta_lines.append(
                f"- id:{c['id']} bbox:[{d.x1},{d.y1},{d.x2},{d.y2}] class:{d.class_name} "
                f"shelf:{c['shelf']} position:{c['position']} ocr:{c['ocr'][:80] or 'None'}"
            )
        if prompt:
            text_block = prompt + "\n\nReturn ONLY JSON with top-level key 'items' that matches the provided schema." + "\n".join(meta_lines)
        else:
            text_block = (
                "Identify each detection by comparing with the reference images. "
                "Prefer visual features (shape, control panel, ink tank layout) and use OCR hints only as supportive evidence. "
                "Allowed product_type: ['printer','product_box','fact_tag','promotional_graphic','ink_bottle']. "
                "Models to look for (if any): ['ET-2980','ET-3950','ET-4950']. "
                "Return one item per detection id.\n"
                + "\n".join(meta_lines)
            )
        content_blocks.append({"type": "text", "text": text_block})
        # add crops
        for c in crops:
            content_blocks.append(c["img_content"])

        # --- JSON schema (strict) for enforcement ---
        # We wrap the array in an object {"items":[...]} so json_schema works consistently.
        item_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "detection_id": {"type": "integer", "minimum": 1},
                "product_type": {"type": "string"},
                "product_model": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "visual_features": {"type": "array", "items": {"type": "string"}},
                "reference_match": {"type": ["string", "null"]},
                "shelf_location": {"type": "string"},
                "position_on_shelf": {"type": "string"},
                "brand": {"type": ["string", "null"]},
                "advertisement_type": {"type": ["string", "null"]},
            },
            "required": [
                "detection_id","product_type","product_model","confidence","visual_features",
                "reference_match","shelf_location","position_on_shelf","brand","advertisement_type"
            ],
        }
        resp_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "identified_products",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": item_schema,
                            "minItems": len(detections),   # drop or lower if this causes 400s
                        }
                    },
                    "required": ["items"],
                },
            },
        }

        # ensure shelves/positions are precomputed in case the model drops them
        shelf_pos_map = {c["id"]: (c["shelf"], c["position"]) for c in crops}

        # --- call OpenAI ---
        messages = [{"role": "user", "content": content_blocks}]
        response = await self.client.chat.completions.create(
            model=model.value if isinstance(model, Enum) else model,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature or self.temperature,
            response_format=resp_format
        )

        raw = response.choices[0].message.content or "{}"
        try:
            # data = json.loads(raw)
            data = json_decoder(raw)
            items = data.get("items") or data.get("detections") or []
        except Exception:
            # fallback: try best-effort parse if model didn’t honor schema
            data = self._json.loads(
                raw
            )
            items = data.get("items") or data.get("detections") or []

        # --- build IdentifiedProduct list ---
        out: List[IdentifiedProduct] = []
        for idx, it in enumerate(items, start=1):
            det_id = int(it.get("detection_id") or idx)
            if not (1 <= det_id <= len(detections)):
                continue

            det = detections[det_id - 1]
            shelf, pos = shelf_pos_map.get(det_id, ("unknown", "center"))

            # allow model to override if present
            shelf = (it.get("shelf_location") or shelf)
            pos = (it.get("position_on_shelf") or pos)

            # --- COERCION / DEFAULTS ---
            det_cls = det.class_name.lower()
            pt = (it.get("product_type") or "").strip().lower()
            pm = (it.get("product_model") or None)

            # Default to detector class when empty
            if not pt:
                pt = "price_tag" if det_cls in ("price_tag", "fact_tag") else det_cls

            # Shelf rule: middle/bottom should be boxes; detector box forces box
            if shelf in ("middle", "bottom") or det_cls == "product_box":
                if pt == "printer":
                    pt = "product_box"

            # Fill sensible models
            if pt in ("price_tag", "fact_tag") and not pm:
                pm = "price tag"
            if pt == "promotional_graphic" and not pm:
                # light OCR-based guess if you like; otherwise leave None
                pm = None

            out.append(
                IdentifiedProduct(
                    detection_box=det,
                    product_type=it.get("product_type", "unknown"),
                    product_model=it.get("product_model"),
                    confidence=float(it.get("confidence", 0.5)),
                    visual_features=it.get("visual_features", []),
                    reference_match=it.get("reference_match"),
                    shelf_location=shelf,
                    position_on_shelf=pos,
                    detection_id=det_id,
                    brand=it.get("brand"),
                    advertisement_type=it.get("advertisement_type"),
                )
            )
        return out

    async def generate_video(
        self,
        prompt: VideoGenerationPrompt,
        *,
        output_directory: Optional[Path] = None,
        mime_format: str = "video/mp4",
        model: Optional[Union[str, OpenAIModel]] = None,
        poll_interval: float = 5.0,
        timeout: Optional[float] = 600.0,
    ) -> AIMessage:
        """Generate a video using OpenAI's Sora or Sora 2 models."""

        if not prompt or not prompt.prompt or not prompt.prompt.strip():
            raise ValueError("Prompt text is required to generate a video with OpenAI.")

        selected_model: Union[str, OpenAIModel, None] = model or prompt.model or OpenAIModel.SORA
        if isinstance(selected_model, Enum):
            selected_model = selected_model.value
        if isinstance(selected_model, OpenAIModel):
            selected_model = selected_model.value
        if selected_model is None:
            selected_model = OpenAIModel.SORA.value

        model_name = str(selected_model).strip()
        normalized_model = model_name.lower()
        allowed_models = {
            OpenAIModel.SORA.value,
            OpenAIModel.SORA_2.value,
        }
        if normalized_model not in allowed_models:
            raise ValueError("OpenAI video generation is only supported for Sora or Sora 2 models.")

        configured_dir = config.get("OPENAI_VIDEO_OUTPUT_DIR")
        if output_directory is not None:
            output_dir_path = Path(output_directory)
        elif configured_dir:
            output_dir_path = Path(configured_dir)
        else:
            output_dir_path = BASE_DIR.joinpath("static", "generated_videos")

        video_options: Dict[str, Any] = {}
        if prompt.aspect_ratio:
            video_options["aspect_ratio"] = prompt.aspect_ratio
        if prompt.duration:
            video_options["duration"] = prompt.duration
        if prompt.negative_prompt:
            video_options["negative_prompt"] = prompt.negative_prompt
        if prompt.number_of_videos and prompt.number_of_videos > 1:
            video_options["num_videos"] = prompt.number_of_videos

        start_time = time.time()

        async def _await_video_job(job_obj: Any) -> Any:
            """Poll OpenAI until the async video job completes."""

            videos_resource = getattr(self.client, "videos", None)
            if videos_resource is None:
                return job_obj

            completed_states = {"succeeded", "completed", "ready", "finished"}
            failed_states = {"failed", "cancelled", "canceled", "error", "errored"}

            def _status(obj: Any) -> Optional[str]:
                return getattr(obj, "status", None) or getattr(obj, "state", None)

            status = _status(job_obj)
            if status in completed_states:
                return job_obj
            if status in failed_states:
                raise RuntimeError(f"OpenAI video generation failed with status '{status}'.")

            job_id = getattr(job_obj, "id", None) or getattr(job_obj, "job_id", None)
            if not job_id:
                return job_obj

            retrieve_callable = None
            for attr in ("retrieve", "get", "retrieve_job", "job"):
                candidate = getattr(videos_resource, attr, None)
                if candidate:
                    retrieve_callable = candidate
                    break

            jobs_resource = getattr(videos_resource, "jobs", None)
            if retrieve_callable is None and jobs_resource is not None:
                for attr in ("retrieve", "get"):
                    candidate = getattr(jobs_resource, attr, None)
                    if candidate:
                        retrieve_callable = candidate
                        videos_resource = jobs_resource
                        break

            if retrieve_callable is None:
                return job_obj

            deadline = (time.time() + timeout) if timeout else None

            while True:
                if deadline and time.time() > deadline:
                    raise TimeoutError("Timed out waiting for OpenAI video generation to complete.")

                await asyncio.sleep(max(0.5, poll_interval))

                try:
                    if asyncio.iscoroutinefunction(retrieve_callable):
                        refreshed = await retrieve_callable(job_id)
                    else:
                        refreshed = retrieve_callable(job_id)
                        if asyncio.iscoroutine(refreshed):
                            refreshed = await refreshed
                except TypeError:
                    kwargs = {"id": job_id}
                    try:
                        if asyncio.iscoroutinefunction(retrieve_callable):
                            refreshed = await retrieve_callable(**kwargs)
                        else:
                            refreshed = retrieve_callable(**kwargs)
                            if asyncio.iscoroutine(refreshed):
                                refreshed = await refreshed
                    except Exception as exc:  # pylint: disable=broad-except
                        self.logger.error(f"Failed to poll OpenAI video job: {exc}")
                        return job_obj

                if refreshed is None:
                    return job_obj

                status = _status(refreshed)
                if status in failed_states:
                    raise RuntimeError(f"OpenAI video generation failed with status '{status}'.")
                if status in completed_states or not status:
                    return refreshed

                job_obj = refreshed

        videos_resource = getattr(self.client, "videos", None)
        responses_resource = getattr(self.client, "responses", None)

        response_payload = {
            "model": model_name,
            "prompt": prompt.prompt,
        }
        if video_options:
            response_payload.update(video_options)

        final_response: Any

        if videos_resource and hasattr(videos_resource, "generate"):
            try:
                job_response = await videos_resource.generate(**response_payload)
            except TypeError:
                kwargs = {k: v for k, v in response_payload.items() if k not in video_options}
                extra_args = {"video": video_options} if video_options else {}
                job_response = await videos_resource.generate(**kwargs, **extra_args)
            final_response = await _await_video_job(job_response)
        else:
            if responses_resource is None or not hasattr(responses_resource, "create"):
                raise RuntimeError("OpenAI client does not provide a video generation endpoint. Please update the SDK.")

            responses_payload = {
                "model": model_name,
                "modalities": ["video"],
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt.prompt}
                        ],
                    }
                ],
            }
            if video_options:
                responses_payload["video"] = video_options

            final_response = await responses_resource.create(**responses_payload)

        video_bytes: List[bytes] = []

        def _decode_b64(value: Any) -> Optional[bytes]:
            if not isinstance(value, str):
                return None
            try:
                return base64.b64decode(value)
            except Exception:  # pylint: disable=broad-except
                return None

        async def _collect_video_bytes(node: Any) -> None:
            if node is None:
                return

            if isinstance(node, dict):
                for key in ("b64_json", "b64_mp4", "base64", "video", "data"):
                    if key in node and isinstance(node[key], str):
                        decoded = _decode_b64(node[key])
                        if decoded:
                            video_bytes.append(decoded)

                video_node = node.get("video") or node.get("output_video") or node.get("asset")
                if isinstance(video_node, dict):
                    await _collect_video_bytes(video_node)

                file_identifier = None
                if isinstance(node.get("file_id"), str):
                    file_identifier = node["file_id"]
                elif isinstance(node.get("id"), str) and node.get("mime_type", "").startswith("video"):
                    file_identifier = node["id"]
                elif isinstance(node.get("file"), str) and node.get("mime_type", "").startswith("video"):
                    file_identifier = node["file"]

                if file_identifier:
                    data = await self._download_openai_file(file_identifier)
                    if data:
                        video_bytes.append(data)

                for value in node.values():
                    await _collect_video_bytes(value)

            elif isinstance(node, list):
                for item in node:
                    await _collect_video_bytes(item)

        raw_dump: Optional[Dict[str, Any]] = None
        if hasattr(final_response, "model_dump") and callable(final_response.model_dump):
            try:
                raw_dump = final_response.model_dump()
            except TypeError:
                try:
                    raw_dump = final_response.model_dump(mode="python")
                except Exception:  # pylint: disable=broad-except
                    raw_dump = None

        if raw_dump is None and hasattr(final_response, "__dict__"):
            raw_dump = {
                k: v for k, v in final_response.__dict__.items() if not k.startswith("_")
            }

        await _collect_video_bytes(raw_dump if raw_dump is not None else final_response)

        if not video_bytes:
            raise RuntimeError("OpenAI did not return any video content for the provided prompt.")

        saved_files: List[Path] = []
        for index, payload in enumerate(video_bytes, start=1):
            if not isinstance(payload, (bytes, bytearray)):
                continue
            file_path = self._save_video_file(bytes(payload), output_dir_path, video_number=index, mime_format=mime_format)
            saved_files.append(file_path)

        if not saved_files:
            raise RuntimeError("Failed to persist OpenAI video generation results.")

        execution_time = time.time() - start_time
        usage = CompletionUsage(
            prompt_tokens=len(prompt.prompt or ""),
            total_time=execution_time,
            extra_usage={
                "videos_requested": prompt.number_of_videos,
                "aspect_ratio": prompt.aspect_ratio,
                "duration": prompt.duration,
                "negative_prompt": prompt.negative_prompt,
                "model": model_name,
            },
        )

        ai_message = AIMessageFactory.from_video(
            output=raw_dump or final_response,
            files=saved_files,
            media=saved_files,
            input=prompt.prompt,
            model=model_name,
            provider="openai",
            usage=usage,
            response_time=execution_time,
            raw_response=raw_dump,
        )

        return ai_message
