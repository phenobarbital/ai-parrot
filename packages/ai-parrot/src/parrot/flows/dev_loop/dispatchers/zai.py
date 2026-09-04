"""ZaiCodeDispatcher — local coding-agent loop bound to ``ZaiClient`` / GLM-5.2."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from parrot.clients.factory import LLMFactory
from parrot.flows.dev_loop.dispatchers._shared import T
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.models import DispatchLabels, ZaiCodeDispatchProfile
from parrot.flows.dev_loop.session_state import SessionHost
from parrot.clients.zai.models import THINKING_CAPABLE_ZAI_MODELS


class ZaiCodeDispatcher(LLMCodeDispatcher):
    """Local coding-agent loop bound to ``ZaiClient`` / GLM-5.2.

    Extends ``LLMCodeDispatcher`` to reuse the inherited local tool loop,
    Redis event streaming, cwd-safety guard, and output validation, while
    overriding the completion-args and chat-completion hooks so requests
    carry Z.ai-native ``thinking``/``reasoning_effort`` parameters instead
    of the Nvidia-style ``extra_body.chat_template_kwargs`` block emitted
    by the base class.
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
        profile: ZaiCodeDispatchProfile,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build Z.ai-native completion args.

        Emits ``thinking={"type": "enabled"|"disabled"}`` and
        ``reasoning_effort`` per ``profile``. Never emits ``extra_body`` /
        ``chat_template_kwargs`` (Nvidia-only concept, not understood by
        Z.ai). Logs a warning (but still dispatches) when thinking is
        requested for a model outside ``THINKING_CAPABLE_ZAI_MODELS``.
        """
        args: Dict[str, Any] = {
            "tools": tools,
            "tool_choice": "auto",
            # Read from the profile (default True): one turn per tool call
            # is what made whole tasks die against `max_turns`.
            "parallel_tool_calls": getattr(profile, "parallel_tool_calls", True),
            "max_tokens": profile.max_tokens,
        }
        if profile.temperature is not None:
            args["temperature"] = profile.temperature

        _provider, model = LLMFactory.parse_llm_string(profile.llm)
        if profile.enable_thinking and model not in THINKING_CAPABLE_ZAI_MODELS:
            self.logger.warning(
                "Z.ai thinking requested for model %s, which is not in the " "known thinking-capable set.",
                model,
            )
        args["thinking"] = {"type": "enabled" if profile.enable_thinking else "disabled"}
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
        sdk = await client._ensure_client()
        return await asyncio.to_thread(
            sdk.chat.completions.create,
            model=model,
            messages=messages,
            **args,
        )

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: ZaiCodeDispatchProfile,
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
