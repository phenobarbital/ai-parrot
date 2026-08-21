"""OpenAI-compatible wire protocol base client.

``OpenAIBaseClient`` carries the OpenAI chat-completions wire protocol
(request/response shaping, tool-calling loop, streaming, structured output)
with **no** OpenAI-the-provider defaults. It declares no model attribute
values — ``_default_model``/``_fallback_model``/``_lightweight_model`` stay
``None`` (inherited from :class:`~parrot.clients.base.AbstractClient`) so the
invoke chain falls back to ``self.model`` instead of silently sending an
OpenAI-only model id to a non-OpenAI endpoint.

This module MUST NOT contain any OpenAI-specific model-id literal — that is
OpenAI-the-provider knowledge and belongs exclusively in
:mod:`parrot.clients.gpt`.

See ``sdd/specs/openai-compatible-clients.spec.md`` (FEAT-438) §3 Module 1.
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from datamodel.parsers.json import json_decoder
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..models import (
    AIMessage,
    AIMessageFactory,
    CompletionUsage,
    StructuredOutputConfig,
    ToolCall,
)
from ..tools.manager import ToolFormat
from .base import AbstractClient


class OpenAIBaseClient(AbstractClient):
    """OpenAI-compatible wire protocol; carries NO OpenAI-provider defaults.

    Subclasses that speak the OpenAI chat-completions wire protocol under a
    provider-specific label (Bedrock Mantle, OpenRouter, Moonshot, Nvidia,
    LocalLLM/vLLM, and — in Phase 2 — Groq/Zai via their native SDKs) should
    inherit from this class instead of :class:`~parrot.clients.gpt.OpenAIClient`
    directly, so they never inherit OpenAI-the-provider defaults (OpenAI-only
    model ids, Responses-API routing, Sora, etc.).
    """

    tool_format: ToolFormat = ToolFormat.OPENAI
    # Intentionally NO _default_model / _fallback_model / _lightweight_model
    # values here — they stay None (AbstractClient defaults) so the invoke
    # chain (base.py:_resolve_invoke_model) falls through to self.model.

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs,
    ):
        """Initialize the OpenAI-compatible wire client.

        Args:
            api_key: Bearer token for the target endpoint. Providers supply
                their own environment-variable default in their own
                ``__init__`` — this base does not read any env var.
            base_url: Base URL of the OpenAI-compatible endpoint. Providers
                supply their own default in their own ``__init__``.
            **kwargs: Forwarded to :class:`~parrot.clients.base.AbstractClient`.
                May include ``model`` (normalized via :meth:`_normalize_model`
                before being forwarded) and ``timeout`` (SDK request timeout,
                defaults to 60 seconds).
        """
        self.api_key = api_key
        self.base_url = base_url
        self.base_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        self._timeout = kwargs.pop("timeout", 60)
        if "model" in kwargs:
            kwargs["model"] = self._normalize_model(kwargs["model"])
        super().__init__(**kwargs)

    async def get_client(self) -> Any:
        """Build the default OpenAI-SDK-shaped async client.

        Lazily imports ``openai.AsyncOpenAI`` so the SDK is only required
        when an OpenAI-compatible client is actually instantiated. Subclasses
        that wrap a native SDK (Groq, Zai) override this hook.

        Returns:
            An ``AsyncOpenAI`` instance configured with this client's
            ``api_key``/``base_url``/timeout.

        Raises:
            ImportError: If the ``openai`` package is not installed.
        """
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAIBaseClient requires the 'openai' SDK. "
                "Install with: pip install ai-parrot[openai]"
            ) from exc
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self._timeout,
        )

    def _normalize_model(self, model: Any) -> str:
        """Coerce *model* to ``str``. Identity — no deprecation logic.

        The base carries no knowledge of any provider's model catalog or
        deprecation schedule; :class:`~parrot.clients.gpt.OpenAIClient`
        overrides this with OpenAI-specific alias/deprecation handling.

        Args:
            model: A model id string, or an ``Enum`` whose ``.value`` is the
                model id.

        Returns:
            The model id as a plain string.
        """
        return model.value if hasattr(model, "value") else model

    def _resolve_model(self, model: Any | None) -> str:
        """Resolve the model for a call: explicit > configured > class default.

        Args:
            model: Explicit per-call model, or ``None`` to use the configured
                one.

        Returns:
            The resolved model id.

        Raises:
            ValueError: If the resolution chain yields no model at all — the
                base never sends ``model=None`` on the wire.
        """
        resolved = model or self.model or self.default_model
        if not resolved:
            raise ValueError(
                f"no model configured for {self.__class__.__name__}"
            )
        return self._normalize_model(resolved)

    def _is_responses_model(self, model_str: str) -> bool:
        """Return whether *model_str* must be routed via the Responses API.

        Always ``False`` in the base — Responses-API routing is
        OpenAI-the-provider behavior owned by
        :class:`~parrot.clients.gpt.OpenAIClient`.

        Args:
            model_str: The resolved model id.

        Returns:
            ``False``.
        """
        return False

    @staticmethod
    def _with_extra_body(payload: dict[str, Any], extra_body: dict[str, Any]) -> dict[str, Any]:
        """Merge *extra_body* into *payload*'s ``extra_body`` key.

        Args:
            payload: The request payload dict.
            extra_body: Additional provider-specific keys to merge into the
                payload's ``extra_body``.

        Returns:
            A new dict with ``extra_body`` merged in (existing values win
            over *extra_body* on key collision).
        """
        merged = dict(payload)
        existing_raw = merged.pop("extra_body", None)
        existing = (dict(existing_raw) if isinstance(existing_raw, dict) else {}) | extra_body
        if existing:
            merged["extra_body"] = existing
        return merged

    async def _chat_completion(
        self, model: str, messages: Any, use_tools: bool = False, **kwargs
    ) -> Any:
        """Call ``chat.completions.create``/``.parse`` with retry.

        The tenacity-wrapped single completion funnel shared by ``ask()``,
        ``resume()``, and (once TASK-2298 lands) ``ask_stream()``/``invoke()``.
        Moved verbatim from :class:`~parrot.clients.gpt.OpenAIClient`
        (FEAT-438 Module 2) — the retry policy and dispatch logic are generic
        to any OpenAI-SDK-shaped ``self.client``.

        Args:
            model: The resolved model id.
            messages: The chat-completions message list.
            use_tools: If ``True``, always use ``.create`` (tool-calling
                responses cannot use ``.parse``). If ``False``, prefer
                ``.parse`` when the SDK exposes it (structured output),
                falling back to ``.create``.
            **kwargs: Additional OpenAI chat-completions request kwargs
                (``tools``, ``tool_choice``, ``max_tokens``, ``temperature``,
                ``response_format``, etc.).

        Returns:
            The raw SDK response object.
        """
        from openai import APIConnectionError, APIError, RateLimitError

        retry_policy = AsyncRetrying(
            retry=retry_if_exception_type((APIConnectionError, RateLimitError, APIError)),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(3),
            reraise=True,
        )
        if use_tools:
            method = self.client.chat.completions.create
        else:
            method = getattr(self.client.chat.completions, "parse", self.client.chat.completions.create)
        async for attempt in retry_policy:
            with attempt:
                return await method(model=model, messages=messages, **kwargs)

    @staticmethod
    def _extract_completion_usage(response_obj: Any) -> tuple:
        """Extract ``(CompletionUsage, raw_usage_dict)`` from an SDK response.

        Both the Chat Completions and Responses API SDK response shapes
        expose ``.usage`` the same way (FEAT-397).

        Args:
            response_obj: A raw SDK response with an optional ``.usage``.

        Returns:
            A 2-tuple ``(CompletionUsage | None, dict | None)``.
        """
        usage_obj = getattr(response_obj, "usage", None)
        if not usage_obj:
            return None, None
        per_round = CompletionUsage.from_openai(usage_obj)
        raw = None
        if hasattr(usage_obj, "model_dump"):
            try:
                raw = usage_obj.model_dump()
            except Exception:  # noqa: BLE001 pylint: disable=broad-except
                raw = None
        elif isinstance(usage_obj, dict):
            raw = usage_obj
        return per_round, raw

    async def _run_tool_call_loop(
        self,
        *,
        result: Any,
        response: Any,
        messages: list[dict[str, Any]],
        model_str: str,
        use_tools: bool,
        args: dict[str, Any],
        call_completion: Callable | None = None,
        session_id: str | None = None,
        lazy_loading: bool = False,
        active_tool_names: set | None = None,
        track_usage: bool = False,
        initial_duration_ms: float = 0.0,
        on_round: Callable | None = None,
        record_malformed_tool_calls: bool = True,
        default_tool_name: str | None = None,
    ) -> tuple:
        """Shared tool-calling loop for ``ask()``/``resume()`` (FEAT-438 Module 2).

        Replaces the two inline, duplicated while-loops that previously
        lived in :class:`~parrot.clients.gpt.OpenAIClient`'s ``ask()``
        (gpt.py:947-1143) and ``resume()`` (gpt.py:1190-1257): executes any
        pending tool calls on *result*, appends the assistant/tool messages,
        re-invokes *call_completion* for the next round, and repeats until
        the model responds with no further tool calls.

        The two original loops differed subtly on two corner cases —
        ``resume()`` never recorded a :class:`ToolCall` for malformed tool
        arguments and used a ``"unknown"`` fallback tool name, while
        ``ask()`` recorded the error and required ``tool_call.function.name``
        to exist. ``record_malformed_tool_calls``/``default_tool_name``
        preserve that distinction exactly (see the FEAT-438 TASK-2297
        Completion Note).

        Args:
            result: The initial ``response.choices[0].message`` to inspect
                for ``tool_calls``.
            response: The initial full SDK response object (used for usage
                extraction when ``track_usage`` is ``True``).
            messages: The mutable conversation message list; each round's
                assistant/tool messages are appended to it in place.
            model_str: The resolved model id passed to *call_completion*.
            use_tools: Forwarded to *call_completion* as ``use_tools``.
            args: Extra kwargs forwarded to *call_completion* each round
                (``tools``, ``tool_choice``, ``response_format``, etc.). May
                be mutated in place — lazy-tool re-preparation rewrites
                ``args["tools"]``.
            call_completion: Async callable ``(model, messages, use_tools,
                **kwargs) -> response`` used to fetch the next round's
                response. Defaults to :meth:`_chat_completion`.
            session_id: Attached to a re-raised ``HumanInteractionInterrupt``
                for resumability.
            lazy_loading: If ``True``, re-prepares tools via
                ``self._prepare_tools(filter_names=...)`` whenever a
                ``search_tools`` call surfaces new tool names.
            active_tool_names: Mutable set of currently active tool names,
                consulted/updated only when ``lazy_loading`` is ``True``.
            track_usage: If ``True``, accumulate per-round
                :class:`CompletionUsage` across rounds.
            initial_duration_ms: Wall-clock duration (ms) of the call that
                produced *response*/*result*, measured by the caller before
                entering the loop — becomes round 1's ``duration_ms``.
            on_round: Optional callable ``(round_number, usage, raw_usage,
                tool_names, duration_ms)`` invoked once per tool-execution
                round (used for ``ClientRoundEvent`` emission). ``None``
                skips round reporting entirely (``resume()`` never reports).
            record_malformed_tool_calls: If ``True`` (``ask()`` semantics), a
                malformed tool-call (bad JSON args) is still recorded as a
                :class:`ToolCall` with an ``_error`` argument. If ``False``
                (``resume()`` semantics), it is dropped from the returned
                list entirely.
            default_tool_name: If not ``None``, resolve the tool name via
                ``getattr(tool_call.function, "name", default_tool_name)``
                (``resume()`` semantics: ``"unknown"``); if ``None``, use
                ``tool_call.function.name`` directly (``ask()`` semantics).

        Returns:
            A 5-tuple ``(result, response, all_tool_calls, accumulated_usage,
            round_number)``: the final assistant message (with no further
            ``tool_calls``), the final full SDK response, the list of
            executed :class:`ToolCall` objects across all rounds, the
            accumulated :class:`CompletionUsage` (``None`` when
            ``track_usage`` is ``False`` or no usage was ever reported), and
            the 1-indexed number of completion rounds observed.
        """
        if call_completion is None:
            call_completion = self._chat_completion
        if active_tool_names is None:
            active_tool_names = set()

        all_tool_calls: list[ToolCall] = []
        round_number = 1
        round_duration_ms = initial_duration_ms
        accumulated_usage: CompletionUsage | None = None
        round_usage: CompletionUsage | None = None
        round_raw_usage: dict | None = None

        if track_usage:
            round_usage, round_raw_usage = self._extract_completion_usage(response)
            if round_usage is not None:
                accumulated_usage = round_usage

        while getattr(result, "tool_calls", None):
            round_tool_names: list[str] = []
            messages.append(
                {
                    "role": "assistant",
                    "content": result.content,
                    "tool_calls": [
                        (
                            tc.model_dump()
                            if hasattr(tc, "model_dump")
                            else {
                                "id": tc.id,
                                "function": {
                                    "name": getattr(tc.function, "name", None),
                                    "arguments": getattr(tc.function, "arguments", "{}"),
                                },
                            }
                        )
                        for tc in result.tool_calls
                    ],
                }
            )

            found_new_tools = False

            for tool_call in result.tool_calls:
                if default_tool_name is not None:
                    tool_name = getattr(tool_call.function, "name", default_tool_name)
                else:
                    tool_name = tool_call.function.name
                try:
                    try:
                        tool_args = self._json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = json_decoder(tool_call.function.arguments)

                    tc = ToolCall(id=getattr(tool_call, "id", ""), name=tool_name, arguments=tool_args)

                    try:
                        start_time = time.time()
                        tool_result = await self._execute_tool(tool_name, tool_args)
                        execution_time = time.time() - start_time

                        if lazy_loading and tool_name == "search_tools":
                            new_tools = self._check_new_tools(tool_name, str(tool_result))
                            if new_tools:
                                for nt in new_tools:
                                    if nt not in active_tool_names:
                                        active_tool_names.add(nt)
                                        found_new_tools = True

                        tc.result = tool_result
                        tc.execution_time = execution_time

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": getattr(tool_call, "id", ""),
                                "name": tool_name,
                                "content": str(tool_result),
                            }
                        )
                    except Exception as e:
                        from parrot.core.exceptions import HumanInteractionInterrupt

                        if isinstance(e, HumanInteractionInterrupt):
                            e.session_id = session_id
                            e.messages = messages.copy()
                            e.tool_call_id = getattr(tool_call, "id", "")
                            e.agent_name = model_str
                            raise

                        tc.error = str(e)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": getattr(tool_call, "id", ""),
                                "name": tool_name,
                                "content": str(e),
                            }
                        )

                    all_tool_calls.append(tc)
                    round_tool_names.append(tool_name)

                except Exception as e:  # noqa: BLE001 — malformed tool-call args, must not crash the loop
                    if record_malformed_tool_calls:
                        all_tool_calls.append(
                            ToolCall(
                                id=getattr(tool_call, "id", ""),
                                name=tool_name,
                                arguments={"_error": f"malformed tool args: {e}"},
                            )
                        )
                        round_tool_names.append(tool_name)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": getattr(tool_call, "id", ""),
                            "name": tool_name,
                            "content": f"Error decoding arguments: {e}",
                        }
                    )

            if lazy_loading and found_new_tools:
                args["tools"] = self._prepare_tools(filter_names=list(active_tool_names))

            if on_round is not None:
                on_round(round_number, round_usage, round_raw_usage, round_tool_names, round_duration_ms)

            round_t0 = time.perf_counter()
            response = await call_completion(model=model_str, messages=messages, use_tools=use_tools, **args)
            round_number += 1
            round_duration_ms = (time.perf_counter() - round_t0) * 1000

            if track_usage:
                round_usage, round_raw_usage = self._extract_completion_usage(response)
                if round_usage is not None:
                    accumulated_usage = (
                        round_usage if accumulated_usage is None else accumulated_usage + round_usage
                    )

            result = response.choices[0].message

        return result, response, all_tool_calls, accumulated_usage, round_number

    async def ask(
        self,
        prompt: str,
        model: Any | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        files: list[str | Path] | None = None,
        system_prompt: str | None = None,
        structured_output: type | StructuredOutputConfig | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        use_tools: bool | None = None,
        lazy_loading: bool = False,
    ) -> AIMessage:
        """Ask the OpenAI-compatible endpoint a question with optional conversation memory.

        Generic chat-completions implementation shared by every
        ``OpenAIBaseClient`` subclass that speaks the plain OpenAI wire
        protocol. Subclasses needing Responses-API routing, deep-research
        dispatch, or other OpenAI-provider-only behavior override this
        method (currently only :class:`~parrot.clients.gpt.OpenAIClient`,
        which reuses :meth:`_chat_completion`/:meth:`_run_tool_call_loop`
        from this base while keeping its own richer ``ask()``).

        Args:
            prompt: The prompt to send to the model.
            model: The model to use, or ``None`` to use the configured one.
            max_tokens: Maximum tokens for the response.
            temperature: Sampling temperature.
            files: Files to upload before the call.
            system_prompt: System prompt to prepend.
            structured_output: Structured output definition (Pydantic model,
                dataclass, or explicit ``StructuredOutputConfig``).
            user_id: User ID for conversation memory.
            session_id: Session ID for conversation memory.
            tools: Tools to register for this call.
            use_tools: Whether to use tools; defaults to ``self.enable_tools``.
            lazy_loading: If ``True``, enable dynamic tool searching.

        Returns:
            The response from the model.

        Raises:
            NotImplementedError: If the resolved model requires Responses-API
                routing (:meth:`_is_responses_model`) and this class does not
                override ``ask()`` to handle it.
        """
        turn_id = str(uuid.uuid4())
        original_prompt = prompt
        _use_tools = use_tools if use_tools is not None else self.enable_tools

        model_str = self._resolve_model(model)

        if self._is_responses_model(model_str):
            raise NotImplementedError(
                f"{type(self).__name__} does not implement Responses-API routing "
                "for this model; override ask() to handle it."
            )

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        _lc_tc = self._emit_before_call(
            client_name=self.client_name,
            model=model_str,
            temperature=temperature if temperature is not None else self.temperature,
            system_prompt=system_prompt,
            has_tools=bool(_use_tools),
            parent_trace=None,
        )
        _lc_t0 = time.perf_counter()

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
            if isinstance(system_prompt, list):
                system_prompt = "\n\n".join(s.text for s in system_prompt)
            messages.insert(0, {"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        output_config = self._get_structured_config(structured_output)

        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        active_tool_names = set()
        prepared_tools = None

        if _use_tools:
            if lazy_loading:
                prepared_tools = self._prepare_lazy_tools()
                if prepared_tools:
                    active_tool_names.add("search_tools")
            else:
                prepared_tools = self._prepare_tools()

        args: dict[str, Any] = {}
        if prepared_tools:
            args["tools"] = prepared_tools
            args["tool_choice"] = "auto"

        if max_tokens or self.max_tokens:
            args["max_tokens"] = max_tokens or self.max_tokens
        if temperature:
            args["temperature"] = temperature

        if output_config:
            args["response_format"] = self._build_response_format_from(output_config)

        _used_fallback = False
        _original_model = model_str

        _round_t0 = time.perf_counter()
        try:
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
                response = await self._chat_completion(
                    model=model_str, messages=messages, use_tools=_use_tools, **args
                )
            else:
                raise
        _round_duration_ms = (time.perf_counter() - _round_t0) * 1000
        result = response.choices[0].message

        def _on_round(round_number, usage, raw_usage, tool_names, duration_ms):
            self._emit_round_event(
                _lc_tc,
                client_name=self.client_name,
                model=model_str,
                round_number=round_number,
                usage=usage,
                raw_usage=raw_usage,
                tool_calls=tool_names,
                duration_ms=duration_ms,
            )

        result, response, all_tool_calls, accumulated_usage, round_number = await self._run_tool_call_loop(
            result=result,
            response=response,
            messages=messages,
            model_str=model_str,
            use_tools=_use_tools,
            args=args,
            session_id=session_id,
            lazy_loading=lazy_loading,
            active_tool_names=active_tool_names,
            track_usage=True,
            initial_duration_ms=_round_duration_ms,
            on_round=_on_round,
        )

        messages.append({"role": "assistant", "content": result.content})

        response_text = result.content if isinstance(result.content, str) else self._json.dumps(result.content)
        final_output = None
        if output_config:
            try:
                if output_config.custom_parser:
                    final_output = output_config.custom_parser(response_text)
                else:
                    final_output = await self._parse_structured_output(response_text, output_config)
            except Exception:  # noqa: BLE001 pylint: disable=broad-except
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

        if accumulated_usage is not None:
            if round_number > 1:
                accumulated_usage.extra_usage["rounds"] = round_number
            ai_message.usage = accumulated_usage

        ai_message.tool_calls = all_tool_calls
        if _used_fallback:
            ai_message.metadata["used_fallback_model"] = True
            ai_message.metadata["original_model"] = _original_model
            ai_message.metadata["fallback_model"] = self._fallback_model

        _lc_usage = getattr(ai_message, "usage", None)
        await self._emit_after_call(
            _lc_tc,
            client_name=self.client_name,
            model=model_str,
            duration_ms=(time.perf_counter() - _lc_t0) * 1000,
            input_tokens=getattr(_lc_usage, "prompt_tokens", None) if _lc_usage else None,
            output_tokens=getattr(_lc_usage, "completion_tokens", None) if _lc_usage else None,
            finish_reason=getattr(ai_message, "stop_reason", None),
        )
        return ai_message

    async def resume(self, session_id: str, user_input: str, state: dict[str, Any]) -> AIMessage:
        """Resume a suspended model execution.

        Args:
            session_id: The session ID.
            user_input: The user's input to inject as a tool result.
            state: The suspended state containing messages and tool_call_id.

        Returns:
            The response from the model.
        """
        await self._ensure_client()

        messages = state["messages"]
        tool_call_id = state["tool_call_id"]
        model_str = state.get("agent_name", self.model or self.default_model)

        messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "name": "handoff_tool", "content": user_input}
        )

        turn_id = str(uuid.uuid4())

        response = await self._chat_completion(model=model_str, messages=messages, use_tools=True)
        result = response.choices[0].message

        result, response, all_tool_calls, _accumulated_usage, _round_number = await self._run_tool_call_loop(
            result=result,
            response=response,
            messages=messages,
            model_str=model_str,
            use_tools=True,
            args={},
            session_id=session_id,
            record_malformed_tool_calls=False,
            default_tool_name="unknown",
        )

        ai_message = AIMessageFactory.from_openai(
            response=response,
            input_text="[Resumed Conversation]",
            model=model_str,
            user_id="unknown",
            session_id=session_id,
            turn_id=turn_id,
        )
        ai_message.tool_calls = all_tool_calls
        return ai_message

    async def batch_ask(self, requests: list[dict[str, Any]]) -> list[AIMessage]:
        """Process multiple ``ask()`` requests sequentially.

        No native batch API exists for the OpenAI wire protocol; requests
        are processed one at a time via :meth:`ask`.

        Args:
            requests: A list of kwargs dicts, each forwarded to :meth:`ask`.

        Returns:
            The list of :class:`AIMessage` responses, in request order.
        """
        results = []
        for request in requests:
            result = await self.ask(**request)
            results.append(result)
        return results
