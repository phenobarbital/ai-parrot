from __future__ import annotations
from typing import AsyncIterator, Dict, List, Optional, Union, Any, Tuple, TYPE_CHECKING
import io
import json
import uuid
import warnings
from pathlib import Path
import time
import asyncio
from logging import getLogger
from enum import Enum
from parrot._imports import lazy_import
from pydantic import ValidationError
from datamodel.parsers.json import json_decoder, json_decoder  # pylint: disable=E0611 # noqa
from navconfig import config
from .openai_base import OpenAIBaseClient

if TYPE_CHECKING:
    # Type-check-only imports — keep IDE/mypy support without forcing the
    # SDKs to be installed at runtime when this client is unused.
    from openai import AsyncOpenAI
    from PIL import Image
from ..models import AIMessage, AIMessageFactory, ToolCall, CompletionUsage, StructuredOutputConfig, OutputFormat
from ..models.responses import InvokeResult
from ..exceptions import InvokeError
from ..models.openai import (
    OpenAIModel,
    is_deprecated,
    get_shutoff_date,
    resolve_alias,
)
from ..models.outputs import ProductReview
from ..models.detections import DetectionBox, ShelfRegion, IdentifiedProduct

# The httpx/httpcore families are quieted by parrot.clients.openai_base at
# import time (it covers the httpx2/httpcore2 names the OpenAI SDK actually
# uses); only the SDK's own logger is set here.
getLogger("openai").setLevel("INFO")

# Module-level deduplication cache for deprecation warnings (spec §3 Module 2).
# set.add is atomic under the GIL; no async lock needed.
_warned: set[str] = set()

# Reasoning models available via the Responses API only.
# NOTE: spec §8 Q1 open — search-preview / deep-research IDs are
# DEPRECATED (shutoff 2026-07-23) and NOT listed here; their code
# paths are preserved with DeprecationWarnings until Q1 is resolved.
RESPONSES_ONLY_MODELS = {
    "o3",
    "o3-pro",
}

STRUCTURED_OUTPUT_COMPATIBLE_MODELS = {
    OpenAIModel.GPT5_6.value,
    OpenAIModel.GPT5_6_SOL.value,
    OpenAIModel.GPT5_6_TERRA.value,
    OpenAIModel.GPT5_6_LUNA.value,
    OpenAIModel.GPT5_5.value,
    OpenAIModel.GPT5_5_PRO.value,
    OpenAIModel.GPT5_4.value,
    OpenAIModel.GPT5_4_PRO.value,
    OpenAIModel.GPT5_4_MINI.value,
    OpenAIModel.GPT5_4_NANO.value,
    OpenAIModel.GPT5_3_CODEX.value,
    OpenAIModel.GPT5_2.value,
    OpenAIModel.GPT5_2_PRO.value,
    OpenAIModel.GPT5_1.value,
    OpenAIModel.GPT5.value,
    OpenAIModel.GPT5_PRO.value,
    OpenAIModel.GPT5_MINI.value,
    OpenAIModel.GPT5_NANO.value,
    OpenAIModel.CHAT_LATEST.value,
    OpenAIModel.GPT4_1.value,
    OpenAIModel.GPT4_1_MINI.value,
    OpenAIModel.GPT4O_MINI.value,
}

DEFAULT_STRUCTURED_OUTPUT_MODEL = OpenAIModel.GPT5_MINI.value


