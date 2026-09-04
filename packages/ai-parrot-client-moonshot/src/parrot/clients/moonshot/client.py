"""Moonshot (Kimi) client for AI-Parrot.

Extends OpenAIBaseClient (FEAT-438) to route requests through Moonshot's
OpenAI-compatible API at https://api.moonshot.ai/v1.

Most completion, streaming, tool-calling, retry, and invoke logic is
inherited from OpenAIBaseClient unchanged. MoonshotClient overrides what
Moonshot requires:

- ``__init__`` resolves ``MOONSHOT_API_KEY`` and sets the Moonshot base URL.
- ``_chat_completion`` strips fixed sampling parameters for K-series models,
  injects thinking-mode ``extra_body`` (``reasoning_effort`` for K3,
  ``thinking`` dict for K2.6, always-on for K2.7-code), translates
  ``max_tokens`` to ``max_completion_tokens``, and injects
  ``prompt_cache_key`` when configured.
- ``ask`` / ``ask_stream`` accept ``thinking`` and ``reasoning_effort``
  keywords and propagate them to ``_chat_completion`` via a context
  variable (NvidiaClient pattern), and post-process the returned
  ``AIMessage``(s) to surface ``reasoning_content`` into
  ``metadata["reasoning_content"]`` (mirroring ``ZaiClient``'s pattern,
  since ``AIMessageFactory.from_openai`` does not extract it).

RESOLVED LIMITATION (FEAT-311 code review follow-up; fixed by FEAT-438
TASK-2298/2300): ``OpenAIClient.ask_stream()``'s Chat-Completions branch and
``OpenAIClient.invoke()`` used to call ``self.client.chat.completions.
create()`` directly, never routing through the overridden
``_chat_completion()`` — so the sanitize/thinking-injection/
``max_completion_tokens``/``prompt_cache_key`` logic never ran for
streaming or invoke, and K-series models (which reject a non-``null``
``temperature``) needed workarounds on both paths. FEAT-438's completion
funnel (``_chat_completion`` is now the single seam every call routes
through) closes this gap: both paths now go through this module's
``_chat_completion`` override, which already strips ``temperature`` (and
the other fixed sampling params) for K-series models — so the former
``ask_stream()`` temperature-neutralization hack and the former
``invoke()`` K-series guard/``ValueError`` are both gone; ``invoke()`` is
no longer overridden at all (inherited from ``OpenAIBaseClient`` unchanged)
and K-series models now work through it instead of raising.
"""
import contextvars
from enum import Enum
from typing import Any, AsyncIterator, Dict, Optional, Union

