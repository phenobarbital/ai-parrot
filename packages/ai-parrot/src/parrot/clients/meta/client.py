"""Meta Model API client for AI-Parrot.

``MetaClient`` subclasses :class:`~parrot.clients.openai_base.OpenAIBaseClient`
— the neutral OpenAI-wire layer (FEAT-438) that owns the wire protocol and
declares no OpenAI-provider model defaults — to speak to Meta's Muse Spark
model family (https://api.meta.ai/v1).

Chat Completions (``ask``/``ask_stream``/``resume``/``invoke`` when
``use_responses=False``) is inherited unchanged: it already funnels through
``OpenAIBaseClient._chat_completion()``, and live testing confirmed the
base's existing emissions are Meta-legal (``tool_choice="auto"`` and
``max_tokens``).

The Responses API path (``use_responses=True``, the default) is net-new and
**local to this class** (design decision D1): ``OpenAIBaseClient`` has no
Responses-API support by design, so ``ask()``/``ask_stream()`` are overridden
here to route to :meth:`MetaClient._responses_completion`. The *structure* of
:class:`~parrot.clients.gpt.OpenAIClient`'s equivalent methods
(``gpt.py:353-680``) is mirrored as a read-only reference — never imported,
subclassed, or modified; some duplication is the accepted, reversible trade.

See ``sdd/specs/meta-llm-client.spec.md`` (FEAT-526).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, TYPE_CHECKING
from logging import getLogger

import aiohttp
from navconfig import config

from ..openai_base import OpenAIBaseClient
from ...models import AIMessage, AIMessageFactory, CompletionUsage
from parrot.observability.context import current_session_id, current_user_id
from .models import MetaModel

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = getLogger(__name__)


class _ToolCallFunction:
    """Chat-Completions-shaped ``function`` sub-object for a tool call."""

    def __init__(self, name: str | None, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    """Chat-Completions-shaped tool call, folded from a Responses
    ``function_call`` output item."""

    def __init__(self, tc_id: str, function: _ToolCallFunction) -> None:
        self.id = tc_id
        self.function = function


class _Message:
    """Chat-Completions-shaped ``choices[0].message`` compatibility shim."""

    def __init__(self, content: str, tool_calls: list[_ToolCall]) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    """Chat-Completions-shaped ``choices[0]`` compatibility shim."""

    def __init__(self, message: _Message, *, finish_reason: str | None = None) -> None:
        self.message = message
        self.finish_reason = finish_reason
        self.stop_reason = finish_reason


class _ResponsesCompatResult:
    """Chat-Completions-shaped adapter over a Responses API result.

    Lets the generic Chat-Completions machinery inherited from
    :class:`~parrot.clients.openai_base.OpenAIBaseClient`
    (``_run_tool_call_loop``, :class:`~parrot.models.responses.AIMessageFactory`)
    drive the Responses wire protocol unchanged — mirrors the
    ``_CompatResp``/``_Choice``/``_Msg`` pattern in
    ``OpenAIClient._responses_completion`` (``gpt.py:661-686``), read as a
    structural reference only.
    """

    def __init__(self, raw: Any, message: _Message, *, finish_reason: str | None = None) -> None:
        self.raw = raw
        self.choices = [_Choice(message, finish_reason=finish_reason)]
        # FEAT-397: Chat Completions and Responses usage objects are read
        # the same way downstream (getattr-based), even though the
        # Responses shape uses input_tokens/output_tokens rather than
        # prompt_tokens/completion_tokens — matches the existing gpt.py
        # Responses path, not "fixed" here (D1: mirror the structure).
        self.usage = getattr(raw, "usage", None)


class MetaClient(OpenAIBaseClient):
    """Client for Meta Model API (Muse Spark family).

    Args:
        api_key: Meta Model API key. Resolution order: ``api_key`` kwarg
            → ``META_API_KEY`` env var → ``MODEL_API_KEY`` env var. This
            chain MUST NOT fall through to ``OPENAI_API_KEY`` — the
            ``AsyncOpenAI`` SDK would otherwise silently pick that up and
            ship an OpenAI key to Meta.
        base_url: Override for Meta's API base URL. Defaults to
            ``https://api.meta.ai/v1``.
        use_responses: Whether to route ``ask()``/``ask_stream()`` through
            the Responses API (default) instead of the inherited Chat
            Completions funnel. Set ``False`` to use Chat Completions.
        **kwargs: Additional arguments passed to
            :class:`~parrot.clients.openai_base.OpenAIBaseClient`.

    Example:
        >>> client = MetaClient()
        >>> response = await client.ask("Hello!")
    """

    client_type: str = "meta"
    client_name: str = "meta"
    _default_model: str = MetaModel.MUSE_SPARK_1_3.value
    # Muse Spark is a reasoning model: a live one-word answer ("pong") spent
    # 199 of 210 completion tokens on reasoning. A conventional 60s timeout
    # is measurably too tight for heavier prompts.
    _default_timeout: float = 120.0

    # FEAT-523 discovery contract: every factory key this class answers to
    # (primary first), and the model catalog enum it owns.
    provider_keys: tuple[str, ...] = ("meta", "muse", "meta-muse")
    models: type[MetaModel] = MetaModel

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        use_responses: bool = True,
        **kwargs: Any,
    ) -> None:
        self.use_responses = use_responses
        resolved_key = api_key or config.get("META_API_KEY") or config.get("MODEL_API_KEY")
        super().__init__(
            api_key=resolved_key,
            base_url=base_url or "https://api.meta.ai/v1",
            **kwargs,
        )
        # Re-set after super().__init__ — AbstractClient may overwrite it.
        self.api_key = resolved_key

    async def get_client(self) -> "AsyncOpenAI":
        """Initialize AsyncOpenAI configured for Meta Model API.

        Returns:
            An ``AsyncOpenAI`` instance pointed at Meta's base URL, with
            the resolved Meta API key passed explicitly (never relying on
            the SDK's ``OPENAI_API_KEY`` default).

        Raises:
            ImportError: If the ``openai`` package is not installed.
        """
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "MetaClient requires the 'openai' SDK. " "Install with: pip install ai-parrot[openai]"
            ) from exc
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self._timeout,
        )

    async def list_models(self) -> list[dict[str, Any]]:
        """List available models from Meta Model API.

        Fetches the model catalog from ``GET /v1/models``.

        Returns:
            List of model dicts as returned by the endpoint's ``data`` key.

        Raises:
            aiohttp.ClientError: If the HTTP request fails.
        """
        url = f"{self.base_url}/models"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                data = await response.json()

        return data.get("data", [])

    # ------------------------------------------------------------------
    # Responses API path (D1: MetaClient-local; spec §3 Module 3).
    # ------------------------------------------------------------------

    def _fold_output(self, output: list[Any]) -> str:
        """Fold Responses API ``output[]`` items into visible text.

        Concatenates text from items whose ``type == "message"``, skipping
        ``reasoning`` items — their content is redacted to empty for
        external keys, and treating them as text yields blank output for a
        conventional-budget call (spec §7 gotchas 1 and 4).

        Args:
            output: The ``output`` list from a Responses API response — raw
                dicts, or SDK objects exposing the same shape via attributes.

        Returns:
            The concatenated visible text.
        """
        text = ""
        for item in output or []:
            item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if item_type != "message":
                continue
            content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            for part in content or []:
                if isinstance(part, dict):
                    if part.get("type") == "output_text":
                        text += part.get("text", "") or ""
                elif getattr(part, "type", None) == "output_text":
                    text += getattr(part, "text", "") or ""
        return text

    def _extract_tool_calls(self, output: list[Any]) -> list[_ToolCall]:
        """Extract Chat-Completions-shaped tool calls from ``output[]``.

        Maps Responses ``function_call`` output items to the same
        ``{id, function: {name, arguments}}`` shape the inherited
        ``_run_tool_call_loop`` and ``AIMessageFactory.from_openai`` expect
        from a Chat Completions response, so the same generic tool-execution
        loop drives both wire protocols unchanged.

        Args:
            output: The ``output`` list from a Responses API response.

        Returns:
            A list of :class:`_ToolCall` shims.
        """
        tool_calls: list[_ToolCall] = []
        for item in output or []:
            item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if item_type != "function_call":
                continue
            if isinstance(item, dict):
                call_id = item.get("call_id") or item.get("id")
                name = item.get("name")
                arguments = item.get("arguments")
            else:
                call_id = getattr(item, "call_id", None) or getattr(item, "id", None)
                name = getattr(item, "name", None)
                arguments = getattr(item, "arguments", None)
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments or {})
            tool_calls.append(
                _ToolCall(
                    tc_id=call_id or str(uuid.uuid4()),
                    function=_ToolCallFunction(name=name, arguments=arguments),
                )
            )
        return tool_calls

    @staticmethod
    def _to_responses_tool(tool: dict[str, Any]) -> dict[str, Any]:
        """Convert a Chat-Completions-shaped function tool to the Responses shape.

        Chat Completions nests the function definition:
        ``{"type": "function", "function": {"name", "description",
        "parameters", ...}}`` (what ``AbstractClient._prepare_tools()``
        always produces). The Responses API expects the same fields
        **flattened** onto the tool dict itself:
        ``{"type": "function", "name", "description", "parameters", ...}``
        — sending the nested Chat-Completions shape live 400s with
        ``'tools[0]' missing required field 'name'``.

        Non-function tools (e.g. ``{"type": "web_search"}``, already flat)
        pass through unchanged.

        Args:
            tool: A single tool dict, in either shape.

        Returns:
            The Responses-shaped tool dict.
        """
        if isinstance(tool, dict) and tool.get("type") == "function" and "function" in tool:
            function = tool["function"]
            flat: dict[str, Any] = {
                "type": "function",
                "name": function.get("name"),
                "description": function.get("description"),
                "parameters": function.get("parameters", {}),
            }
            if "strict" in function:
                flat["strict"] = function["strict"]
            return flat
        return tool

    def _prepare_responses_args(self, *, messages: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
        """Map a Chat-Completions-style message list into a Responses payload.

        Lifts the first ``system`` message into ``instructions``; the rest
        become the ``input`` list. Tool-call round trips are represented as
        top-level ``function_call``/``function_call_output`` input items —
        the *real*, live-verified Responses wire shape (NOT a
        ``role``/``content`` wrapper like Chat Completions; NOT the
        ``tool_output``/``tool_call`` content-block shape
        :class:`~parrot.clients.gpt.OpenAIClient` mirrors, which was tried
        first here and 400s live with ``'input[N].content' did not match
        any supported type`` — corrected during implementation).

        Args:
            messages: Chat-Completions-shaped message dicts.
            args: Chat-Completions-style extra kwargs (``tools``,
                ``tool_choice``, ``max_output_tokens`` or ``max_tokens``,
                ``temperature``, ...).

        Returns:
            A Responses API request payload (without ``model``).
        """

        def _text_content(role: str, content: Any) -> list[dict[str, Any]]:
            text_type = "input_text" if role in {"user", "system"} else "output_text"
            parts: list[dict[str, Any]] = []
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        item_type = item.get("type")
                        if item_type in {"input_text", "output_text"}:
                            parts.append(item)
                        elif item_type == "text":
                            text_val = item.get("text")
                            if text_val:
                                parts.append({"type": text_type, "text": str(text_val)})
                        else:
                            parts.append(item)
                    elif item:
                        parts.append({"type": text_type, "text": str(item)})
            elif content:
                parts.append({"type": text_type, "text": str(content)})
            return parts

        instructions = None
        input_msgs: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "system" and instructions is None:
                instructions = content if isinstance(content, str) else str(content)
                continue

            if role == "tool":
                # Real Responses input item for a tool result: a top-level
                # `function_call_output`, keyed by `call_id` — NOT a
                # `{"role": "tool", ...}` message wrapper.
                if isinstance(content, list):
                    output_text = "\n".join(
                        str(part) if not isinstance(part, dict) else str(part.get("text") or part.get("output") or "")
                        for part in content
                    )
                else:
                    output_text = "" if content is None else str(content)
                input_msgs.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.get("tool_call_id"),
                        "output": output_text,
                    }
                )
                continue

            if role == "assistant" and message.get("tool_calls"):
                # Real text (if any) first, then one top-level `function_call`
                # item per tool call — NOT nested inside the message content.
                if content:
                    input_msgs.append({"role": role, "content": _text_content(role, content)})
                for tool_call in message["tool_calls"]:
                    function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
                    input_msgs.append(
                        {
                            "type": "function_call",
                            "call_id": tool_call.get("id") if isinstance(tool_call, dict) else None,
                            "name": function.get("name"),
                            "arguments": function.get("arguments"),
                        }
                    )
                continue

            input_msgs.append({"role": role, "content": _text_content(role, content)})

        req: dict[str, Any] = {"input": input_msgs}
        if instructions:
            req["instructions"] = instructions
        if args.get("tools"):
            req["tools"] = [self._to_responses_tool(tool) for tool in args["tools"]]
        # Meta HTTP 400s on any tool_choice value other than "auto" (spec §7
        # gotcha 2) — never forward a caller-supplied override.
        if "tool_choice" in args:
            req["tool_choice"] = "auto"
        if args.get("temperature") is not None:
            req["temperature"] = args["temperature"]
        # Responses' output-budget parameter is `max_output_tokens`, not
        # Chat Completions' `max_tokens` (spec §7 gotcha 1 — Muse Spark
        # burns most of a small budget on hidden reasoning).
        max_output_tokens = args.get("max_output_tokens", args.get("max_tokens"))
        if max_output_tokens is not None:
            req["max_output_tokens"] = max_output_tokens
        return req

    async def _responses_completion(
        self, *, model: str, messages: list[dict[str, Any]], use_tools: bool = False, **args: Any
    ) -> _ResponsesCompatResult:
        """Call ``responses.create()`` and adapt the result to Chat-Completions shape.

        Args:
            model: The resolved model id.
            messages: The Chat-Completions-shaped message list.
            use_tools: Accepted for signature parity with
                :meth:`~parrot.clients.openai_base.OpenAIBaseClient._chat_completion`
                (the inherited ``_run_tool_call_loop`` calls both the same
                way); unused here, since tools are always forwarded via
                ``args["tools"]`` when present.
            **args: Additional Responses request kwargs (``tools``,
                ``tool_choice``, ``max_output_tokens``, ``temperature``).

        Returns:
            A :class:`_ResponsesCompatResult` exposing
            ``.choices[0].message.{content,tool_calls}`` and ``.usage``, so
            the generic Chat-Completions tool loop and
            ``AIMessageFactory.from_openai`` can consume it unchanged.
        """
        del use_tools  # see docstring
        await self._ensure_client()
        req = self._prepare_responses_args(messages=messages, args=args)
        req["model"] = model

        resp = await self.client.responses.create(**req)

        output = getattr(resp, "output", None)
        if output is None and isinstance(resp, dict):
            output = resp.get("output")
        output = output or []

        content = getattr(resp, "output_text", None)
        if content is None:
            content = self._fold_output(output)

        tool_calls = self._extract_tool_calls(output)
        message = _Message(content=content or "", tool_calls=tool_calls)

        status = getattr(resp, "status", None)
        if status is None and isinstance(resp, dict):
            status = resp.get("status")
        finish_reason = "incomplete" if status == "incomplete" else None

        return _ResponsesCompatResult(raw=resp, message=message, finish_reason=finish_reason)

    @staticmethod
    def _extract_cached_tokens(usage: Any) -> int | None:
        """Extract ``cached_tokens`` from either usage-details shape.

        Chat Completions reports it at ``usage.prompt_tokens_details.cached_tokens``;
        Responses reports the same value at
        ``usage.input_tokens_details.cached_tokens``. Prompt caching itself
        is automatic server-side — this is observability only (spec §1
        Non-Goals).

        Args:
            usage: The raw SDK usage object (or dict) from either wire shape.

        Returns:
            The cached-token count, or ``None`` if not present.
        """
        if usage is None:
            return None
        if isinstance(usage, dict):
            details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details")
        else:
            details = getattr(usage, "prompt_tokens_details", None) or getattr(usage, "input_tokens_details", None)
        if details is None:
            return None
        if isinstance(details, dict):
            return details.get("cached_tokens")
        return getattr(details, "cached_tokens", None)

    async def count_input_tokens(
        self, *, model: str | None = None, input: Any, **kwargs: Any
    ) -> int:  # noqa: A002 — spec-mandated parameter name
        """Count input tokens for a prospective Responses API request.

        Standalone endpoint (``POST /v1/responses/input_tokens``) — it does
        not depend on the generation path, only on the client's
        credentials and base URL, so it works regardless of
        ``self.use_responses``.

        Args:
            model: Model to count for, or ``None`` to use the configured one.
            input: The Responses-shaped ``input`` payload to count tokens for.
            **kwargs: Additional args forwarded to the SDK call (e.g.
                ``instructions``, ``tools``).

        Returns:
            The input token count.
        """
        await self._ensure_client()
        model_str = self._resolve_model(model)
        # `responses.input_tokens` is an SDK sub-resource (`AsyncInputTokens`),
        # not directly callable — the actual RPC is `.count(...)`. Verified
        # against the installed `openai` SDK during implementation; earlier
        # revisions of this method called `responses.input_tokens(...)`
        # directly, which raises `TypeError: 'AsyncInputTokens' object is
        # not callable`.
        resp = await self.client.responses.input_tokens.count(model=model_str, input=input, **kwargs)
        count = getattr(resp, "input_tokens", None)
        if count is None and isinstance(resp, dict):
            count = resp.get("input_tokens")
        return int(count) if count is not None else 0

    async def ask(
        self,
        prompt: str,
        model: Any | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        files: list[Any] | None = None,
        system_prompt: str | None = None,
        history: Any | None = None,
        structured_output: Any | None = None,
        tools: list[dict[str, Any]] | None = None,
        use_tools: bool | None = None,
        lazy_loading: bool = False,
        search_grounding: bool = False,
    ) -> AIMessage:
        """Ask Meta Model API a question, routing via ``use_responses``.

        When ``self.use_responses`` is ``False``, delegates unchanged to the
        inherited Chat Completions funnel
        (:meth:`~parrot.clients.openai_base.OpenAIBaseClient.ask`). When
        ``True`` (the default), routes to the Responses API via
        :meth:`_responses_completion`, reusing the same generic tool-call
        loop (:meth:`~parrot.clients.openai_base.OpenAIBaseClient._run_tool_call_loop`)
        so a full tool-calling round trip works on both paths.

        Keeps the base's signature exactly, plus the additive
        ``search_grounding`` keyword (spec §6/§7), so the funnel-parity
        sweep in ``tests/clients/test_openai_base_parity.py`` continues to
        pass.

        Args:
            prompt: The prompt to send to the model.
            model: The model to use, or ``None`` to use the configured one.
            max_tokens: Maximum output tokens (mapped to
                ``max_output_tokens`` on this path).
            temperature: Sampling temperature.
            files: Files to upload before the call.
            system_prompt: System prompt to prepend.
            history: Already-rendered conversation history.
            structured_output: Not yet supported on the Responses path;
                ignored when ``use_responses`` is ``True``.
            tools: Tools to register for this call.
            use_tools: Whether to use tools; defaults to ``self.enable_tools``.
            lazy_loading: If ``True``, enable dynamic tool searching.
            search_grounding: If ``True``, inject Meta's native web-search
                tool (``{"type": "web_search"}``) into the Responses
                request, enabling live retrieval grounding. Opt-in and
                ``False`` by default — it triggers live web requests and
                bills for extra model iterations. Requires
                ``self.use_responses`` (Responses-API only); citation/
                annotation extraction is explicitly NOT implemented — a
                verified-good grounded response returned empty
                ``annotations`` (spec §7 gotcha 5).

        Returns:
            The response from the model.

        Raises:
            ValueError: If ``search_grounding=True`` while
                ``self.use_responses`` is ``False``.
        """
        if search_grounding and not self.use_responses:
            raise ValueError(
                "search_grounding requires the Responses API path "
                "(use_responses=True); this client was configured with "
                "use_responses=False."
            )

        if not self.use_responses:
            return await super().ask(
                prompt,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                files=files,
                system_prompt=system_prompt,
                history=history,
                structured_output=structured_output,
                tools=tools,
                use_tools=use_tools,
                lazy_loading=lazy_loading,
            )

        turn_id = str(uuid.uuid4())
        original_prompt = prompt
        _use_tools = use_tools if use_tools is not None else self.enable_tools
        model_str = self._resolve_model(model)

        messages = self._build_messages(prompt, files, history)

        if system_prompt:
            if isinstance(system_prompt, list):
                system_prompt = "\n\n".join(s.text for s in system_prompt)
            messages.insert(0, {"role": "system", "content": system_prompt})

        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        active_tool_names: set[str] = set()
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

        if search_grounding:
            web_search_tool = {"type": "web_search"}
            existing_tools = args.get("tools") or []
            if web_search_tool not in existing_tools:
                args["tools"] = [*existing_tools, web_search_tool]
                args["tool_choice"] = "auto"

        resolved_max_tokens = self._resolve_max_tokens(max_tokens)
        if resolved_max_tokens is not None:
            args["max_output_tokens"] = resolved_max_tokens
        if temperature:
            args["temperature"] = temperature

        response = await self._responses_completion(model=model_str, messages=messages, use_tools=_use_tools, **args)
        result = response.choices[0].message

        result, response, all_tool_calls, accumulated_usage, round_number = await self._run_tool_call_loop(
            result=result,
            response=response,
            messages=messages,
            model_str=model_str,
            use_tools=_use_tools,
            args=args,
            session_id=current_session_id.get(),
            call_completion=self._responses_completion,
            lazy_loading=lazy_loading,
            active_tool_names=active_tool_names,
            track_usage=True,
        )

        messages.append({"role": "assistant", "content": result.content})

        ai_message = AIMessageFactory.from_openai(
            response=response,
            input_text=original_prompt,
            model=model_str,
            user_id=current_user_id.get(),
            session_id=current_session_id.get(),
            turn_id=turn_id,
        )

        if accumulated_usage is not None:
            if round_number > 1:
                accumulated_usage.extra_usage["rounds"] = round_number
            ai_message.usage = accumulated_usage

        ai_message.tool_calls = all_tool_calls

        # Surface web_search_call output items so callers can distinguish a
        # grounded answer from an ungrounded one. Deliberately NOT extracting
        # citations/annotations here — a verified-good grounded response
        # returned empty `annotations` (spec §7 gotcha 5); no promise the
        # API does not currently keep.
        raw_output = getattr(response.raw, "output", None)
        if raw_output is None and isinstance(response.raw, dict):
            raw_output = response.raw.get("output")
        web_search_call_ids = [
            (item.get("id") if isinstance(item, dict) else getattr(item, "id", None))
            for item in (raw_output or [])
            if (item.get("type") if isinstance(item, dict) else getattr(item, "type", None)) == "web_search_call"
        ]
        if web_search_call_ids:
            ai_message.metadata["web_search_calls"] = web_search_call_ids
            ai_message.metadata["search_grounded"] = True

        # Cached-token observability (spec §1 Non-Goal: caching itself is
        # automatic server-side; nothing to implement beyond surfacing it).
        raw_usage = getattr(response.raw, "usage", None)
        cached_tokens = self._extract_cached_tokens(raw_usage)
        if cached_tokens is not None:
            ai_message.usage.extra_usage["cached_tokens"] = cached_tokens

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: Any | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        files: list[Any] | None = None,
        system_prompt: str | None = None,
        history: Any | None = None,
        tools: list[dict[str, Any]] | None = None,
        use_tools: bool = True,
        structured_output: Any | None = None,
        lazy_loading: bool = False,
        **kwargs: Any,
    ):
        """Stream a response, routing via ``use_responses``.

        When ``self.use_responses`` is ``False``, delegates unchanged to the
        inherited Chat Completions streaming funnel. When ``True`` (the
        default), streams text deltas from the Responses API.

        Note:
            Unlike :meth:`ask`, the Responses streaming path here does not
            run a tool-calling round trip mid-stream — it yields the
            streamed text and a final :class:`~parrot.models.responses.AIMessage`.
            Use :meth:`ask` (``use_responses=True``) for a full tool-calling
            round trip on the Responses path.

        Yields:
            Successive string chunks, followed by a final
            :class:`~parrot.models.responses.AIMessage`.
        """
        if not self.use_responses:
            async for item in super().ask_stream(
                prompt,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                files=files,
                system_prompt=system_prompt,
                history=history,
                tools=tools,
                use_tools=use_tools,
                structured_output=structured_output,
                lazy_loading=lazy_loading,
                **kwargs,
            ):
                yield item
            return

        turn_id = str(uuid.uuid4())
        model_str = self._resolve_model(model)
        messages = self._build_messages(prompt, files, history)

        if system_prompt:
            if isinstance(system_prompt, list):
                system_prompt = "\n\n".join(s.text for s in system_prompt)
            messages.insert(0, {"role": "system", "content": system_prompt})

        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        tools_payload = None
        if use_tools and self.tools:
            if lazy_loading:
                tools_payload = self._prepare_lazy_tools()
            else:
                tools_payload = self._prepare_tools()

        args: dict[str, Any] = {}
        if tools_payload:
            args["tools"] = tools_payload
            args["tool_choice"] = "auto"

        resolved_max_tokens = self._resolve_max_tokens(max_tokens)
        if resolved_max_tokens is not None:
            args["max_output_tokens"] = resolved_max_tokens
        temperature_value = temperature if temperature is not None else self.temperature
        if temperature_value is not None:
            args["temperature"] = temperature_value

        await self._ensure_client()
        req = self._prepare_responses_args(messages=messages, args=args)
        req["model"] = model_str

        assistant_content = ""
        final_response = None
        stream_cm = self.client.responses.stream(**req)
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
            try:
                final_response = await stream.get_final_response()
            except Exception:  # noqa: BLE001 pylint: disable=broad-except
                final_response = None

        if final_response is not None and not assistant_content:
            output = getattr(final_response, "output", None)
            if output is None and isinstance(final_response, dict):
                output = final_response.get("output")
            assistant_content = self._fold_output(output or [])
            if assistant_content:
                yield assistant_content

        usage_obj = getattr(final_response, "usage", None) if final_response is not None else None
        usage = (
            CompletionUsage.from_openai(usage_obj)
            if usage_obj is not None
            else CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        )

        ai_message = AIMessage(
            input=prompt,
            output=assistant_content,
            response=assistant_content,
            model=model_str,
            provider=self.client_type,
            usage=usage,
            user_id=current_user_id.get(),
            session_id=current_session_id.get(),
            turn_id=turn_id,
        )
        yield ai_message
