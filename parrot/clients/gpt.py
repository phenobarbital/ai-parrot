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
from dataclasses import is_dataclass
from PIL import Image
import pytesseract
from pydantic import BaseModel, ValidationError, TypeAdapter
from datamodel.parsers.json import json_decoder, json_decoder  # pylint: disable=E0611 # noqa
from navconfig import config, BASE_DIR
from tenacity import (
    AsyncRetrying,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from openai import AsyncOpenAI
from openai import APIConnectionError, RateLimitError, APIError, BadRequestError
from .base import AbstractClient
from ..models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    CompletionUsage,
    VideoGenerationPrompt,
    StructuredOutputConfig,
    OutputFormat
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
    "gpt-5-pro",
    "gpt-5-mini",
}

STRUCTURED_OUTPUT_COMPATIBLE_MODELS = {
    OpenAIModel.GPT_4O_MINI.value,
    OpenAIModel.GPT_O4.value,
    OpenAIModel.GPT_4O.value,
    OpenAIModel.GPT4_1.value,
    OpenAIModel.GPT_4_1_MINI.value,
    OpenAIModel.GPT_4_1_NANO.value,
    OpenAIModel.GPT5_MINI.value,
    OpenAIModel.GPT5.value,
    OpenAIModel.GPT5_CHAT.value,
    OpenAIModel.GPT5_PRO.value,
}

