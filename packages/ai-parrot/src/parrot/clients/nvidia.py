"""Nvidia NIM client for AI-Parrot.

Extends OpenAIClient to route requests through Nvidia's OpenAI-compatible
NIM gateway at https://integrate.api.nvidia.com/v1.

All completion, streaming, tool-calling, retry, and invoke logic is inherited
from OpenAIClient unchanged. The only Nvidia-specific affordance is the
``enable_thinking`` keyword on ``ask`` / ``ask_stream`` that injects
``chat_template_kwargs`` into ``extra_body`` for reasoning-capable models
such as ``z-ai/glm-5.1``.
"""
import contextvars
from typing import Any, AsyncIterator, Dict, Optional

from navconfig import config
from openai import APIConnectionError, APIError, RateLimitError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..models import AIMessage
from .gpt import OpenAIClient
from ..models.nvidia import NvidiaModel

# Context variable that carries enable_thinking / clear_thinking flags from
# ask / ask_stream down to _chat_completion without altering the parent's
# call signatures.  Using a ContextVar is safe for concurrent async calls
# because each asyncio Task inherits an isolated copy of the context.
_thinking_ctx: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "_nvidia_thinking_ctx", default={}
)


class NvidiaClient(OpenAIClient):
    """Client for Nvidia NIM's OpenAI-compatible API gateway.

    Routes all requests through ``https://integrate.api.nvidia.com/v1`` and
    resolves the API key from the constructor argument or the ``NVIDIA_API_KEY``
    environment variable (via ``navconfig.config``).

    All inherited OpenAI machinery — ``ask``, ``ask_stream``, ``invoke``,
    ``_chat_completion``, tool calling, structured output, and retry — works
    without modification.

    The only Nvidia-specific affordance is the ``enable_thinking`` shortcut on
    ``ask`` / ``ask_stream`` that injects ``chat_template_kwargs`` into
    ``extra_body`` for reasoning-capable models (e.g. ``z-ai/glm-5.1``).

    ``enable_thinking`` is propagated to ``_chat_completion`` via an async
    context variable so that no changes to the parent's call signatures are
    required.

    Args:
        api_key: Nvidia NIM API key. Falls back to ``NVIDIA_API_KEY`` env var
            (resolved via ``navconfig.config``).
        **kwargs: Additional arguments passed to ``OpenAIClient`` /
            ``AbstractClient``.

    Example::

        client = NvidiaClient(model=NvidiaModel.GLM_5_1)
        response = await client.ask(
            "Explain gradient descent.",
            enable_thinking=True,
        )
    """

    client_type: str = "nvidia"
    client_name: str = "nvidia"
    _default_model: str = NvidiaModel.KIMI_K2_INSTRUCT_0905.value

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        resolved_key = api_key or config.get("NVIDIA_API_KEY")
        super().__init__(
            api_key=resolved_key,
            base_url="https://integrate.api.nvidia.com/v1",
            **kwargs,
        )
        # Re-set after super().__init__ because AbstractClient may overwrite
        # self.api_key during its own initialisation.  This mirrors the guard
        # used by OpenRouterClient (openrouter.py:75).
        self.api_key = resolved_key

    @staticmethod
    def _merge_thinking_extra_body(
        extra_body: Optional[Dict[str, Any]],
        enable_thinking: bool,
        clear_thinking: bool,
    ) -> Optional[Dict[str, Any]]:
        """Merge ``chat_template_kwargs`` reasoning flags into ``extra_body``.

        When ``enable_thinking`` is ``False`` the function returns
        ``extra_body`` completely unchanged (including returning ``None`` when
        ``extra_body`` was ``None``).

        When ``enable_thinking`` is ``True`` the function returns a new dict
        that preserves every existing key in ``extra_body`` and every existing
        key inside ``extra_body["chat_template_kwargs"]``, then adds
        ``enable_thinking`` and ``clear_thinking`` flags.

        This is an internal helper; callers should use the ``enable_thinking``
        keyword on ``ask`` / ``ask_stream`` rather than calling this directly.

        Args:
            extra_body: Existing ``extra_body`` dict (may be ``None``).
            enable_thinking: When ``True``, inject the reasoning flags.
            clear_thinking: Value forwarded to ``clear_thinking`` in the
                injected payload.

        Returns:
            Updated ``extra_body`` dict, or ``None`` when nothing was injected.
        """
        if not enable_thinking:
            return extra_body
        merged: Dict[str, Any] = dict(extra_body or {})
        kwargs_block: Dict[str, Any] = dict(merged.get("chat_template_kwargs") or {})
        kwargs_block["enable_thinking"] = True
        kwargs_block["clear_thinking"] = clear_thinking
        merged["chat_template_kwargs"] = kwargs_block
        return merged

    async def _chat_completion(
        self,
        model: str,
        messages: Any,
        use_tools: bool = False,
        **kwargs,
    ) -> Any:
        """Run a chat completion against NVIDIA NIM via ``create()``.

        Two NVIDIA-specific differences from ``OpenAIClient._chat_completion``:

        1. Always uses ``client.chat.completions.create``. NIM rejects the
           OpenAI SDK's ``parse()`` shortcut (returns 5xx / "page not found"),
           so we never route through it — even when ``use_tools`` is ``False``.
        2. Reads the thinking flags from the async context variable set by
           ``ask`` / ``ask_stream`` and merges them into ``extra_body`` for
           reasoning-capable models (e.g. ``z-ai/glm-5.1``).

        Args:
            model: Model identifier string.
            messages: Chat messages list.
            use_tools: Whether tools are enabled (kept for parity with parent).
            **kwargs: Additional completion arguments forwarded to the OpenAI SDK.

        Returns:
            Raw OpenAI ``ChatCompletion`` response.
        """
        thinking = _thinking_ctx.get()
        if thinking.get("enable_thinking"):
            kwargs["extra_body"] = self._merge_thinking_extra_body(
                kwargs.get("extra_body"),
                True,
                thinking.get("clear_thinking", False),
            )
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
        enable_thinking: bool = False,
        clear_thinking: bool = False,
        **kwargs,
    ) -> AIMessage:
        """Submit a prompt and return the full response.

        Identical to ``OpenAIClient.ask`` with an additional ``enable_thinking``
        shortcut that injects ``chat_template_kwargs`` into ``extra_body`` for
        reasoning-capable models (e.g. ``z-ai/glm-5.1``).

        The flags are forwarded to ``_chat_completion`` via an async context
        variable, so the parent's call signature is preserved.

        Args:
            prompt: User message text.
            enable_thinking: When ``True``, add
                ``extra_body["chat_template_kwargs"]["enable_thinking"] = True``.
            clear_thinking: Forwarded to ``clear_thinking`` in the payload
                when ``enable_thinking`` is ``True``.
            **kwargs: All other keyword arguments delegated to
                ``OpenAIClient.ask`` (e.g. ``model``, ``temperature``,
                ``system_prompt``, ``session_id``).

        Returns:
            AIMessage with the model response.
        """
        kwargs.setdefault("model", self.model or self._default_model)
        token = _thinking_ctx.set(
            {"enable_thinking": enable_thinking, "clear_thinking": clear_thinking}
        )
        try:
            return await super().ask(prompt, **kwargs)
        finally:
            _thinking_ctx.reset(token)

    async def ask_stream(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        clear_thinking: bool = False,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Submit a prompt and stream response chunks.

        Identical to ``OpenAIClient.ask_stream`` with the same
        ``enable_thinking`` shortcut as ``ask``.  For reasoning-capable models
        (e.g. ``z-ai/glm-5.1``) each chunk may carry a
        ``delta.reasoning_content`` field in addition to ``delta.content``.

        The flags are forwarded to ``_chat_completion`` via an async context
        variable, so the parent's call signature is preserved.

        Args:
            prompt: User message text.
            enable_thinking: When ``True``, inject reasoning flags into
                ``extra_body``.
            clear_thinking: Forwarded to ``clear_thinking`` in the payload
                when ``enable_thinking`` is ``True``.
            **kwargs: All other keyword arguments delegated to
                ``OpenAIClient.ask_stream`` (e.g. ``model``, ``temperature``,
                ``system_prompt``, ``session_id``).

        Yields:
            Response text chunks (same shape as ``OpenAIClient.ask_stream``).
        """
        kwargs.setdefault("model", self.model or self._default_model)
        token = _thinking_ctx.set(
            {"enable_thinking": enable_thinking, "clear_thinking": clear_thinking}
        )
        try:
            async for chunk in super().ask_stream(prompt, **kwargs):
                yield chunk
        finally:
            _thinking_ctx.reset(token)