from navconfig import config
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ...models import AIMessage
from ..openai_base import OpenAIBaseClient
from .models import (
    MoonshotModel,
    K_SERIES_MODELS,
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


class MoonshotClient(OpenAIBaseClient):
    """Client for Moonshot's (Kimi) OpenAI-compatible API.

    Routes all requests through ``https://api.moonshot.ai/v1`` and resolves
    the API key from the constructor argument or the ``MOONSHOT_API_KEY``
    environment variable (via ``navconfig.config``).

    All inherited OpenAI-wire machinery — ``ask``, ``ask_stream``,
    ``invoke``, tool calling, structured output, and retry — works with
    minor Moonshot adjustments applied in ``_chat_completion``, which now
    covers every one of those paths (FEAT-438's single completion funnel).

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
        **kwargs: Additional arguments passed to ``OpenAIBaseClient`` /
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

    # FEAT-523 folder-convention attributes (read by LLMFactory).
    provider_keys: tuple[str, ...] = ("moonshot", "kimi")
    models: type[Enum] = MoonshotModel
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

    @staticmethod
    def _capture_reasoning_content(message: AIMessage) -> None:
        """Surface ``reasoning_content`` from the raw SDK response into metadata.

        ``OpenAIBaseClient.ask()``/``ask_stream()`` build their ``AIMessage`` via
        ``AIMessageFactory.from_openai()``, which does not extract
        ``reasoning_content`` from the response (unlike ``ZaiClient``, which
        hand-builds its ``AIMessage`` and does the extraction itself — see
        ``zai.py:256-260``). K-series models return ``reasoning_content``
        (spec §7), so this mutates ``message.metadata`` in place using the
        same ``getattr(message, "reasoning_content", None)`` idiom, applied
        to the already-serialized ``raw_response`` dict.

        This is a no-op when ``raw_response`` is absent/empty or carries no
        ``reasoning_content`` (e.g. legacy non-reasoning models).

        Args:
            message: The ``AIMessage`` to mutate in place.
        """
        raw = getattr(message, "raw_response", None)
        if not raw:
            return
        choices = raw.get("choices") or []
        if not choices:
            return
        first_choice = choices[0] or {}
        choice_message = first_choice.get("message") or {}
        reasoning_content = choice_message.get("reasoning_content")
        if reasoning_content:
            message.metadata["reasoning_content"] = reasoning_content

    async def _chat_completion(
        self,
        model: str,
        messages: Any,
        use_tools: bool = False,
        **kwargs,
    ) -> Any:
        """Run a chat completion against Moonshot via ``create()``.

        Moonshot-specific differences from ``OpenAIBaseClient._chat_completion``:

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
            effort = thinking.get("reasoning_effort")
            if effort is None:
                effort = "max"
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
        # K2.7-code / K2.7-code-highspeed (ALWAYS_THINKING_MODELS): always-on
        # server-side — no client-supplied parameter is needed or injected.

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

        Identical to ``OpenAIBaseClient.ask`` with additional ``thinking`` and
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
                ``OpenAIBaseClient.ask`` (e.g. ``model``, ``temperature``,
                ``system_prompt``, ``session_id``).

        Returns:
            AIMessage with the model response. When the model returned
            ``reasoning_content``, it is captured in
            ``metadata["reasoning_content"]`` (see
            ``_capture_reasoning_content``).
        """
        kwargs.setdefault("model", self.model or self._default_model)
        token = _thinking_ctx.set(
            {"thinking": thinking, "reasoning_effort": reasoning_effort}
        )
        try:
            result = await super().ask(prompt, **kwargs)
        finally:
            _thinking_ctx.reset(token)
        self._capture_reasoning_content(result)
        return result

    async def ask_stream(
        self,
        prompt: str,
        *,
        thinking: Optional[Union[bool, Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Submit a prompt and stream response chunks.

        Identical to ``OpenAIBaseClient.ask_stream`` with the same
        ``thinking`` and ``reasoning_effort`` shortcuts as ``ask``.

        FEAT-438 TASK-2300: the K-series temperature-neutralization
        workaround this method used to carry (see the module-level
        "RESOLVED LIMITATION" note) is gone — ``ask_stream()`` now routes
        through ``_chat_completion`` (the completion funnel, TASK-2298),
        so this module's own ``_chat_completion`` override already strips
        ``temperature`` for K-series models. The ``thinking``/
        ``reasoning_effort`` injection and ``max_completion_tokens``/
        ``prompt_cache_key`` handling in ``_chat_completion`` now apply to
        streaming too — previously they did not.

        Args:
            prompt: User message text.
            thinking: For ``kimi-k2.6``. ``True``/``False`` shortcut for
                ``{"type": "enabled"/"disabled"}``, or an explicit dict.
            reasoning_effort: For ``kimi-k3``. Effort level string (e.g.
                ``"max"``).
            **kwargs: All other keyword arguments delegated to
                ``OpenAIBaseClient.ask_stream`` (e.g. ``model``,
                ``temperature``, ``system_prompt``, ``session_id``).

        Yields:
            Response text chunks, then a final
            :class:`~parrot.models.responses.AIMessage` (same shape as
            ``OpenAIBaseClient.ask_stream``). When the final message carries
            ``reasoning_content``, it is captured in
            ``metadata["reasoning_content"]``.
        """
        kwargs.setdefault("model", self.model or self._default_model)

        token = _thinking_ctx.set(
            {"thinking": thinking, "reasoning_effort": reasoning_effort}
        )
        try:
            async for chunk in super().ask_stream(prompt, **kwargs):
                if isinstance(chunk, AIMessage):
                    self._capture_reasoning_content(chunk)
                yield chunk
        finally:
            _thinking_ctx.reset(token)

    # invoke() override deleted (FEAT-438 TASK-2300) — it existed solely to
    # guard K-series models against OpenAIClient.invoke()'s fixed
    # temperature, which bypassed _chat_completion entirely (see the
    # module-level "RESOLVED LIMITATION" note). Now that invoke() routes
    # through _chat_completion (the completion funnel, TASK-2298), this
    # module's own _chat_completion override already strips temperature
    # for K-series models — invoke() is inherited from OpenAIBaseClient
    # unchanged, and K-series models work through it instead of raising.
