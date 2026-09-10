"""GoogleCompatCodeDispatcher — LLMCodeDispatcher over Gemini's OpenAI-compatible endpoint (FEAT-549).

Two overrides beyond the client factory: ``_completion_args`` (reasoning_effort, no extra_body) and
``_tool_call_to_openai_dict`` (carry ``extra_content`` — Gemini 3 returns HTTP 400
"Function call is missing a thought_signature" otherwise; verified live 2026-09-10).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from parrot.clients.factory import LLMFactory  # verified: clients/factory.py:163
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher  # verified: dispatchers/llm.py:51
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile  # verified: models/llm.py:10


class GoogleCompatCodeDispatcher(LLMCodeDispatcher):
    """Gemini seat for the sdd_coder kernel and the dev-loop pool."""

    def __init__(self, *, max_concurrent: int, redis_url: str, stream_ttl_seconds: int) -> None:
        super().__init__(
            max_concurrent=max_concurrent,
            redis_url=redis_url,
            stream_ttl_seconds=stream_ttl_seconds,
            client_factory=self._create_compat_client,
        )
        self.logger = logging.getLogger(__name__)

    def _create_compat_client(self, llm: str, *, model_args: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
        """Build ``GeminiOpenAICompatClient`` for ``llm='google-compat:<model>'`` (lazy provider import, FEAT-523 AC-3)."""
        from parrot.clients.google.openai_compat import GeminiOpenAICompatClient  # noqa: PLC0415 — provider import stays lazy

        _provider, model = LLMFactory.parse_llm_string(llm)
        init_params: Dict[str, Any] = {}
        if model:
            init_params["model"] = model
        for key in ("temperature", "max_tokens"):
            if model_args and model_args.get(key) is not None:
                init_params[key] = model_args[key]
        init_params.update(kwargs)
        return GeminiOpenAICompatClient(**init_params)

    def _completion_args(self, profile: LLMCodeDispatchProfile, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """super() minus ``extra_body`` (ignored by Google) plus ``reasoning_effort`` from the profile."""
        args = super()._completion_args(profile, tools)
        args.pop("extra_body", None)
        args["reasoning_effort"] = getattr(profile, "reasoning_effort", "none")
        return args

    def _tool_call_to_openai_dict(self, call: Any, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """super() dict + ``extra_content`` copied verbatim when the raw call carries it (thought_signature)."""
        rendered = super()._tool_call_to_openai_dict(call, arguments)
        extra = call.get("extra_content") if isinstance(call, dict) else getattr(call, "extra_content", None)
        if extra:
            if isinstance(extra, BaseModel):
                extra = extra.model_dump()
            rendered["extra_content"] = extra
        return rendered