class OpenAIClient(OpenAIBaseClient):
    """Client for interacting with OpenAI's API."""

    client_type: str = "openai"
    # tool_format = ToolFormat.OPENAI is inherited from OpenAIBaseClient
    # (FEAT-438) — no need to redeclare it here.
    model: str = OpenAIModel.GPT5_MINI.value
    client_name: str = "openai"
    _default_model: str = "gpt-5-mini"
    _fallback_model: str = "gpt-5-nano"
    _lightweight_model: str = "gpt-4.1"
    # FEAT-181: OpenAI caches prefixes ≥1024 tokens automatically
    _min_cache_tokens: int = 1024

    def __init__(self, api_key: str = None, base_url: str = "https://api.openai.com/v1", **kwargs):
        # FEAT-438: resolve the OpenAI-specific API-key env default here,
        # then delegate to OpenAIBaseClient.__init__ (which sets
        # self.api_key/base_url/base_headers) instead of setting them
        # directly — the base's __init__ would otherwise clobber them back
        # to None since it no longer receives them via **kwargs.
        resolved_api_key = api_key or config.get("OPENAI_API_KEY")
        if "model" in kwargs:
            kwargs["model"] = self._normalize_model(kwargs["model"])
        super().__init__(api_key=resolved_api_key, base_url=base_url, **kwargs)

    def _resolve_model(self, model: Union[str, OpenAIModel, None]) -> str:
        """Resolve the model for a call, honouring the client's configuration.

        A hard-coded signature default would override the model the client was
        constructed with — which silently sent OpenAI model ids to
        OpenAI-compatible endpoints (Bedrock Mantle, OpenRouter, LocalLLM,
        vLLM, Moonshot, Nvidia) that do not host them.

        Args:
            model: Explicit per-call model, or ``None`` to use the configured
                one.

        Returns:
            The resolved model id: explicit call argument, then the model this
            client was configured with, then the class default.
        """
        return self._normalize_model(model or self.model or self.default_model)

    def _normalize_model(self, model: Union[str, OpenAIModel]) -> str:
        """Coerce model to str and emit a one-shot DeprecationWarning if deprecated.

        The warning is emitted exactly once per (model, process) using the
        module-level ``_warned`` cache. ``stacklevel=3`` so the warning points
        at user code (e.g. the caller of ``ask()``), not at this helper.
        """
        s = model.value if isinstance(model, OpenAIModel) else model
        if is_deprecated(s) and s not in _warned:
            shutoff = get_shutoff_date(s)
            target = resolve_alias(s)
            warnings.warn(
                f"OpenAI model '{s}' is deprecated; shutoff {shutoff}. " f"Migrate to '{target}'.",
                DeprecationWarning,
                stacklevel=3,
            )
            _warned.add(s)
        return s

    def _apply_cache_hints(
        self,
        payload: dict,
        segments: list,
        trace_context=None,
    ) -> dict:
        """OpenAI cache translator — FEAT-181.

        OpenAI caches prompt prefixes ≥ 1024 tokens automatically; no API
        shape change is required.  When segments are provided, this method
        concatenates them back into a single string and stores it under
        ``payload["system"]`` so the existing message-build path can use it
        directly.

        Note: the caller (``ask()`` / ``ask_stream()``) already guards against
        ``List[CacheableSegment]`` being inserted into messages directly — this
        method is the canonical place for the collapse, but the inline guards
        remain as a defence-in-depth measure.

        Args:
            payload: The request payload dict being assembled.
            segments: List of ``CacheableSegment`` produced by
                ``PromptBuilder.build_segments()``.  May be empty.
            trace_context: Optional W3C trace context for event correlation.
                When ``None``, a new root trace is created for the event.

        Returns:
            The (potentially updated) payload dict.
        """
        import hashlib as _hashlib
        from parrot.core.events.lifecycle.events import (
            PromptCacheAppliedEvent as _PCApplied,
            PromptCacheSkippedEvent as _PCSkipped,
        )
        from parrot.core.events.lifecycle import TraceContext as _TC

        tc = trace_context if trace_context is not None else _TC.new_root()
        if not segments:
            self.events.emit_nowait(
                _PCSkipped(
                    trace_context=tc,
                    client_name="openai",
                    model=payload.get("model", ""),
                    reason="no_segments",
                    source_type="client",
                    source_name="openai",
                )
            )
            return payload
        # OpenAI prefix caching is automatic — just reconstruct the string.
        combined = "\n\n".join(s.text for s in segments)
        # Store under "system" so the caller can read it back as a plain string.
        payload["system"] = combined
        # Emit cache-applied event (fire-and-forget; OpenAI caching is implicit)
        cacheable_segs = [s for s in segments if s.cacheable]
        seg_hashes = tuple(_hashlib.sha256(s.text.encode()).hexdigest() for s in cacheable_segs)
        est_tokens = sum(len(s.text) // 4 for s in cacheable_segs)
        self.events.emit_nowait(
            _PCApplied(
                trace_context=tc,
                client_name="openai",
                model=payload.get("model", ""),
                blocks_marked=0,  # OpenAI caching is implicit; no explicit blocks
                est_tokens=est_tokens,
                segment_hashes=seg_hashes,
                source_type="client",
                source_name="openai",
            )
        )
        return payload

    def _is_capacity_error(self, error: Exception) -> bool:
        """Detect OpenAI capacity errors.

        Overrides base class with OpenAI-specific exception types.
        """
        from openai import RateLimitError, APIError

        if isinstance(error, RateLimitError):
            return True
        if isinstance(error, APIError) and hasattr(error, "status_code"):
            if error.status_code in (502, 503):
                return True
        return super()._is_capacity_error(error)

    async def get_client(self) -> "AsyncOpenAI":
        """Initialize the OpenAI client."""
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAIClient requires the 'openai' SDK. " "Install with: pip install ai-parrot[openai]"
            ) from exc
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=config.get("OPENAI_TIMEOUT", 60),
        )

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

    # _upload_file moved to OpenAIBaseClient (FEAT-438 Module 2) — generic,
    # inherited unchanged.

    # _chat_completion moved to OpenAIBaseClient (FEAT-438 Module 2) — the
    # tenacity-wrapped retry/dispatch logic is generic and now inherited
    # unchanged.

    def _is_responses_model(self, model_str: str) -> bool:
        """Return True if the selected model must go through Responses API."""
        # allow aliases/enums already normalized to str
        ms = (model_str or "").strip()
        return ms in RESPONSES_ONLY_MODELS

    @staticmethod
    def _resolve_deep_research_model(model_str: str) -> str:
        """Resolve the deep research model. NOTE: spec §8 Q1 open — these IDs
        are deprecated upstream (shutoff 2026-07-23). Branch retained until
        the question is resolved."""
        warnings.warn(
            "Deep-research models are deprecated (shutoff 2026-07-23). " "Pending decision in spec §8 Q1.",
            DeprecationWarning,
            stacklevel=2,
        )
        normalized = (model_str or "").strip()
        if normalized in {"o4-mini", "o4-mini-deep-research"}:
            return "o4-mini-deep-research"
        return "o3-deep-research"

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
                        part.get("text", "") if isinstance(part, dict) else str(part) for part in sys_content
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
        if "background" in args and args["background"] is not None:
            req["background"] = args["background"]
        return req

    # _with_extra_body moved to OpenAIBaseClient (TASK-2296) — inherited
    # unchanged.

    async def _call_responses_create(self, payloads):
        """
        Try several payload shapes against responses.create().
        We retry not only on TypeError (client-side signature issues)
        but also on BadRequestError when the server reports unknown params,
        so we can fall back to older-SDK-compatible shapes.
        """
        from openai import BadRequestError

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
                if (
                    code == "unknown_parameter"
                    or "Unknown parameter" in msg
                    or param in {"response", "modalities", "video"}
                ):
                    last_exc = exc
                    continue
                raise  # other 400s should bubble up
        if last_exc:
            raise last_exc
        raise RuntimeError("OpenAI responses.create call failed without response")

    async def _call_responses_stream(self, payloads):
        """
        Try several payload shapes against responses.stream(), mirroring
        the compatibility shims we use for responses.create().
        """
        from openai import BadRequestError

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
                if (
                    code == "unknown_parameter"
                    or "Unknown parameter" in msg
                    or param in {"response", "modalities", "video"}
                ):
                    last_exc = exc
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError("OpenAI responses.stream call failed without response")

    async def _responses_completion(self, *, model: str, messages, **args):
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
                    elif text := getattr(part, "text", None):
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

        # 4b) The Responses API reports truncation at the top level, not per
        #     output item: ``status="incomplete"`` with
        #     ``incomplete_details.reason`` ("max_output_tokens" |
        #     "content_filter"). Surface it as the Chat-style finish_reason so
        #     the shared truncation guard (_raise_if_truncated) can see it.
        if finish_reason is None and getattr(resp, "status", None) == "incomplete":
            details = getattr(resp, "incomplete_details", None)
            if isinstance(details, dict):
                finish_reason = details.get("reason")
            else:
                finish_reason = getattr(details, "reason", None)
            finish_reason = finish_reason or "incomplete"

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
        model: Union[str, OpenAIModel, None] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        deep_research: bool = False,
        background: bool = False,
        vector_store_ids: Optional[List[str]] = None,
        enable_web_search: bool = True,
        enable_code_interpreter: bool = False,
        lazy_loading: bool = False,
    ) -> AIMessage:
        """Ask OpenAI a question with optional conversation memory.

        Args:
            prompt (str): The prompt to send to the model.
            model (Union[str, OpenAIModel], optional): The model to use. Defaults to GPT5_MINI.
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
            deep_research (bool): If True, use OpenAI's deep research models (o3/o4-deep-research).
            background (bool): If True, execute research in background (not yet supported).
            vector_store_ids (Optional[List[str]]): Vector store IDs for file_search tool.
            enable_web_search (bool): Enable web search preview tool (default: True for deep research).
            enable_code_interpreter (bool): Enable code interpreter tool.
            lazy_loading (bool): If True, enable dynamic tool searching.

        Returns:
            AIMessage: The response from the model.

        """

        turn_id = str(uuid.uuid4())
        original_prompt = prompt
        _use_tools = use_tools if use_tools is not None else self.enable_tools

        model = self._resolve_model(model)
        model_str = model.value if isinstance(model, Enum) else str(model)

        # Deep research routing: switch to deep research model if requested
        if deep_research:
            # Use o3-deep-research as default deep research model.
            # NOTE: these model IDs are deprecated (shutoff 2026-07-23); see spec §8 Q1.
            if model_str not in {"o3-deep-research", "o4-mini-deep-research"}:
                model_str = self._resolve_deep_research_model(model_str)
                self.logger.info(f"Deep research enabled: switching to {model_str}")

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # FEAT-176: lifecycle event — BeforeClientCallEvent
        import time as _lc_time_gpt

        _lc_tc_gpt = self._emit_before_call(
            client_name="openai",
            model=model_str,
            temperature=temperature if temperature is not None else self.temperature,
            system_prompt=system_prompt,
            has_tools=bool(_use_tools),
            parent_trace=None,
        )
        _lc_t0_gpt = _lc_time_gpt.perf_counter()

        if files:
            for file in files:
                if isinstance(file, str):
                    file = Path(file)
                if isinstance(file, Path):
                    await self._upload_file(file)

        # Add search instruction if lazy loading is enabled
        if lazy_loading and system_prompt:
            system_prompt += (
                "\n\nYou have access to a library of tools. Use the 'search_tools' function to find relevant tools."
            )
        elif lazy_loading and not system_prompt:
            system_prompt = (
                "You have access to a library of tools. Use the 'search_tools' function to find relevant tools."
            )

        if system_prompt:
            # FEAT-181: collapse List[CacheableSegment] → string before inserting
            if isinstance(system_prompt, list):
                system_prompt = "\n\n".join(s.text for s in system_prompt)
            messages.insert(0, {"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        output_config = self._get_structured_config(structured_output)

        # Build tools for deep research or regular use
        research_tools = []
        if deep_research:
            # For deep research, build specialized tools array
            if enable_web_search:
                research_tools.append({"type": "web_search_preview"})

            if vector_store_ids:
                research_tools.append({"type": "file_search", "vector_store_ids": vector_store_ids})

            if enable_code_interpreter:
                research_tools.append({"type": "code_interpreter", "container": {"type": "auto", "memory_limit": "4g"}})

            self.logger.info(f"Deep research tools configured: {len(research_tools)} tools")

        # tools prep
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        # LAZY LOADING LOGIC
        active_tool_names = set()
        prepared_tools = None

        if _use_tools:
            if lazy_loading:
                # Prepare only search_tools + explicitly passed tools?
                # Using _prepare_lazy_tools which handles search_tools
                prepared_tools = self._prepare_lazy_tools()
                if prepared_tools:
                    active_tool_names.add("search_tools")
            else:
                prepared_tools = self._prepare_tools()

        args = {}
        # NOTE: spec §8 Q1 open — search-preview IDs deprecated (shutoff 2026-07-23).
        # Branch retained until Q1 is resolved.
        if model_str in {
            "gpt-4o-mini-search-preview",
            "gpt-4o-search-preview",
            "gpt-4o-mini-search-preview-2025-03-11",
            "gpt-4o-search-preview-2025-03-11",
        }:
            warnings.warn(
                f"OpenAI model '{model_str}' is a search-preview model deprecated "
                "upstream (shutoff 2026-07-23). See spec §8 Q1.",
                DeprecationWarning,
                stacklevel=2,
            )
            args["web_search_options"] = {"web_search": True, "web_search_model": "gpt-4o-mini"}

        # Merge research tools with regular tools
        if deep_research and research_tools:
            # For deep research, add research-specific tools
            args["tools"] = research_tools
        elif prepared_tools:
            args["tools"] = prepared_tools
            args["tool_choice"] = "auto"
            args["parallel_tool_calls"] = True

        if (
            output_config
            and output_config.format == OutputFormat.JSON
            and model_str not in STRUCTURED_OUTPUT_COMPATIBLE_MODELS
        ):
            self.logger.warning(
                "Model %s does not support structured outputs; switching to %s",
                model_str,
                DEFAULT_STRUCTURED_OUTPUT_MODEL,
            )
            model_str = DEFAULT_STRUCTURED_OUTPUT_MODEL

        if model_str != "gpt-5-nano":
            args["max_tokens"] = self._resolve_max_tokens(max_tokens)
        if temperature:
            args["temperature"] = temperature
        if deep_research and background:
            args["background"] = True

        # -------- ROUTING: Responses-only vs Chat -----------
        use_responses = self._is_responses_model(model_str)
        resp_format = self._build_response_format_from(output_config) if output_config else None
        _used_fallback = False
        _original_model = model_str

        _lc_round_t0_gpt = _lc_time_gpt.perf_counter()

        try:
            if use_responses:
                if output_config:
                    args["response_format"] = resp_format
                response = await self._responses_completion(model=model_str, messages=messages, **args)
            else:
                if output_config:
                    args["response_format"] = resp_format
                response = await self._chat_completion(model=model_str, messages=messages, use_tools=_use_tools, **args)
        except Exception as e:
            if self._should_use_fallback(model_str, e):
                self.logger.warning(
                    "Model %s capacity error: %s. Retrying once with fallback: %s",
                    model_str,
                    e,
                    self._fallback_model,
                )
                model_str = self._fallback_model
                _used_fallback = True
                if use_responses:
                    response = await self._responses_completion(model=model_str, messages=messages, **args)
                else:
                    response = await self._chat_completion(
                        model=model_str, messages=messages, use_tools=_use_tools, **args
                    )
            else:
                raise

        # FEAT-397: round 1 is the initial (pre-loop) call above.
        _lc_round_duration_gpt = (_lc_time_gpt.perf_counter() - _lc_round_t0_gpt) * 1000
        result = response.choices[0].message

        # ---------- Tool loop (works for both paths) ----------
        # FEAT-438: single shared implementation (OpenAIBaseClient) instead
        # of an inline duplicate of resume()'s loop. `_continue_call` keeps
        # the Responses-API-vs-chat-completions routing this method already
        # had; `_on_round` keeps emitting the same ClientRoundEvent as before.
        async def _continue_call(model, messages, use_tools, **kw):
            if use_responses:
                return await self._responses_completion(model=model, messages=messages, **kw)
            return await self._chat_completion(model=model, messages=messages, use_tools=use_tools, **kw)

        def _on_round(round_number, usage, raw_usage, tool_names, duration_ms):
            self._emit_round_event(
                _lc_tc_gpt,
                client_name="openai",
                model=model_str,
                round_number=round_number,
                usage=usage,
                raw_usage=raw_usage,
                tool_calls=tool_names,
                duration_ms=duration_ms,
            )

        result, response, all_tool_calls, _lc_accumulated_usage_gpt, _lc_round_number_gpt = await self._run_tool_call_loop(
            result=result,
            response=response,
            messages=messages,
            model_str=model_str,
            use_tools=_use_tools,
            args=args,
            session_id=session_id,
            call_completion=_continue_call,
            lazy_loading=lazy_loading,
            active_tool_names=active_tool_names,
            track_usage=True,
            initial_duration_ms=_lc_round_duration_gpt,
            on_round=_on_round,
        )

        # ---------- Finalization (unchanged) ----------
        messages.append({"role": "assistant", "content": result.content})

        response_text = result.content if isinstance(result.content, str) else self._json.dumps(result.content)
        final_output = None
        if output_config:
            try:
                # Known-truncated output must not reach a custom parser either.
                self._raise_if_truncated(self._extract_finish_reason(response), model=model_str)
                if output_config.custom_parser:
                    final_output = output_config.custom_parser(response_text)
                else:
                    final_output = await self._parse_structured_output(
                        response_text,
                        output_config,
                        finish_reason=self._extract_finish_reason(response),
                        model=model_str,
                    )
            except InvokeError:
                raise
            except Exception:  # pylint: disable=broad-except
                final_output = response_text

        tools_used = [tc.name for tc in all_tool_calls]
        assistant_response_text = (
            result.content if isinstance(result.content, str) else self._json.dumps(result.content)
        )
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt,
            turn_id,
            original_prompt,
            assistant_response_text,
            tools_used,
        )

        structured_payload = None
        if final_output is not None and not (isinstance(final_output, str) and final_output == response_text):
            structured_payload = final_output

        ai_message = AIMessageFactory.from_openai(
            response=response,
            input_text=original_prompt,
            model=model_str,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=structured_payload,
        )

        # FEAT-397: replace the last-round-only usage with the accumulated
        # multi-round total. For single-round calls (no tool use), the
        # accumulated total equals the last (only) round's usage, so this
        # is a no-op for existing single-round behavior.
        if _lc_accumulated_usage_gpt is not None:
            if _lc_round_number_gpt > 1:
                _lc_accumulated_usage_gpt.extra_usage["rounds"] = _lc_round_number_gpt
            ai_message.usage = _lc_accumulated_usage_gpt

        ai_message.tool_calls = all_tool_calls
        if _used_fallback:
            ai_message.metadata["used_fallback_model"] = True
            ai_message.metadata["original_model"] = _original_model
            ai_message.metadata["fallback_model"] = self._fallback_model
        # FEAT-176: lifecycle event — AfterClientCallEvent
        _lc_gpt_usage = getattr(ai_message, "usage", None)
        await self._emit_after_call(
            _lc_tc_gpt,
            client_name="openai",
            model=model_str,
            duration_ms=(_lc_time_gpt.perf_counter() - _lc_t0_gpt) * 1000,
            input_tokens=getattr(_lc_gpt_usage, "prompt_tokens", None) if _lc_gpt_usage else None,
            output_tokens=getattr(_lc_gpt_usage, "completion_tokens", None) if _lc_gpt_usage else None,
            finish_reason=getattr(ai_message, "stop_reason", None),
        )
        return ai_message

    # resume() moved to OpenAIBaseClient (FEAT-438 Module 2) — it had no
    # OpenAI-only logic; it is now inherited unchanged (reusing the same
    # _run_tool_call_loop that ask() above uses).

    async def ask_stream(
        self,
        prompt: str,
        model: Union[str, OpenAIModel, None] = None,
        max_tokens: int = None,
        temperature: float = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: bool = True,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        vector_store_ids: Optional[List[str]] = None,
        enable_web_search: bool = True,
        enable_code_interpreter: bool = False,
        lazy_loading: bool = False,
        **kwargs,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Stream OpenAI's response with optional conversation memory.

        Yields successive string chunks followed by a final
        :class:`~parrot.models.responses.AIMessage` with metadata.

        Args:
            deep_research: If True, use deep research models with streaming
            agent_config: Optional configuration (not used for OpenAI, for interface compatibility)
            vector_store_ids: Vector store IDs for file_search tool
            enable_web_search: Enable web search preview tool
            enable_code_interpreter: Enable code interpreter tool
            lazy_loading: If True, enable dynamic tool searching
        """

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        model = self._resolve_model(model)
        # Extract model value if it's an enum
        model_str = model.value if isinstance(model, Enum) else model

        # Deep research routing (same as in ask method).
        # NOTE: these model IDs are deprecated (shutoff 2026-07-23); see spec §8 Q1.
        if deep_research:
            if model_str not in {"o3-deep-research", "o4-mini-deep-research"}:
                model_str = self._resolve_deep_research_model(model_str)
                self.logger.info(f"Deep research streaming enabled: switching to {model_str}")

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # FEAT-176: lifecycle event — BeforeClientCallEvent for stream
        import time as _lc_time_gpts
        from parrot.core.events.lifecycle.events import ClientStreamChunkEvent as _GPTStreamChunkEvent

        _lc_tc_gpts = self._emit_before_call(
            client_name="openai",
            model=model_str,
            temperature=temperature if temperature is not None else self.temperature,
            system_prompt=system_prompt,
            has_tools=bool(self.tools) and use_tools,
            parent_trace=None,
        )
        _lc_t0_gpts = _lc_time_gpts.perf_counter()
        _lc_has_chunk_subs_gpt = self.events.has_subscribers(_GPTStreamChunkEvent)
        _lc_chunk_idx_gpt = 0

        # Upload files if they are path-like objects
        if files:
            for file in files:
                if isinstance(file, str):
                    file = Path(file)
                if isinstance(file, Path):
                    await self._upload_file(file)

        if lazy_loading and system_prompt:
            system_prompt += (
                "\n\nYou have access to a library of tools. Use the 'search_tools' function to find relevant tools."
            )
        elif lazy_loading and not system_prompt:
            system_prompt = (
                "You have access to a library of tools. Use the 'search_tools' function to find relevant tools."
            )

        if system_prompt:
            # FEAT-181: collapse List[CacheableSegment] → string before inserting
            if isinstance(system_prompt, list):
                system_prompt = "\n\n".join(s.text for s in system_prompt)
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Build research tools if needed
        research_tools = []
        if deep_research:
            if enable_web_search:
                research_tools.append({"type": "web_search_preview"})
            if vector_store_ids:
                research_tools.append({"type": "file_search", "vector_store_ids": vector_store_ids})
            if enable_code_interpreter:
                research_tools.append({"type": "code_interpreter", "container": {"type": "auto", "memory_limit": "4g"}})
            self.logger.info(f"Deep research streaming tools: {len(research_tools)} tools")

        # Prepare tools (Note: streaming with tools is more complex)
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        # LAZY LOADING LOGIC
        active_tool_names = set()
        tools_payload = None

        if self.tools:
            if lazy_loading:
                tools_payload = self._prepare_lazy_tools()
                if tools_payload:
                    active_tool_names.add("search_tools")
            else:
                tools_payload = self._prepare_tools()

        args: Dict[str, Any] = {}

        # Merge research tools with regular tools (same logic as ask)
        if deep_research and research_tools:
            args["tools"] = research_tools
        elif tools_payload:
            args["tools"] = tools_payload
            args["tool_choice"] = "auto"
            args["parallel_tool_calls"] = True

        max_tokens_value = self._resolve_max_tokens(max_tokens)
        if max_tokens_value is not None:
            args["max_tokens"] = max_tokens_value

        temperature_value = temperature if temperature is not None else self.temperature
        if temperature_value is not None:
            args["temperature"] = temperature_value

        # -------- structured output config (normalize + model guard) --------
        output_config = self._get_structured_config(structured_output)
        if (
            output_config
            and output_config.format == OutputFormat.JSON
            and model_str not in STRUCTURED_OUTPUT_COMPATIBLE_MODELS
        ):
            self.logger.warning(
                "Model %s does not support structured outputs; switching to %s",
                model_str,
                DEFAULT_STRUCTURED_OUTPUT_MODEL,
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
                        self._with_extra_body(payload_base, {"response": {"format": resp_format}}),
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
                            # FEAT-176: per-chunk event
                            if _lc_has_chunk_subs_gpt:
                                await self.events.emit(
                                    _GPTStreamChunkEvent(
                                        trace_context=_lc_tc_gpts,
                                        client_name="openai",
                                        model=model_str,
                                        chunk_index=_lc_chunk_idx_gpt,
                                        chunk_size_bytes=len(delta.encode("utf-8")) if isinstance(delta, str) else 0,
                                        source_type="client",
                                        source_name="openai",
                                    )
                                )
                                _lc_chunk_idx_gpt += 1
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

            # Build and yield final AIMessage for Responses API path
            resp_usage_obj = getattr(final_response, "usage", None) if final_response else None
            if resp_usage_obj is not None:
                resp_usage = CompletionUsage.from_openai(resp_usage_obj)
            else:
                resp_usage = CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            resp_ai_message = AIMessage(
                input=prompt,
                output=assistant_content,
                response=assistant_content,
                model=model_str,
                provider="openai",
                usage=resp_usage,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
            )
            # FEAT-176: lifecycle event — AfterClientCallEvent (Responses API path)
            _lc_resp_usage = getattr(resp_ai_message, "usage", None)
            await self._emit_after_call(
                _lc_tc_gpts,
                client_name="openai",
                model=model_str,
                duration_ms=(_lc_time_gpts.perf_counter() - _lc_t0_gpts) * 1000,
                input_tokens=getattr(_lc_resp_usage, "prompt_tokens", None) if _lc_resp_usage else None,
                output_tokens=getattr(_lc_resp_usage, "completion_tokens", None) if _lc_resp_usage else None,
                finish_reason=None,
            )
            yield resp_ai_message
        else:
            chat_args = dict(args)
            # Request usage stats in the final streaming chunk (OpenAI SDK >= 1.17)
            chat_args["stream_options"] = {"include_usage": True}
            if output_config:
                chat_args["response_format"] = output_config.output_type
            usage_data = None
            all_tool_calls: List[ToolCall] = []
            _max_tool_rounds = 25  # safety cap

            # ── Streaming tool-call loop (Chat Completions path) ──
            for _tool_round in range(_max_tool_rounds):
                # FEAT-438 G3: route through the single completion funnel
                response_stream = await self._chat_completion(
                    model=model_str,
                    messages=messages,
                    use_tools=use_tools and not bool(output_config),
                    stream=True,
                    **chat_args,
                )

                _finish_reason = None
                # Accumulator for incremental tool-call chunks (keyed by index)
                _tc_accum: Dict[int, Dict[str, str]] = {}

                async for chunk in response_stream:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        _finish_reason = chunk.choices[0].finish_reason or _finish_reason

                        if delta and delta.content:
                            text_chunk = delta.content
                            assistant_content += text_chunk
                            # FEAT-176: per-chunk event
                            if _lc_has_chunk_subs_gpt:
                                await self.events.emit(
                                    _GPTStreamChunkEvent(
                                        trace_context=_lc_tc_gpts,
                                        client_name="openai",
                                        model=model_str,
                                        chunk_index=_lc_chunk_idx_gpt,
                                        chunk_size_bytes=len(text_chunk.encode("utf-8")),
                                        source_type="client",
                                        source_name="openai",
                                    )
                                )
                                _lc_chunk_idx_gpt += 1
                            yield text_chunk

                        # Accumulate tool-call fragments by index
                        if delta and hasattr(delta, "tool_calls") and delta.tool_calls:
                            for tc_chunk in delta.tool_calls:
                                idx = tc_chunk.index
                                if idx not in _tc_accum:
                                    _tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                                if tc_chunk.id:
                                    _tc_accum[idx]["id"] = tc_chunk.id
                                if tc_chunk.function:
                                    if tc_chunk.function.name:
                                        _tc_accum[idx]["name"] = tc_chunk.function.name
                                    if tc_chunk.function.arguments:
                                        _tc_accum[idx]["arguments"] += tc_chunk.function.arguments

                    # Capture usage from the final chunk
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        usage_data = chunk.usage

                # If the model requested tool calls, execute them and loop
                if _tc_accum and _finish_reason in ("tool_calls", "stop") and use_tools:
                    import json as _tc_json

                    # Build the assistant message with tool_calls for the conversation
                    oai_tool_calls = []
                    for idx in sorted(_tc_accum):
                        acc = _tc_accum[idx]
                        oai_tool_calls.append({
                            "id": acc["id"],
                            "type": "function",
                            "function": {"name": acc["name"], "arguments": acc["arguments"]},
                        })
                    assistant_msg: Dict[str, Any] = {"role": "assistant", "content": assistant_content or None}
                    assistant_msg["tool_calls"] = oai_tool_calls
                    messages.append(assistant_msg)

                    # Execute each tool and feed results back
                    for tc_entry in oai_tool_calls:
                        tool_name = tc_entry["function"]["name"]
                        try:
                            tool_args = _tc_json.loads(tc_entry["function"]["arguments"])
                        except _tc_json.JSONDecodeError:
                            tool_args = {}
                        tc = ToolCall(id=tc_entry["id"], name=tool_name, arguments=tool_args)
                        try:
                            start_t = time.time()
                            tool_result = await self._execute_tool(tool_name, tool_args)
                            tc.result = tool_result
                            tc.execution_time = time.time() - start_t
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_entry["id"],
                                "content": str(tool_result),
                            })
                        except Exception as e:
                            from parrot.core.exceptions import HumanInteractionInterrupt

                            if isinstance(e, HumanInteractionInterrupt):
                                e.session_id = session_id
                                e.messages = list(messages)
                                e.tool_call_id = tc_entry["id"]
                                e.agent_name = model_str
                                raise
                            tc.error = str(e)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_entry["id"],
                                "content": f"Error: {e}",
                            })
                        all_tool_calls.append(tc)

                    # Reset text accumulator for the next round (tool result
                    # round may produce new text)
                    assistant_content = ""
                    continue

                # Not a tool-call stop — done streaming
                break

            # Build and yield final AIMessage for Chat Completions path
            tools_used = [tc.name for tc in all_tool_calls]
            if usage_data is not None:
                chat_usage = CompletionUsage.from_openai(usage_data)
            else:
                chat_usage = CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            chat_ai_message = AIMessage(
                input=prompt,
                output=assistant_content,
                response=assistant_content,
                model=model_str,
                provider="openai",
                usage=chat_usage,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                tool_calls=all_tool_calls,
            )
            # FEAT-176: lifecycle event — AfterClientCallEvent (Chat Completions path)
            _lc_chat_usage = getattr(chat_ai_message, "usage", None)
            await self._emit_after_call(
                _lc_tc_gpts,
                client_name="openai",
                model=model_str,
                duration_ms=(_lc_time_gpts.perf_counter() - _lc_t0_gpts) * 1000,
                input_tokens=getattr(_lc_chat_usage, "prompt_tokens", None) if _lc_chat_usage else None,
                output_tokens=getattr(_lc_chat_usage, "completion_tokens", None) if _lc_chat_usage else None,
                finish_reason=_finish_reason,
            )
            yield chat_ai_message

        # Update conversation memory if content was generated
        if assistant_content:
            messages.append({"role": "assistant", "content": assistant_content})
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
                tools_used if 'tools_used' in dir() else [],
            )

    # batch_ask() moved to OpenAIBaseClient (FEAT-438 Module 2) — the
    # sequential loop over self.ask() is generic and now inherited
    # unchanged (self.ask() still resolves polymorphically to this
    # class's own ask() override above).

    # _encode_image_for_openai moved to OpenAIBaseClient (FEAT-438 Module 2)
    # — generic, inherited unchanged; still used below by ask_to_image() etc.

    async def ask_to_image(
        self,
        prompt: str,
        image: Union[Path, bytes, Image.Image],
        reference_images: Optional[List[Union[Path, bytes, Image.Image]]] = None,
        model: str = OpenAIModel.GPT5_MINI.value,
        max_tokens: int = None,
        temperature: float = None,
        structured_output: Optional[type] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        no_memory: bool = False,
        low_quality: bool = False,
    ) -> AIMessage:
        """Ask OpenAI a question about an image with optional conversation memory."""
        model = self._normalize_model(model)
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
            if hasattr(structured_output, "model_json_schema"):
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": structured_output.__name__.lower(),
                        "schema": structured_output.model_json_schema(),
                    },
                }
            elif isinstance(structured_output, dict):
                response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": structured_output},
                }
        else:
            response_format = {"type": "json_object"}

        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=self._resolve_max_tokens(max_tokens),
            temperature=temperature or self.temperature,
            response_format=response_format,
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

        assistant_message = {"role": "assistant", "content": [{"type": "text", "text": result.content}]}
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
            [],
        )

        usage = response.usage.model_dump() if response.usage else {}

        ai_message = AIMessageFactory.from_openai(
            response=response,
            input_text=f"[Image Analysis]: {prompt}",
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output,
        )

        ai_message.usage = CompletionUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            extra_usage=usage,
        )

        ai_message.provider = "openai"

        return ai_message

    async def summarize_text(
        self,
        text: str,
        max_length: int = 500,
        min_length: int = 100,
        model: Union[OpenAIModel, str] = OpenAIModel.GPT5_MINI,
        temperature: Optional[float] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Generate a concise summary of *text* (single paragraph, stateless).
        """
        model = self._normalize_model(model)
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
            max_tokens=self._resolve_max_tokens(),
            temperature=temperature or self.temperature,
            use_tools=False,
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

    async def translate_text(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        model: Union[OpenAIModel, str] = OpenAIModel.GPT5_MINI,
        temperature: float = 0.2,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Translate *text* from *source_lang* (auto‑detected if None) into *target_lang*.
        """
        model = self._normalize_model(model)
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
            max_tokens=self._resolve_max_tokens(),
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
        model: Union[OpenAIModel, str] = OpenAIModel.GPT5_MINI,
        temperature: float = 0.3,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Extract *num_points* bullet‑point key ideas from *text* (stateless).
        """
        model = self._normalize_model(model)
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
            max_tokens=self._resolve_max_tokens(),
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
        model: Union[OpenAIModel, str] = OpenAIModel.GPT5_MINI,
        temperature: float = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Perform sentiment analysis on *text* and return a structured explanation.
        """
        model = self._normalize_model(model)
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
            max_tokens=self._resolve_max_tokens(),
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
        model: Union[OpenAIModel, str] = OpenAIModel.GPT5_MINI,
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
        model = self._normalize_model(model)
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
            {
                "role": "user",
                "content": f"Product ID: {product_id}\nProduct Name: {product_name}\nReview: {review_text}",
            },
        ]

        # Use structured output with response_format
        response = await self._chat_completion(
            model=model.value if isinstance(model, Enum) else model,
            messages=messages,
            max_tokens=self._resolve_max_tokens(),
            temperature=temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "product_review_analysis",
                    "schema": ProductReview.model_json_schema(),
                    "strict": True,
                },
            },
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
        image: Union[Path, bytes, "Image.Image"],
        detections: List[DetectionBox],  # from parrot.models.detections
        shelf_regions: List[ShelfRegion],  # "
        reference_images: Optional[List[Union[Path, bytes, "Image.Image"]]] = None,
        model: Union[OpenAIModel, str] = OpenAIModel.GPT4_1_MINI,
        prompt: Optional[str] = None,
        temperature: float = 0.0,
        ocr_hints: bool = True,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> List[IdentifiedProduct]:
        """
        Step-2: Identify products using the detected boxes + reference images.

        Returns a list[IdentifiedProduct] with bbox, type, model, confidence, features,
        reference_match, shelf_location, and position_on_shelf.
        """
        try:
            from PIL import Image
        except ImportError as exc:
            raise ImportError("image_identification() requires Pillow. " "Install with: pip install Pillow") from exc
        model = self._normalize_model(model)
        try:
            _pytesseract = lazy_import("pytesseract", extra="ocr")
            _has_tesseract = True
        except ImportError:
            _pytesseract = None
            _has_tesseract = False

        def _crop_box(pil_img: "Image.Image", box) -> "Image.Image":
            # small padding to include context
            pad = 6
            x1 = max(0, box.x1 - pad)
            y1 = max(0, box.y1 - pad)
            x2 = min(pil_img.width, box.x2 + pad)
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
                thirds = (
                    best.bbox.x1 + (best.bbox.x2 - best.bbox.x1) / 3.0,
                    best.bbox.x1 + 2 * (best.bbox.x2 - best.bbox.x1) / 3.0,
                )
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
                    text = _pytesseract.image_to_string(crop)
                    text_hint = text.strip()
                except Exception:
                    text_hint = ""
            shelf, pos = _shelf_and_position(det, shelf_regions)
            crops.append(
                {
                    "id": i,
                    "det": det,
                    "shelf": shelf,
                    "position": pos,
                    "ocr": text_hint,
                    "img_content": self._encode_image_for_openai(crop),
                }
            )

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
            text_block = (
                prompt
                + "\n\nReturn ONLY JSON with top-level key 'items' that matches the provided schema."
                + "\n".join(meta_lines)
            )
        else:
            text_block = (
                "Identify each detection by comparing with the reference images. "
                "Prefer visual features (shape, control panel, ink tank layout) and use OCR hints only as supportive evidence. "
                "Allowed product_type: ['printer','product_box','fact_tag','promotional_graphic','ink_bottle']. "
                "Models to look for (if any): ['ET-2980','ET-3950','ET-4950']. "
                "Return one item per detection id.\n" + "\n".join(meta_lines)
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
                "detection_id",
                "product_type",
                "product_model",
                "confidence",
                "visual_features",
                "reference_match",
                "shelf_location",
                "position_on_shelf",
                "brand",
                "advertisement_type",
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
                            "minItems": len(detections),  # drop or lower if this causes 400s
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
            max_tokens=self._resolve_max_tokens(max_tokens),
            temperature=temperature or self.temperature,
            response_format=resp_format,
        )

        raw = response.choices[0].message.content or "{}"
        try:
            # data = json.loads(raw)
            data = json_decoder(raw)
            items = data.get("items") or data.get("detections") or []
        except Exception:
            # fallback: try best-effort parse if model didn’t honor schema
            data = self._json.loads(raw)
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
            shelf = it.get("shelf_location") or shelf
            pos = it.get("position_on_shelf") or pos

            # --- COERCION / DEFAULTS ---
            det_cls = det.class_name.lower()
            pt = (it.get("product_type") or "").strip().lower()
            pm = it.get("product_model") or None

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
        model_name: str = "sora-2",  # "sora-1" or "sora-2"
        duration: Optional[int] = None,  # seconds (if your access supports it)
        ratio: Optional[str] = None,  # "16:9", "9:16", "1:1", etc. (mapped to aspect_ratio)
        output_path: Optional[Union[str, Path]] = None,
        poll_interval: float = 2.0,
        timeout: float = 15 * 60,  # 15 minutes
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
        saved_files = [
            {
                "path": str(out_path),
                "mime_type": "video/mp4",
                "type": "video",
                "id": vid_id,
                "model": getattr(video_obj, "model", model_name),
                "duration": getattr(video_obj, "duration", None),
            }
        ]

        # usage is typically token-based for text; keep a minimal structure for consistency
        usage = getattr(video_obj, "usage", None) or {
            "total_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }

        # serialize the raw object if it’s a Pydantic-like model
        raw_dump = (
            video_obj.model_dump() if hasattr(video_obj, "model_dump") else getattr(video_obj, "__dict__", video_obj)
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

    # invoke() is inherited unchanged from OpenAIBaseClient (FEAT-438
    # code-review fix): this override used to be byte-for-byte functionally
    # identical to the base implementation (same logic, same call
    # sequence — only the "not initialised" error-message string differed
    # cosmetically, and that string renders identically for an
    # OpenAIClient instance either way since the base uses
    # ``type(self).__name__``). Keeping a dead duplicate here was a
    # maintenance hazard: a future change to the base's invoke() would
    # have silently failed to propagate to OpenAIClient.
