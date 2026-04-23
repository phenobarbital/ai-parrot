"""Nvidia NIM client for AI-Parrot.

Extends OpenAIClient to route requests through Nvidia's OpenAI-compatible
NIM gateway at https://integrate.api.nvidia.com/v1.

All completion, streaming, tool-calling, retry, and invoke logic is inherited
from OpenAIClient unchanged. The only Nvidia-specific affordance is the
``enable_thinking`` keyword on ``ask`` / ``ask_stream`` that injects
``chat_template_kwargs`` into ``extra_body`` for reasoning-capable models
such as ``z-ai/glm-5.1``.
"""
from typing import Any, Dict, Optional
from logging import getLogger

from navconfig import config

from .gpt import OpenAIClient
from ..models.nvidia import NvidiaModel

logger = getLogger(__name__)


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

    async def ask(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        clear_thinking: bool = False,
        **kwargs,
    ):
        """Submit a prompt and return the full response.

        Identical to ``OpenAIClient.ask`` with an additional ``enable_thinking``
        shortcut that injects ``chat_template_kwargs`` into ``extra_body`` for
        reasoning-capable models (e.g. ``z-ai/glm-5.1``).

        Args:
            prompt: User message text.
            enable_thinking: When ``True``, add
                ``extra_body["chat_template_kwargs"]["enable_thinking"] = True``.
            clear_thinking: Forwarded to ``clear_thinking`` in the payload
                when ``enable_thinking`` is ``True``.
            **kwargs: All other keyword arguments delegated to
                ``OpenAIClient.ask``.

        Returns:
            AI response (same shape as ``OpenAIClient.ask``).
        """
        kwargs["extra_body"] = self._merge_thinking_extra_body(
            kwargs.get("extra_body"), enable_thinking, clear_thinking
        )
        return await super().ask(prompt, **kwargs)

    async def ask_stream(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        clear_thinking: bool = False,
        **kwargs,
    ):
        """Submit a prompt and stream response chunks.

        Identical to ``OpenAIClient.ask_stream`` with the same
        ``enable_thinking`` shortcut as ``ask``.  For reasoning-capable models
        (e.g. ``z-ai/glm-5.1``) each chunk may carry a
        ``delta.reasoning_content`` field in addition to ``delta.content``.

        Args:
            prompt: User message text.
            enable_thinking: When ``True``, inject reasoning flags into
                ``extra_body``.
            clear_thinking: Forwarded to ``clear_thinking`` in the payload
                when ``enable_thinking`` is ``True``.
            **kwargs: All other keyword arguments delegated to
                ``OpenAIClient.ask_stream``.

        Yields:
            Response chunks (same shape as ``OpenAIClient.ask_stream``).
        """
        kwargs["extra_body"] = self._merge_thinking_extra_body(
            kwargs.get("extra_body"), enable_thinking, clear_thinking
        )
        async for chunk in super().ask_stream(prompt, **kwargs):
            yield chunk
