"""Meta Model API client for AI-Parrot.

``MetaClient`` subclasses :class:`~parrot.clients.openai_base.OpenAIBaseClient`
— the neutral OpenAI-wire layer (FEAT-438) that owns the wire protocol and
declares no OpenAI-provider model defaults — to speak to Meta's Muse Spark
model family (https://api.meta.ai/v1).

Almost everything is inherited: Chat Completions (``ask``/``ask_stream``/
``resume``/``invoke``) already funnels through
``OpenAIBaseClient._chat_completion()``, and live testing confirmed the
base's existing emissions are Meta-legal (``tool_choice="auto"`` and
``max_tokens``). This module adds only credential resolution, the Meta
base URL, a raised request timeout (Muse Spark is a reasoning model and
routinely slow), and ``list_models()``.

See ``sdd/specs/meta-llm-client.spec.md`` (FEAT-526).
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from logging import getLogger

import aiohttp
from navconfig import config

from ..openai_base import OpenAIBaseClient
from .models import MetaModel

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = getLogger(__name__)


class MetaClient(OpenAIBaseClient):
    """Client for Meta Model API (Muse Spark family).

    Args:
        api_key: Meta Model API key. Resolution order: ``api_key`` kwarg
            → ``META_API_KEY`` env var → ``MODEL_API_KEY`` env var. This
            chain MUST NOT fall through to ``OPENAI_API_KEY`` — the
            ``AsyncOpenAI`` SDK would otherwise silently pick that up and
            ship an OpenAI key to Meta.
        base_url: Override for Meta's API base URL. Defaults to
            ``https://api.meta.ai/v1``.
        use_responses: Whether to route ``ask()``/``ask_stream()`` through
            the Responses API instead of Chat Completions. Stored here;
            consumed by the Responses-API override added in a later task
            (TASK-2836) — otherwise inert.
        **kwargs: Additional arguments passed to
            :class:`~parrot.clients.openai_base.OpenAIBaseClient`.

    Example:
        >>> client = MetaClient()
        >>> response = await client.ask("Hello!")
    """

    client_type: str = "meta"
    client_name: str = "meta"
    _default_model: str = MetaModel.MUSE_SPARK_1_3.value
    # Muse Spark is a reasoning model: a live one-word answer ("pong") spent
    # 199 of 210 completion tokens on reasoning. A conventional 60s timeout
    # is measurably too tight for heavier prompts.
    _default_timeout: float = 120.0

    # FEAT-523 discovery contract: every factory key this class answers to
    # (primary first), and the model catalog enum it owns.
    provider_keys: tuple[str, ...] = ("meta", "muse", "meta-muse")
    models: type[MetaModel] = MetaModel

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        use_responses: bool = True,
        **kwargs: Any,
    ) -> None:
        self.use_responses = use_responses
        resolved_key = (
            api_key or config.get("META_API_KEY") or config.get("MODEL_API_KEY")
        )
        super().__init__(
            api_key=resolved_key,
            base_url=base_url or "https://api.meta.ai/v1",
            **kwargs,
        )
        # Re-set after super().__init__ — AbstractClient may overwrite it.
        self.api_key = resolved_key

    async def get_client(self) -> "AsyncOpenAI":
        """Initialize AsyncOpenAI configured for Meta Model API.

        Returns:
            An ``AsyncOpenAI`` instance pointed at Meta's base URL, with
            the resolved Meta API key passed explicitly (never relying on
            the SDK's ``OPENAI_API_KEY`` default).

        Raises:
            ImportError: If the ``openai`` package is not installed.
        """
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "MetaClient requires the 'openai' SDK. "
                "Install with: pip install ai-parrot[openai]"
            ) from exc
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self._timeout,
        )

    async def list_models(self) -> list[dict[str, Any]]:
        """List available models from Meta Model API.

        Fetches the model catalog from ``GET /v1/models``.

        Returns:
            List of model dicts as returned by the endpoint's ``data`` key.

        Raises:
            aiohttp.ClientError: If the HTTP request fails.
        """
        url = f"{self.base_url}/models"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                data = await response.json()

        return data.get("data", [])