DEFAULT_STRUCTURED_OUTPUT_MODEL = OpenAIModel.GPT_4O_MINI.value


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
            ((), {"id": file_id}),
            ((), {"id": file_id}),
            ((), {"file": file_id}),
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

    async def _chat_completion(
        self,
        model: str,
        messages: Any,
        use_tools: bool = False,
        **kwargs
    ):
        retry_policy = AsyncRetrying(
            retry=retry_if_exception_type((APIConnectionError, RateLimitError, APIError)),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(5),
            reraise=True
        )
        if use_tools:
            method = self.client.chat.completions.create
        else:
            method = getattr(self.client.chat.completions, 'parse', self.client.chat.completions.create)
        async for attempt in retry_policy:
            with attempt:
                return await method(
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
        if "temperature" in args and args["temperature"] is not None:
            req["temperature"] = args["temperature"]
        if "max_tokens" in args and args["max_tokens"] is not None:
            req["max_output_tokens"] = args["max_tokens"]
        if "parallel_tool_calls" in args:
            req["parallel_tool_calls"] = args["parallel_tool_calls"]
        return req

    @staticmethod
    def _with_extra_body(payload: Dict[str, Any], extra_body: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(payload)
        existing_raw = merged.pop("extra_body", None)
        existing = (
            dict(existing_raw) if isinstance(existing_raw, dict) else {}
        ) | extra_body
        if existing:
            merged["extra_body"] = existing
        return merged

    async def _call_responses_create(self, payloads):
        """
        Try several payload shapes against responses.create().
        We retry not only on TypeError (client-side signature issues)
        but also on BadRequestError when the server reports unknown params,
        so we can fall back to older-SDK-compatible shapes.
        """
        last_exc = None
        for payload in payloads:
            try:
                return await self.client.responses.create(**payload)
            except TypeError as exc:
                last_exc = exc
            except BadRequestError as exc:
                # 2.6.0 returns 400 unknown_parameter for fields like "response", "modalities", etc.
                msg = getattr(exc, "message", "") or ""
                body = getattr(getattr(exc, "response", None), "json", lambda: {})()
                code = (body.get("error") or {}).get("code", "")
                param = (body.get("error") or {}).get("param", "")
                if code == "unknown_parameter" or "Unknown parameter" in msg or param in {"response", "modalities", "video"}:
                    last_exc = exc
                    continue
                raise  # other 400s should bubble up
        if last_exc:
            raise last_exc
        raise RuntimeError(
            "OpenAI responses.create call failed without response"
        )

    async def _call_responses_stream(self, payloads):
        """
        Try several payload shapes against responses.stream(), mirroring
        the compatibility shims we use for responses.create().
        """
        last_exc = None
        for payload in payloads:
            try:
                return await self.client.responses.stream(**payload)
            except TypeError as exc:
                last_exc = exc
            except BadRequestError as exc:
                msg = getattr(exc, "message", "") or ""
                body = getattr(getattr(exc, "response", None), "json", lambda: {})()
                code = (body.get("error") or {}).get("code", "")
                param = (body.get("error") or {}).get("param", "")
                if code == "unknown_parameter" or "Unknown parameter" in msg or param in {"response", "modalities", "video"}:
                    last_exc = exc
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError(
            "OpenAI responses.stream call failed without response"
        )

    async def _responses_completion(
        self,
        *,
        model: str,
        messages,
        **args
    ):
        """
        Adapter around OpenAI Responses API that mimics Chat Completions:
        returns an object with `.choices[0].message` where `message` has
        `.content: str` and `.tool_calls: list` (each item has `.id` and `.function.{name,arguments}`).
        """
        # 1) Build request payload from chat-like messages/args
        resp_format = args.get("response_format")
        req = self._prepare_responses_args(messages=messages, args=args)
        req["model"] = model

        # 2) Call Responses API
        payload_base = dict(req)
        payload_base.pop("response", None)
        payload_base.pop("response_format", None)

        attempts: List[Dict[str, Any]] = []
        if resp_format:
            # 2.6-compatible first:
            attempts.append({**payload_base, "response_format": resp_format})
            # Fallback to future SDKs that accept namespaced `response`:
            attempts.append(self._with_extra_body(payload_base, {"response": {"format": resp_format}}))
            # Last resort: drop structured constraints
            attempts.append(dict(payload_base))
        else:
            attempts.append(dict(payload_base))

        resp = await self._call_responses_create(attempts)

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
        finish_reason = None
        stop_reason = None
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

            finish_reason = finish_reason or getattr(item, "finish_reason", None)
            if isinstance(item, dict):
                finish_reason = finish_reason or item.get("finish_reason")
            stop_reason = stop_reason or getattr(item, "stop_reason", None)
            if isinstance(item, dict):
                stop_reason = stop_reason or item.get("stop_reason")

        # 5) Build a Chat-like container
        class _Msg:
            def __init__(self, content, tool_calls):
                self.content = content
                self.tool_calls = tool_calls

        class _Choice:
            def __init__(self, message, *, finish_reason=None, stop_reason=None):
                self.message = message
                self.finish_reason = finish_reason
                self.stop_reason = stop_reason

        class _CompatResp:
            def __init__(self, raw, message, *, finish_reason=None, stop_reason=None):
                self.raw = raw
                self.choices = [_Choice(message, finish_reason=finish_reason, stop_reason=stop_reason)]
                # Usage may or may not exist; keep attribute for downstream code
                self.usage = getattr(raw, "usage", None)

        message = _Msg(output_text or "", norm_tool_calls)
        return _CompatResp(
            resp,
            message,
            finish_reason=finish_reason,
            stop_reason=stop_reason,
        )

    async def ask(
        self,
        prompt: str,
        model: Union[str, OpenAIModel] = OpenAIModel.GPT4_1,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
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
            structured_output (Union[type, StructuredOutputConfig, None], optional):
                Structured output definition, supporting Pydantic models, dataclasses,
                or explicit StructuredOutputConfig instances. Defaults to None.
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

        model_str = model.value if isinstance(model, Enum) else str(model)

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

        messages.append({"role": "user", "content": prompt})

        all_tool_calls = []

        output_config = self._get_structured_config(
            structured_output
        )

        # tools prep
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)
        tools = self._prepare_tools() if (_use_tools) else None

        args = {}
        if model_str in {
            OpenAIModel.GPT_4O_MINI_SEARCH.value,
            OpenAIModel.GPT_4O_SEARCH.value
        }:
            args['web_search_options'] = {
                "web_search": True,
                "web_search_model": "gpt-4o-mini"
            }

        if tools:
            args['tools'] = tools
            args['tool_choice'] = "auto"
            args['parallel_tool_calls'] = True

        if output_config and output_config.format == OutputFormat.JSON and model_str not in STRUCTURED_OUTPUT_COMPATIBLE_MODELS:
            self.logger.warning(
                "Model %s does not support structured outputs; switching to %s",
                model_str,
                DEFAULT_STRUCTURED_OUTPUT_MODEL
            )
            model_str = DEFAULT_STRUCTURED_OUTPUT_MODEL

        if model_str != 'gpt-5-nano':
            args['max_tokens'] = max_tokens or self.max_tokens
        if temperature:
            args['temperature'] = temperature

        # -------- ROUTING: Responses-only vs Chat -----------
        use_responses = self._is_responses_model(model_str)
        resp_format = self._build_response_format_from(output_config) if output_config else None

        if use_responses:
            if output_config:
                args['response_format'] = resp_format
            response = await self._responses_completion(
                model=model_str,
                messages=messages,
                **args
            )
        else:
            if output_config:
                args['response_format'] = resp_format
            response = await self._chat_completion(
                model=model_str,
                messages=messages,
                use_tools=_use_tools,
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
                if output_config:
                    args['response_format'] = resp_format
                response = await self._responses_completion(
                    model=model_str,
                    messages=messages,
                    **args
                )
            else:
                if output_config:
                    args['response_format'] = resp_format
                response = await self._chat_completion(
                    model=model_str,
                    messages=messages,
                    use_tools=_use_tools,
                    **args
                )
            result = response.choices[0].message

        # ---------- Finalization (unchanged) ----------
        messages.append({"role": "assistant", "content": result.content})

        response_text = result.content if isinstance(result.content, str) else self._json.dumps(result.content)
        final_output = None
        if output_config:
            try:
                if output_config.custom_parser:
                    final_output = output_config.custom_parser(response_text)
                else:
                    final_output = await self._parse_structured_output(
                        response_text,
                        output_config
                    )
            except Exception:  # pylint: disable=broad-except
                final_output = response_text

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

        structured_payload = None
        if final_output is not None and not (
            isinstance(final_output, str) and final_output == response_text
        ):
            structured_payload = final_output

        ai_message = AIMessageFactory.from_openai(
            response=response,
            input_text=original_prompt,
            model=model_str,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=structured_payload
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
        tools: Optional[List[Dict[str, Any]]] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
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
        tools_payload = self._prepare_tools() if self.tools else None

        args: Dict[str, Any] = {}

        if tools_payload:
            args['tools'] = tools_payload
            args['tool_choice'] = "auto"
            args["parallel_tool_calls"] = True

        max_tokens_value = max_tokens if max_tokens is not None else self.max_tokens
        if max_tokens_value is not None:
            args['max_tokens'] = max_tokens_value

        temperature_value = temperature if temperature is not None else self.temperature
        if temperature_value is not None:
            args['temperature'] = temperature_value

        # -------- structured output config (normalize + model guard) --------
        output_config = self._get_structured_config(structured_output)
        if output_config and output_config.format == OutputFormat.JSON and model_str not in STRUCTURED_OUTPUT_COMPATIBLE_MODELS:
            self.logger.warning(
                "Model %s does not support structured outputs; switching to %s",
                model_str,
                DEFAULT_STRUCTURED_OUTPUT_MODEL
            )
            model_str = DEFAULT_STRUCTURED_OUTPUT_MODEL

        # Build the OpenAI response_format payload (dict) once
        resp_format = self._build_response_format_from(output_config) if output_config else None

        use_responses = self._is_responses_model(model_str)
        assistant_content = ""

        if use_responses:
            req = self._prepare_responses_args(messages=messages, args=args)
            req["model"] = model_str

            payload_base = dict(req)
            payload_base.pop("response", None)
            payload_base.pop("response_format", None)
            attempts: List[Dict[str, Any]] = []
            if resp_format:
                attempts.extend(
                    (
                        {**payload_base, "response_format": resp_format},
                        self._with_extra_body(
                            payload_base, {"response": {"format": resp_format}}
                        ),
                        dict(payload_base),
                    )
                )
            else:
                attempts: List[Dict[str, Any]] = [dict(payload_base)]

            stream_cm = await self._call_responses_stream(attempts)

            async with stream_cm as stream:
                async for event in stream:
                    event_type = getattr(event, "type", None)
                    if event_type is None and isinstance(event, dict):
                        event_type = event.get("type")

                    if event_type == "response.output_text.delta":
                        delta = getattr(event, "delta", None)
                        if delta is None and isinstance(event, dict):
                            delta = event.get("delta")
                        if delta:
                            assistant_content += delta
                            yield delta
                    elif event_type == "response.output_text.done":
                        text = getattr(event, "text", None)
                        if text is None and isinstance(event, dict):
                            text = event.get("text")
                        if text:
                            assistant_content += text
                            yield text

                final_response = None
                try:
                    final_response = await stream.get_final_response()
                except Exception:  # pylint: disable=broad-except
                    final_response = None

            if final_response and not assistant_content:
                output_text = getattr(final_response, "output_text", None) or ""
                if not output_text:
                    for item in getattr(final_response, "output", []) or []:
                        for part in getattr(item, "content", []) or []:
                            text_part = None
                            if isinstance(part, dict):
                                if part.get("type") == "output_text":
                                    text_part = part.get("text", "")
                            else:
                                text_part = getattr(part, "text", None)
                            if text_part:
                                output_text += text_part
                if output_text:
                    assistant_content = output_text
                    yield output_text
        else:
            chat_args = dict(args)
            method = getattr(
                self.client.chat.completions, "parse",
                None
            ) if output_config else None
            if callable(method):
                try:
                    response_stream = await method(  # pylint: disable=E1102 # noqa
                        model=model_str,
                        messages=messages,
                        stream=True,
                        response_format=(output_config.output_type if output_config else None),
                        **chat_args
                    )
                except TypeError:
                    # parse() in this SDK may not accept stream=True → fallback to create()
                    method = None
            else:
                response_stream = await self.client.chat.completions.create(
                    model=model_str,
                    messages=messages,
                    stream=True,
                    response_format=(output_config.output_type if output_config else None),
                    **chat_args
                )

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
            use_tools=False,
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
        prompt: Union[str, Any],
        *,
        model_name: str = "sora-2",        # "sora-1" or "sora-2"
        duration: Optional[int] = None,    # seconds (if your access supports it)
        ratio: Optional[str] = None,       # "16:9", "9:16", "1:1", etc. (mapped to aspect_ratio)
        output_path: Optional[Union[str, Path]] = None,
        poll_interval: float = 2.0,
        timeout: float = 15 * 60,          # 15 minutes
        extra: Optional[Dict[str, Any]] = None,  # pass-through for future knobs (seed/fps/style/etc.)
    ):
        """
        Generate a video with Sora using the Videos API and return an AIMessage.

        Notes:
        - Requires an openai 2.6.x build that exposes `client.videos`.
        - This function intentionally does NOT fall back to Responses for video,
            because 2.6.0 rejects a `response` object (400 unknown_parameter).
        """
        start_ts = time.time()

        # -------- 0) Verify Videos API exists in this installed client --------
        videos_res = getattr(self.client, "videos", None)
        if videos_res is None:
            import openai as _openai
            ver = getattr(_openai, "__version__", "unknown")
            raise RuntimeError(
                f"openai=={ver} does not expose `client.videos`; "
                "this build cannot generate video. Please upgrade to a build that includes the Videos API."
            )

        # -------- 1) Normalize prompt + build create kwargs --------
        if isinstance(prompt, str):
            prompt_text = prompt
            create_kwargs: Dict[str, Any] = {"model": model_name, "prompt": prompt_text}
        else:
            # supports objects like your VideoPrompt with `.prompt` and maybe `.options`
            prompt_text = getattr(prompt, "prompt", None) or str(prompt)
            create_kwargs = {"model": model_name, "prompt": prompt_text}
            # if user supplied options, merge them
            opts = getattr(prompt, "options", None)
            if isinstance(opts, dict):
                create_kwargs |= opts

        if duration is not None:
            create_kwargs["duration"] = duration
        if ratio:
            create_kwargs["aspect_ratio"] = ratio
        if extra:
            create_kwargs |= extra

        # choose output file
        out_path = Path(output_path) if output_path else Path.cwd() / f"{int(start_ts)}_{model_name}.mp4"

        # -------- 2) Run job (prefer create_and_poll) --------
        create_and_poll = getattr(videos_res, "create_and_poll", None)
        if callable(create_and_poll):
            video_obj = await create_and_poll(**create_kwargs)
        else:
            create = getattr(videos_res, "create", None)
            retrieve = getattr(videos_res, "retrieve", None)
            if not callable(create) or not callable(retrieve):
                import openai as _openai
                ver = getattr(_openai, "__version__", "unknown")
                raise RuntimeError(
                    f"`client.videos` exists but lacks required methods in openai=={ver} "
                    "(expected videos.create and videos.retrieve)."
                )
            job = await create(**create_kwargs)
            vid_id = getattr(job, "id", None) or getattr(job, "video_id", None)
            if not vid_id:
                raise RuntimeError(f"Videos.create returned no id: {job!r}")

            status = getattr(job, "status", None) or "queued"
            start_poll = time.time()
            while status in ("queued", "in_progress", "processing", "running"):
                if (time.time() - start_poll) > timeout:
                    raise RuntimeError(f"Video job {vid_id} timed out after {timeout}s")
                await asyncio.sleep(poll_interval)
                job = await retrieve(vid_id)
                status = getattr(job, "status", None)
            if status not in ("completed", "succeeded", "success"):
                err = getattr(job, "error", None) or getattr(job, "last_error", None)
                raise RuntimeError(f"Video job {vid_id} failed with status={status}, error={err}")
            video_obj = job

        # -------- 3) Download the MP4 --------
        download = getattr(videos_res, "download_content", None)
        vid_id = getattr(video_obj, "id", None) or getattr(video_obj, "video_id", None)
        if callable(download) and vid_id:
            content = await download(vid_id)
            data = await content.aread() if hasattr(content, "aread") else bytes(content)
            out_path.write_bytes(data)
        else:
            url = getattr(video_obj, "url", None) or getattr(video_obj, "download_url", None)
            if url:
                # You can implement your own HTTP fetch here if needed
                raise RuntimeError(
                    "download_content() is unavailable and direct URL download isn't implemented. "
                    "Please enable videos.download_content in your SDK."
                )
            raise RuntimeError("Could not download video: no download method or URL available on video object.")

        # -------- 4) Build saved_files + usage + raw_dump --------
        saved_files = [{
            "path": str(out_path),
            "mime_type": "video/mp4",
            "type": "video",
            "id": vid_id,
            "model": getattr(video_obj, "model", model_name),
            "duration": getattr(video_obj, "duration", None),
        }]

        # usage is typically token-based for text; keep a minimal structure for consistency
        usage = getattr(video_obj, "usage", None) or {
            "total_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }

        # serialize the raw object if it’s a Pydantic-like model
        raw_dump = (
            video_obj.model_dump() if hasattr(video_obj, "model_dump")
            else getattr(video_obj, "__dict__", video_obj)
        )

        execution_time = time.time() - start_ts

        # -------- 5) Return AIMessage (drop-in) --------
        return AIMessageFactory.from_video(
            output=raw_dump or video_obj,
            files=saved_files,
            media=saved_files,
            input=prompt_text,
            model=model_name,
            provider="openai",
            usage=usage,
            response_time=execution_time,
            raw_response=raw_dump,
        )
