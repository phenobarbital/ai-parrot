"""Moonshot (Kimi) client for AI-Parrot.

Extends OpenAIClient to route requests through Moonshot's OpenAI-compatible
API at https://api.moonshot.ai/v1.

Most completion, streaming, tool-calling, retry, and invoke logic is
inherited from OpenAIClient unchanged. MoonshotClient overrides only what
Moonshot requires:

- ``__init__`` resolves ``MOONSHOT_API_KEY`` and sets the Moonshot base URL.
- ``_chat_completion`` strips fixed sampling parameters for K-series models,
  injects thinking-mode ``extra_body`` (``reasoning_effort`` for K3,
  ``thinking`` dict for K2.6, always-on for K2.7-code), translates
  ``max_tokens`` to ``max_completion_tokens``, and injects
  ``prompt_cache_key`` when configured.
- ``ask`` / ``ask_stream`` accept ``thinking`` and ``reasoning_effort``
  keywords and propagate them to ``_chat_completion`` via a context
  variable (NvidiaClient pattern).
"""
import contextvars
from typing import Any, AsyncIterator, Dict, Optional, Union

from navconfig import config
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..models import AIMessage
from .gpt import OpenAIClient
from ..models.moonshot import (
    MoonshotModel,
    K_SERIES_MODELS,
    ALWAYS_THINKING_MODELS,
    REASONING_EFFORT_MODELS,
    THINKING_DICT_MODELS,
)

# Context variable that carries thinking / reasoning_effort flags from
# ask / ask_stream down to _chat_completion without altering the parent's
# call signatures. Using a ContextVar is safe for concurrent async calls
# because each asyncio Task inherits an isolated copy of the context.
_thinking_ctx: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "_moonshot_thinking_ctx", default={}
)

# Fixed sampling parameters that K-series models reject.
_PARAMS_TO_STRIP = frozenset({
    "temperature", "top_p", "n", "presence_penalty", "frequency_penalty",
})


