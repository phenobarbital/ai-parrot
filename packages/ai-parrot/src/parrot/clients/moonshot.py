"""Moonshot (Kimi) client for AI-Parrot.

Extends OpenAIClient to route requests through Moonshot's OpenAI-compatible
API at https://api.moonshot.ai/v1.

Most completion, streaming, tool-calling, retry, and invoke logic is
inherited from OpenAIClient unchanged. MoonshotClient overrides what
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
- ``invoke`` guards against K-series models, which reject the fixed
  ``temperature`` that ``OpenAIClient.invoke()`` always sends
  unconditionally (see the KNOWN LIMITATIONS note below).

KNOWN LIMITATIONS (FEAT-311 code review follow-up):
    ``OpenAIClient.ask_stream()``'s Chat-Completions branch and
    ``OpenAIClient.invoke()`` both call
    ``self.client.chat.completions.create()`` **directly**, never routing
    through the overridden ``_chat_completion()``. This means, on those two
    paths, ``max_completion_tokens`` translation, thinking-mode ``extra_body``
    injection, and ``prompt_cache_key`` injection do not apply:

    - ``ask_stream()``: the actual API-rejecting bug (K-series models
      reject a non-``null`` ``temperature``, which ``OpenAIClient`` sends
      by default) is mitigated below by neutralizing ``self.temperature``
      for the duration of K-series calls. The remaining gaps
      (``max_completion_tokens``/``prompt_cache_key``/thinking injection)
      are not hard failures (Moonshot's API is documented as accepting
      legacy ``max_tokens``) and are left as a tracked follow-up.
    - ``invoke()``: there is no ``None``-based omission path at all (unlike
      ``ask_stream()``), so the fixed ``temperature`` cannot be
      neutralized from the outside. K-series models are rejected up front
      with a clear ``ValueError`` rather than silently sending a doomed
      request — use ``ask()``/``ask_stream()`` for K-series models instead.

    A proper fix requires widening ``OpenAIClient.ask_stream()`` /
    ``OpenAIClient.invoke()`` to route through ``_chat_completion()`` (or
    otherwise accept an ``extra_body``/kwargs passthrough) — shared code
    affecting every OpenAI-compatible-gateway client (Nvidia, Moonshot),
    out of this module's scope.
"""
from enum import Enum
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

    All inherited OpenAI machinery — ``ask``, ``ask_stream``, tool calling,
    structured output, and retry — works with minor Moonshot adjustments
    applied in ``_chat_completion``. See the module-level "KNOWN
    LIMITATIONS" note for the ``ask_stream()``/``invoke()`` caveats.

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

    @staticmethod
    def _capture_reasoning_content(message: AIMessage) -> None:
        """Surface ``reasoning_content`` from the raw SDK response into metadata.

        ``OpenAIClient.ask()``/``ask_stream()`` build their ``AIMessage`` via
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

        Identical to ``OpenAIClient.ask_stream`` with the same ``thinking``
        and ``reasoning_effort`` shortcuts as ``ask``, plus a K-series safety
        net: ``OpenAIClient.ask_stream()``'s Chat-Completions branch calls
        ``self.client.chat.completions.create()`` directly and never routes
        through the overridden ``_chat_completion()``, so the sanitize /
        thinking-injection / ``max_completion_tokens`` / ``prompt_cache_key``
        logic there never runs for streaming. K-series models reject a
        non-``null`` ``temperature`` (the parameter ``OpenAIClient`` sends by
        default), so this method neutralizes ``self.temperature`` for the
        duration of K-series calls to avoid a doomed request. See the
        module-level "KNOWN LIMITATIONS" note for what remains unaddressed
        on this path (``max_completion_tokens`` translation, thinking-mode
        ``extra_body`` injection, ``prompt_cache_key``).

        Args:
            prompt: User message text.
            thinking: For ``kimi-k2.6``. ``True``/``False`` shortcut for
                ``{"type": "enabled"/"disabled"}``, or an explicit dict.
                Not applied on this path — see the module-level "KNOWN
                LIMITATIONS" note.
            reasoning_effort: For ``kimi-k3``. Effort level string (e.g.
                ``"max"``). Not applied on this path — see the module-level
                "KNOWN LIMITATIONS" note.
            **kwargs: All other keyword arguments delegated to
                ``OpenAIClient.ask_stream`` (e.g. ``model``, ``temperature``,
                ``system_prompt``, ``session_id``).

        Yields:
            Response text chunks, then a final
            :class:`~parrot.models.responses.AIMessage` (same shape as
            ``OpenAIClient.ask_stream``). When the final message carries
            ``reasoning_content``, it is captured in
            ``metadata["reasoning_content"]``.
        """
        kwargs.setdefault("model", self.model or self._default_model)
        model_value = kwargs["model"]
        if isinstance(model_value, Enum):
            model_value = model_value.value

        saved_temperature = self.temperature
        if model_value in K_SERIES_MODELS:
            # K-series models reject a non-null `temperature`.
            # OpenAIClient.ask_stream() always sends
            # `temperature if temperature is not None else self.temperature`,
            # so neutralizing the instance default here is the only way to
            # omit it from this call without modifying shared gpt.py code.
            self.temperature = None
            kwargs["temperature"] = None

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
            self.temperature = saved_temperature

    async def invoke(self, prompt: str, **kwargs) -> Any:
        """Lightweight stateless invocation — guarded for K-series models.

        ``OpenAIClient.invoke()`` always sends a fixed ``temperature``
        (default ``0.0``) with no ``None``-based omission path (unlike
        ``ask()``/``ask_stream()``), and never routes through the
        overridden ``_chat_completion()`` (see the module-level "KNOWN
        LIMITATIONS" note). K-series models reject that fixed
        ``temperature`` outright, so rather than silently forwarding a
        doomed request, this raises immediately for K-series models.

        Legacy (``moonshot-v1-*``) models are unaffected by the
        ``temperature`` restriction and delegate to
        ``OpenAIClient.invoke()`` unchanged (though, per the module-level
        note, ``max_completion_tokens`` translation and ``prompt_cache_key``
        still do not apply on this path).

        Args:
            prompt: User prompt.
            **kwargs: Forwarded to ``OpenAIClient.invoke()`` (e.g. ``model``,
                ``system_prompt``, ``max_tokens``, ``temperature``,
                ``use_tools``, ``tools``, ``output_type``,
                ``structured_output``).

        Returns:
            ``InvokeResult`` from ``OpenAIClient.invoke()``.

        Raises:
            ValueError: If the resolved model is a K-series model.
        """
        model_value = kwargs.get("model") or self.model or self._default_model
        if isinstance(model_value, Enum):
            model_value = model_value.value
        if model_value in K_SERIES_MODELS:
            raise ValueError(
                f"MoonshotClient.invoke() does not support K-series model "
                f"{model_value!r}: OpenAIClient.invoke() always sends a "
                "fixed `temperature`, which K-series models reject, and "
                "has no override point to omit it. Use `ask()` or "
                "`ask_stream()` for K-series models instead (see the "
                "module-level 'KNOWN LIMITATIONS' note in "
                "parrot.clients.moonshot)."
            )
        return await super().invoke(prompt, **kwargs)
