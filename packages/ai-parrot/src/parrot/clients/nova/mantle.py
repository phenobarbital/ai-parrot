"""Amazon Bedrock Mantle client for AI-Parrot (FEAT-407).

Extends ``OpenAIClient`` to route requests through Amazon Bedrock's
Project Mantle — a distributed inference engine that exposes an
OpenAI-compatible API for Bedrock-hosted models at
``https://bedrock-mantle.<region>.api.aws/v1``, authenticated with a
Bedrock API key (bearer token) rather than SigV4/boto credentials.

All completion, streaming, tool-calling, structured output, retry, and
fallback machinery is inherited from ``OpenAIClient`` unchanged — this
module only resolves the endpoint (region-aware) and the API key before
delegating to the parent's ``__init__``.

This client coexists with, and does not replace, the native
``BedrockConverseClient`` (FEAT-302) and ``NovaClient`` (FEAT-315),
which use the boto/Converse API code path instead of the OpenAI SDK.
"""

from ...conf import (
    AWS_NOVA_API_KEY,
    AWS_REGION_NAME,
    BEDROCK_AWS_REGION,
    BEDROCK_MANTLE_API_KEY,
    BEDROCK_MANTLE_BASE_URL,
)
from ..gpt import OpenAIClient


class BedrockMantleClient(OpenAIClient):
    """Client for Amazon Bedrock Mantle's OpenAI-compatible API.

    Resolves the Bedrock Mantle endpoint and API key, then delegates all
    completion/streaming/tool-calling behavior to the inherited
    ``OpenAIClient`` machinery — no OpenAI machinery is reimplemented or
    overridden here.

    Endpoint resolution (first match wins):
        1. explicit ``base_url`` kwarg;
        2. ``BEDROCK_MANTLE_BASE_URL`` conf var;
        3. constructed as ``https://bedrock-mantle.{region}.api.aws/v1``,
           where ``region`` resolves (first match wins) from the explicit
           ``region`` kwarg, ``BEDROCK_AWS_REGION``, ``AWS_REGION_NAME``,
           or ``"us-east-1"``.

    API-key resolution (first match wins):
        1. explicit ``api_key`` kwarg;
        2. ``BEDROCK_MANTLE_API_KEY`` conf var;
        3. ``AWS_NOVA_API_KEY`` conf var (existing Bedrock API key shared
           with ``NovaClient`` / ``BedrockConverseBase``).

    A misconfigured region yields a DNS/connection failure rather than an
    auth error — since Mantle is not available in every AWS region, check
    the resolved ``base_url`` first when debugging connectivity issues.

    Args:
        api_key: Bedrock API key (bearer token). Falls back to
            ``BEDROCK_MANTLE_API_KEY`` then ``AWS_NOVA_API_KEY``.
        base_url: Explicit Mantle endpoint override. Falls back to
            ``BEDROCK_MANTLE_BASE_URL`` then a region-constructed URL.
        region: AWS region used to construct the default base URL when
            neither ``base_url`` nor ``BEDROCK_MANTLE_BASE_URL`` is set.
            Falls back to ``BEDROCK_AWS_REGION`` then ``AWS_REGION_NAME``
            then ``"us-east-1"``.
        **kwargs: Additional arguments passed to ``OpenAIClient`` /
            ``AbstractClient``.

    Example::

        from parrot.clients.nova import BedrockMantleClient

        client = BedrockMantleClient(region="us-east-1")
        async with client:
            response = await client.ask(
                "Explain quantum entanglement simply.",
                model="anthropic.claude-mythos-preview",
            )
    """

    client_type: str = "bedrock-mantle"
    client_name: str = "bedrock-mantle"
    _default_model: str = "openai.gpt-oss-120b"
    _fallback_model: str = "google.gemma-4-26b-a4b"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        region: str | None = None,
        **kwargs,
    ):
        resolved_key = api_key or BEDROCK_MANTLE_API_KEY or AWS_NOVA_API_KEY
        resolved_region = region or BEDROCK_AWS_REGION or AWS_REGION_NAME or "us-east-1"
        resolved_base_url = (
            base_url
            or BEDROCK_MANTLE_BASE_URL
            or f"https://bedrock-mantle.{resolved_region}.api.aws/v1"
        )
        # AbstractClient.__init__ unconditionally does
        # ``self._fallback_model = kwargs.get('fallback_model', None)``,
        # which shadows this class's ``_fallback_model`` class attribute
        # with an instance attribute of ``None`` unless a caller
        # explicitly passes ``fallback_model=`` (see bedrock.py:199-209 /
        # spec §7). ``setdefault`` preserves an explicit caller value.
        kwargs.setdefault("fallback_model", self._fallback_model)
        super().__init__(
            api_key=resolved_key,
            base_url=resolved_base_url,
            **kwargs,
        )
        # Re-set after super().__init__ because AbstractClient may
        # overwrite self.api_key during its own initialisation. This
        # mirrors the guard used by NvidiaClient (nvidia.py:84) and
        # OpenRouterClient (openrouter.py:75).
        self.api_key = resolved_key
