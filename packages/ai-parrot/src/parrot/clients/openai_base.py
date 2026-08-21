"""OpenAI-compatible wire protocol base client.

``OpenAIBaseClient`` carries the OpenAI chat-completions wire protocol
(request/response shaping, tool-calling loop, streaming, structured output)
with **no** OpenAI-the-provider defaults. It declares no model attribute
values — ``_default_model``/``_fallback_model``/``_lightweight_model`` stay
``None`` (inherited from :class:`~parrot.clients.base.AbstractClient`) so the
invoke chain falls back to ``self.model`` instead of silently sending an
OpenAI-only model id to a non-OpenAI endpoint.

This module MUST NOT contain any OpenAI-specific model-id literal — that is
OpenAI-the-provider knowledge and belongs exclusively in
:mod:`parrot.clients.gpt`.

See ``sdd/specs/openai-compatible-clients.spec.md`` (FEAT-438) §3 Module 1.
"""
from __future__ import annotations

from typing import Any

from ..tools.manager import ToolFormat
from .base import AbstractClient


class OpenAIBaseClient(AbstractClient):
    """OpenAI-compatible wire protocol; carries NO OpenAI-provider defaults.

    Subclasses that speak the OpenAI chat-completions wire protocol under a
    provider-specific label (Bedrock Mantle, OpenRouter, Moonshot, Nvidia,
    LocalLLM/vLLM, and — in Phase 2 — Groq/Zai via their native SDKs) should
    inherit from this class instead of :class:`~parrot.clients.gpt.OpenAIClient`
    directly, so they never inherit OpenAI-the-provider defaults (OpenAI-only
    model ids, Responses-API routing, Sora, etc.).
    """

    tool_format: ToolFormat = ToolFormat.OPENAI
    # Intentionally NO _default_model / _fallback_model / _lightweight_model
    # values here — they stay None (AbstractClient defaults) so the invoke
    # chain (base.py:_resolve_invoke_model) falls through to self.model.

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs,
    ):
        """Initialize the OpenAI-compatible wire client.

        Args:
            api_key: Bearer token for the target endpoint. Providers supply
                their own environment-variable default in their own
                ``__init__`` — this base does not read any env var.
            base_url: Base URL of the OpenAI-compatible endpoint. Providers
                supply their own default in their own ``__init__``.
            **kwargs: Forwarded to :class:`~parrot.clients.base.AbstractClient`.
                May include ``model`` (normalized via :meth:`_normalize_model`
                before being forwarded) and ``timeout`` (SDK request timeout,
                defaults to 60 seconds).
        """
        self.api_key = api_key
        self.base_url = base_url
        self.base_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        self._timeout = kwargs.pop("timeout", 60)
        if "model" in kwargs:
            kwargs["model"] = self._normalize_model(kwargs["model"])
        super().__init__(**kwargs)

    async def get_client(self) -> Any:
        """Build the default OpenAI-SDK-shaped async client.

        Lazily imports ``openai.AsyncOpenAI`` so the SDK is only required
        when an OpenAI-compatible client is actually instantiated. Subclasses
        that wrap a native SDK (Groq, Zai) override this hook.

        Returns:
            An ``AsyncOpenAI`` instance configured with this client's
            ``api_key``/``base_url``/timeout.

        Raises:
            ImportError: If the ``openai`` package is not installed.
        """
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAIBaseClient requires the 'openai' SDK. "
                "Install with: pip install ai-parrot[openai]"
            ) from exc
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self._timeout,
        )

    def _normalize_model(self, model: Any) -> str:
        """Coerce *model* to ``str``. Identity — no deprecation logic.

        The base carries no knowledge of any provider's model catalog or
        deprecation schedule; :class:`~parrot.clients.gpt.OpenAIClient`
        overrides this with OpenAI-specific alias/deprecation handling.

        Args:
            model: A model id string, or an ``Enum`` whose ``.value`` is the
                model id.

        Returns:
            The model id as a plain string.
        """
        return model.value if hasattr(model, "value") else model

    def _resolve_model(self, model: Any | None) -> str:
        """Resolve the model for a call: explicit > configured > class default.

        Args:
            model: Explicit per-call model, or ``None`` to use the configured
                one.

        Returns:
            The resolved model id.

        Raises:
            ValueError: If the resolution chain yields no model at all — the
                base never sends ``model=None`` on the wire.
        """
        resolved = model or self.model or self.default_model
        if not resolved:
            raise ValueError(
                f"no model configured for {self.__class__.__name__}"
            )
        return self._normalize_model(resolved)

    def _is_responses_model(self, model_str: str) -> bool:
        """Return whether *model_str* must be routed via the Responses API.

        Always ``False`` in the base — Responses-API routing is
        OpenAI-the-provider behavior owned by
        :class:`~parrot.clients.gpt.OpenAIClient`.

        Args:
            model_str: The resolved model id.

        Returns:
            ``False``.
        """
        return False

    @staticmethod
    def _with_extra_body(payload: dict[str, Any], extra_body: dict[str, Any]) -> dict[str, Any]:
        """Merge *extra_body* into *payload*'s ``extra_body`` key.

        Args:
            payload: The request payload dict.
            extra_body: Additional provider-specific keys to merge into the
                payload's ``extra_body``.

        Returns:
            A new dict with ``extra_body`` merged in (existing values win
            over *extra_body* on key collision).
        """
        merged = dict(payload)
        existing_raw = merged.pop("extra_body", None)
        existing = (dict(existing_raw) if isinstance(existing_raw, dict) else {}) | extra_body
        if existing:
            merged["extra_body"] = existing
        return merged
