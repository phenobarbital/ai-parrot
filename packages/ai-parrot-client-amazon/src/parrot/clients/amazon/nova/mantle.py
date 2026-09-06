"""Amazon Bedrock Mantle client for AI-Parrot (FEAT-407; rebased FEAT-438).

Extends ``OpenAIBaseClient`` to route requests through Amazon Bedrock's
Project Mantle — a distributed inference engine that exposes an
OpenAI-compatible API for Bedrock-hosted models at
``https://bedrock-mantle.<region>.api.aws/v1``, authenticated with a
Bedrock API key (bearer token) rather than SigV4/boto credentials.

All completion, streaming, tool-calling, structured output, retry, and
fallback machinery is inherited from ``OpenAIBaseClient`` unchanged — this
module only resolves the endpoint (region-aware) and the API key before
delegating to the parent's ``__init__``. FEAT-438 rebases this client onto
``OpenAIBaseClient`` (not ``OpenAIClient``) so it never inherits
OpenAI-the-provider defaults (``gpt-*`` model ids) — the root cause of the
production DeepSeek V3.2 404 that motivated FEAT-438.

This client coexists with, and does not replace, the native
``BedrockConverseClient`` (FEAT-302) and ``NovaClient`` (FEAT-315),
which use the boto/Converse API code path instead of the OpenAI SDK.
"""

from enum import Enum

from ....conf import (
    AWS_NOVA_API_KEY,
    AWS_REGION_NAME,
    BEDROCK_AWS_REGION,
    BEDROCK_MANTLE_API_KEY,
    BEDROCK_MANTLE_BASE_URL,
)
from ...openai_base import OpenAIBaseClient
from ..models import AmazonModel


class BedrockMantleClient(OpenAIBaseClient):
    """Client for Amazon Bedrock Mantle's OpenAI-compatible API.

    Resolves the Bedrock Mantle endpoint and API key, then delegates all
    completion/streaming/tool-calling behavior to the inherited
    ``OpenAIBaseClient`` machinery — no OpenAI machinery is reimplemented or
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

        from parrot.clients.amazon.nova import BedrockMantleClient

        client = BedrockMantleClient(region="us-east-1")
        async with client:
            response = await client.ask(
                "Explain quantum entanglement simply.",
                model="anthropic.claude-mythos-preview",
            )
    """

    client_type: str = "bedrock-mantle"
    client_name: str = "bedrock-mantle"

    # FEAT-523 folder-convention attributes (read by LLMFactory).
    provider_keys: tuple[str, ...] = ("bedrock-mantle", "mantle")
    models: type[Enum] = AmazonModel
    _default_model: str = "openai.gpt-oss-120b"
    # No verified Mantle-servable fallback model exists yet. This used to be
    # "google.gemma-4-26b-a4b", but a live probe (2026-09-05) got back
    # ``400 validation_error: model 'google.gemma-4-26b-a4b' isn't supported
    # on this route`` — the id is not valid on Mantle's chat-completions
    # route at all (possibly Converse-only, like Llama4 Maverick). Left
    # ``None`` (disables the capacity-error fallback path in
    # AbstractClient._should_use_fallback()) rather than shipping a fallback
    # that would 400 on every retry; set this once a working Mantle-native
    # fallback id is confirmed live.
    _fallback_model: str | None = None

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
            base_url or BEDROCK_MANTLE_BASE_URL or f"https://bedrock-mantle.{resolved_region}.api.aws/v1"
        )
        # FEAT-438 G5: AbstractClient.__init__ now only creates an instance
        # attribute when the caller explicitly passes fallback_model=, so
        # this class's _fallback_model class attribute survives unshadowed
        # without needing a workaround here anymore.
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
        # Code-review fix (FEAT-407, still applicable post-FEAT-438
        # rebase onto OpenAIBaseClient): __init__ builds self.base_headers
        # from the api_key it received *before* the re-set above runs.
        # When no Mantle/Nova/explicit key resolves, the base falls back
        # to None for both self.api_key and self.base_headers — the re-set above
        # corrects self.api_key (used by get_client()/AsyncOpenAI), but
        # left base_headers stale with a real OPENAI_API_KEY bearer
        # token, which AbstractClient.__aenter__ sends verbatim to the
        # Bedrock Mantle host when use_session=True. Rebuild it here so
        # both attributes stay in sync with the resolved Mantle key.
        self.base_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
