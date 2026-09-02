"""GrokCodeDispatcher — local coding-agent loop for xAI Grok Build models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from parrot.clients.factory import LLMFactory
from parrot.flows.dev_loop.dispatchers._shared import T
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.models import (
    DispatchLabels,
    GrokCodeDispatchProfile,
    LLMCodeDispatchProfile,
)
from parrot.flows.dev_loop.session_state import SessionHost


class GrokCodeDispatcher(LLMCodeDispatcher):
    """Local coding-agent loop tailored for Grok client and Grok Build model.

    Extends LLMCodeDispatcher to leverage the local OpenAI-compatible tool loop
    while binding to the custom `GrokClient` via LLMFactory and xAI SDK.
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

    async def _chat_completion(
        self,
        *,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        args: Dict[str, Any],
    ) -> Any:
        await client._ensure_client()
        return await client.client.chat.completions.create(
            model=model,
            messages=messages,
            **args,
        )

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: GrokCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
        labels: Optional[DispatchLabels] = None,
    ) -> T:
        llm_profile = LLMCodeDispatchProfile(
            subagent=profile.subagent,
            llm=f"grok:{profile.model}",
            sandbox=profile.sandbox,
            approval_policy=profile.approval_policy,
            timeout_seconds=profile.timeout_seconds,
            max_turns=profile.max_turns,
            max_tokens=profile.max_tokens,
            temperature=profile.temperature,
            command_timeout_seconds=profile.command_timeout_seconds,
            allowed_commands=profile.allowed_commands,
        )
        return await super().dispatch(
            brief=brief,
            profile=llm_profile,
            output_model=output_model,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
            labels=labels,
        )

