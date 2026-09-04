"""MoonshotCodeDispatcher — local coding-agent loop bound to ``MoonshotClient`` / kimi-k3."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from parrot.clients.factory import LLMFactory
from parrot.clients.moonshot.client import _thinking_ctx as _moonshot_thinking_ctx
from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError, T
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.models import DispatchLabels, MoonshotCodeDispatchProfile
from parrot.flows.dev_loop.session_state import SessionHost
from parrot.clients.moonshot.models import ALWAYS_THINKING_MODELS, K_SERIES_MODELS


class MoonshotCodeDispatcher(LLMCodeDispatcher):
    """Local coding-agent loop bound to ``MoonshotClient`` / kimi-k3.

    Extends ``LLMCodeDispatcher`` to reuse the inherited local tool loop,
    Redis event streaming, cwd-safety guard, and output validation, while
    overriding the completion-args and chat-completion hooks so requests
    route through ``MoonshotClient._chat_completion`` — which strips the
    fixed sampling parameters K-series models reject, translates
    ``max_tokens`` to ``max_completion_tokens``, and injects the
    thinking-mode ``extra_body`` (``reasoning_effort`` for kimi-k3,
    ``thinking`` dict for kimi-k2.6) — instead of emitting the
    Nvidia-style ``extra_body.chat_template_kwargs`` block used by the
    base class.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
    ) -> None:
        super().__init__(
            max_concurrent=max_concurrent,
            redis_url=redis_url,
            stream_ttl_seconds=stream_ttl_seconds,
            client_factory=lambda model, **kw: LLMFactory.create(model, **kw),
        )

    def _completion_args(
        self,
        profile: MoonshotCodeDispatchProfile,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build Moonshot-native completion args.

        Omits ``temperature`` for K-series models (fixed sampling
        parameters — the API rejects a non-null value) and never emits
        ``extra_body`` / ``chat_template_kwargs`` (Nvidia-only concept).
        The ``thinking`` / ``reasoning_effort`` markers are consumed by
        :meth:`_chat_completion`, which forwards them to
        ``MoonshotClient._chat_completion`` via the client's thinking
        context variable so the model-family-specific ``extra_body``
        injection happens in one place.
        """
        args: Dict[str, Any] = {
            "tools": tools,
            "tool_choice": "auto",
            # Read from the profile (default True): one turn per tool call
            # is what made whole tasks die against `max_turns`.
            "parallel_tool_calls": getattr(profile, "parallel_tool_calls", True),
            "max_tokens": profile.max_tokens,
        }
        _provider, model = LLMFactory.parse_llm_string(profile.llm)
        if profile.temperature is not None and model not in K_SERIES_MODELS:
            args["temperature"] = profile.temperature
        if not profile.enable_thinking and model in ALWAYS_THINKING_MODELS:
            self.logger.warning(
                "Moonshot model %s reasons unconditionally; " "enable_thinking=False has no effect.",
                model,
            )
        args["thinking"] = profile.enable_thinking
        args["reasoning_effort"] = profile.reasoning_effort
        return args

    async def _chat_completion(
        self,
        *,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        args: Dict[str, Any],
    ) -> Any:
        args = dict(args)
        thinking_flags = {
            "thinking": args.pop("thinking", None),
            "reasoning_effort": args.pop("reasoning_effort", None),
        }
        method = getattr(client, "_chat_completion", None)
        if not callable(method):
            raise DispatchExecutionError(f"Client {type(client).__name__} does not expose chat completion")
        token = _moonshot_thinking_ctx.set(thinking_flags)
        try:
            return await method(
                model=model,
                messages=messages,
                use_tools=True,
                **args,
            )
        finally:
            _moonshot_thinking_ctx.reset(token)

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: MoonshotCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
        labels: Optional[DispatchLabels] = None,
    ) -> T:
        return await super().dispatch(
            brief=brief,
            profile=profile,
            output_model=output_model,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
            labels=labels,
        )