class MoonshotClient(OpenAIClient):
    """Client for Moonshot's (Kimi) OpenAI-compatible API.

    Routes all requests through ``https://api.moonshot.ai/v1`` and resolves
    the API key from the constructor argument or the ``MOONSHOT_API_KEY``
    environment variable (via ``navconfig.config``).

    All inherited OpenAI machinery — ``ask``, ``ask_stream``, ``invoke``,
    tool calling, structured output, and retry — works with minor Moonshot
    adjustments applied in ``_chat_completion``.

    K-series models (``kimi-k3``, ``kimi-k2.7-code``,
    ``kimi-k2.7-code-highspeed``, ``kimi-k2.6``) have fixed sampling
    parameters — ``temperature``, ``top_p``, ``n``, ``presence_penalty``,
    and ``frequency_penalty`` are stripped from requests targeting them.

    Thinking mode is tri-modal:

    - ``kimi-k3``: ``reasoning_effort`` (via ``extra_body``).
    - ``kimi-k2.6``: ``thinking`` dict (via ``extra_body``).
    - ``kimi-k2.7-code`` / ``kimi-k2.7-code-highspeed``: always-on, no
      parameter needed.

    Args:
        api_key: Moonshot API key. Falls back to ``MOONSHOT_API_KEY`` env
            var (resolved via ``navconfig.config``).
        prompt_cache_key: Optional session-based cache key injected into
            every request body.
        **kwargs: Additional arguments passed to ``OpenAIClient`` /
            ``AbstractClient``.

    Example::

        client = MoonshotClient(model=MoonshotModel.KIMI_K3)
        response = await client.ask(
            "Explain gradient descent.",
            reasoning_effort="max",
        )
    """

    client_type: str = "moonshot"
    client_name: str = "moonshot"
    _default_model: str = MoonshotModel.KIMI_K2_6.value
    _fallback_model: str = MoonshotModel.MOONSHOT_V1_128K.value
    _min_cache_tokens: int = 0  # automatic caching, no explicit threshold

    def __init__(
        self,
        api_key: Optional[str] = None,
        prompt_cache_key: Optional[str] = None,
        **kwargs,
    ) -> None:
        resolved_key = api_key or config.get("MOONSHOT_API_KEY")
        super().__init__(
            api_key=resolved_key,
            base_url="https://api.moonshot.ai/v1",
            **kwargs,
        )
        # Re-set after super().__init__ because AbstractClient may overwrite
        # self.api_key during its own initialisation. This mirrors the guard
        # used by NvidiaClient (nvidia.py:84) / OpenRouterClient (openrouter.py:75).
        self.api_key = resolved_key
        self.prompt_cache_key = prompt_cache_key

    @staticmethod
    def _sanitize_params_for_model(model: str, kwargs: dict) -> dict:
        """Strip fixed sampling parameters for K-series models.

        Args:
            model: Model identifier string.
            kwargs: Request kwargs to sanitize in place.

        Returns:
            The same ``kwargs`` dict, with fixed sampling parameters removed
            when ``model`` is a K-series model.
        """
        if model in K_SERIES_MODELS:
            for param in _PARAMS_TO_STRIP:
                kwargs.pop(param, None)
        return kwargs

    async def _chat_completion(
        self,
        model: str,
        messages: Any,
        use_tools: bool = False,
        **kwargs,
    ) -> Any:
        """Run a chat completion against Moonshot via ``create()``.

        Moonshot-specific differences from ``OpenAIClient._chat_completion``:

        1. Always uses ``client.chat.completions.create``. Moonshot, like
           Nvidia NIM, may not support the OpenAI SDK's ``parse()``
           shortcut, so we never route through it — even when ``use_tools``
           is ``False``.
        2. Strips fixed sampling parameters for K-series models.
        3. Injects thinking-mode ``extra_body`` per the flags set by
           ``ask`` / ``ask_stream`` via the async context variable.
        4. Translates ``max_tokens`` to ``max_completion_tokens``.
        5. Injects ``prompt_cache_key`` when configured.

        Args:
            model: Model identifier string.
            messages: Chat messages list.
            use_tools: Whether tools are enabled (kept for parity with parent).
            **kwargs: Additional completion arguments forwarded to the
                OpenAI SDK.

        Returns:
            Raw OpenAI ``ChatCompletion`` response.
        """
        from openai import APIConnectionError, APIError, RateLimitError

        kwargs = self._sanitize_params_for_model(model, kwargs)

        thinking = _thinking_ctx.get()
        if model in REASONING_EFFORT_MODELS:
            # K3: uses reasoning_effort
            effort = thinking.get("reasoning_effort") or "max"
            extra = dict(kwargs.get("extra_body") or {})
            extra["reasoning_effort"] = effort
            kwargs["extra_body"] = extra
        elif model in THINKING_DICT_MODELS:
            # K2.6: uses thinking dict
            thinking_val = thinking.get("thinking")
            if thinking_val is not None:
                extra = dict(kwargs.get("extra_body") or {})
                if isinstance(thinking_val, bool):
                    extra["thinking"] = {
                        "type": "enabled" if thinking_val else "disabled"
                    }
                elif isinstance(thinking_val, dict):
                    extra["thinking"] = thinking_val
                kwargs["extra_body"] = extra
        # K2.7-code / K2.7-code-highspeed: always-on — no injection needed
        _ = model in ALWAYS_THINKING_MODELS

        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

        if self.prompt_cache_key:
            kwargs.setdefault("prompt_cache_key", self.prompt_cache_key)

        retry_policy = AsyncRetrying(
            retry=retry_if_exception_type(
                (APIConnectionError, RateLimitError, APIError)
            ),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(3),
            reraise=True,
        )
        async for attempt in retry_policy:
            with attempt:
                return await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    **kwargs,
                )

    async def ask(
        self,
        prompt: str,
        *,
        thinking: Optional[Union[bool, Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> AIMessage:
        """Submit a prompt and return the full response.

        Identical to ``OpenAIClient.ask`` with additional ``thinking`` and
        ``reasoning_effort`` shortcuts that inject Moonshot's thinking-mode
        parameters into ``extra_body`` for reasoning-capable models.

        The flags are forwarded to ``_chat_completion`` via an async context
        variable, so the parent's call signature is preserved.

        Args:
            prompt: User message text.
            thinking: For ``kimi-k2.6``. ``True``/``False`` shortcut for
                ``{"type": "enabled"/"disabled"}``, or an explicit dict.
            reasoning_effort: For ``kimi-k3``. Effort level string (e.g.
                ``"max"``).
            **kwargs: All other keyword arguments delegated to
                ``OpenAIClient.ask`` (e.g. ``model``, ``temperature``,
                ``system_prompt``, ``session_id``).

        Returns:
            AIMessage with the model response.
        """
        kwargs.setdefault("model", self.model or self._default_model)
        token = _thinking_ctx.set(
            {"thinking": thinking, "reasoning_effort": reasoning_effort}
        )
        try:
            return await super().ask(prompt, **kwargs)
        finally:
            _thinking_ctx.reset(token)

    async def ask_stream(
        self,
        prompt: str,
        *,
        thinking: Optional[Union[bool, Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Submit a prompt and stream response chunks.

        Identical to ``OpenAIClient.ask_stream`` with the same ``thinking``
        and ``reasoning_effort`` shortcuts as ``ask``.

        The flags are forwarded to ``_chat_completion`` via an async context
        variable, so the parent's call signature is preserved.

        Args:
            prompt: User message text.
            thinking: For ``kimi-k2.6``. ``True``/``False`` shortcut for
                ``{"type": "enabled"/"disabled"}``, or an explicit dict.
            reasoning_effort: For ``kimi-k3``. Effort level string (e.g.
                ``"max"``).
            **kwargs: All other keyword arguments delegated to
                ``OpenAIClient.ask_stream`` (e.g. ``model``, ``temperature``,
                ``system_prompt``, ``session_id``).

        Yields:
            Response text chunks (same shape as ``OpenAIClient.ask_stream``).
        """
        kwargs.setdefault("model", self.model or self._default_model)
        token = _thinking_ctx.set(
            {"thinking": thinking, "reasoning_effort": reasoning_effort}
        )
        try:
            async for chunk in super().ask_stream(prompt, **kwargs):
                yield chunk
        finally:
            _thinking_ctx.reset(token)
