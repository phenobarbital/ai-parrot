"""Composable backend strategy objects for AnthropicClient (FEAT-232).

Each backend encapsulates the SDK-client construction and model-ID
translation for one Anthropic transport:

- ``DirectBackend``       — direct Anthropic API (``AsyncAnthropic``).
- ``BedrockBackend``      — AWS Bedrock (``AsyncAnthropicBedrock``).
- ``AWSWorkspaceBackend`` — Claude-on-AWS workspace (``AsyncAnthropicAWS``).

``AnthropicClient.__init__`` resolves credentials from parrot.conf → env →
``None`` (SDK chain) and passes the resolved values to the chosen backend
via ``__init__``.  ``AnthropicClient.get_client()`` delegates to
``backend.build_client()``.

Usage::

    backend = BedrockBackend(
        aws_region="us-east-1",
        aws_access_key="AKIA...",
        aws_secret_key="...",
        aws_session_token=None,
        region_prefix="us",
    )
    sdk_client = await backend.build_client()
    translated = backend.translate_model("claude-sonnet-4-6")
"""
from __future__ import annotations

import logging
from typing import Optional


class DirectBackend:
    """Backend strategy for the direct Anthropic API (``AsyncAnthropic``).

    This reproduces the current ``get_client()`` behaviour so that adding
    ``backend`` to ``AnthropicClient`` is a no-op when ``backend="direct"``.

    Args:
        api_key: Anthropic API key.  Pass ``None`` to let the SDK read the
            ``ANTHROPIC_API_KEY`` environment variable.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key
        self.logger = logging.getLogger(__name__)

    async def build_client(self):
        """Build and return an ``AsyncAnthropic`` SDK client.

        Returns:
            An ``AsyncAnthropic`` instance configured with ``max_retries=2``.

        Raises:
            ImportError: When the ``anthropic`` SDK is not installed, with a
                hint to install ``ai-parrot[anthropic]``.
        """
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise ImportError(
                "DirectBackend requires the 'anthropic' SDK. "
                "Install with: pip install ai-parrot[anthropic]"
            ) from exc
        return AsyncAnthropic(api_key=self.api_key, max_retries=2)

    def translate_model(self, model: str) -> str:
        """Identity — direct API uses public model IDs unchanged.

        Args:
            model: Public model ID string.

        Returns:
            The same *model* string unchanged.
        """
        return model


class BedrockBackend:
    """Backend strategy for AWS Bedrock (``AsyncAnthropicBedrock``).

    Translates public model IDs to Bedrock IDs via
    :func:`parrot.models.bedrock_models.translate` before every SDK call.
    AWS credentials are optional — pass ``None`` to fall through to the
    standard AWS credential chain (``~/.aws/credentials`` / IAM role / IMDS).

    Args:
        aws_region: AWS region (e.g. ``"us-east-1"``).
        aws_access_key: AWS access key ID.  ``None`` → SDK chain.
        aws_secret_key: AWS secret access key.  ``None`` → SDK chain.
        aws_session_token: Optional STS session token.  ``None`` → omitted.
        region_prefix: Cross-region inference-profile prefix (``"us"``,
            ``"eu"``, ``"apac"``).  ``None`` → no prefix.
    """

    def __init__(
        self,
        aws_region: Optional[str] = None,
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        region_prefix: Optional[str] = None,
    ) -> None:
        self.aws_region = aws_region
        self.aws_access_key = aws_access_key
        self.aws_secret_key = aws_secret_key
        self.aws_session_token = aws_session_token
        self.region_prefix = region_prefix
        self.logger = logging.getLogger(__name__)

    async def build_client(self):
        """Build and return an ``AsyncAnthropicBedrock`` SDK client.

        Passes ``None`` credentials through so the SDK falls back to the
        standard AWS credential chain when they are absent.

        Returns:
            An ``AsyncAnthropicBedrock`` instance.

        Raises:
            ImportError: When ``anthropic[aws]`` is not installed, with a
                hint to install ``ai-parrot[anthropic]``.
        """
        try:
            from anthropic import AsyncAnthropicBedrock
        except ImportError as exc:
            raise ImportError(
                "Bedrock backend requires the AWS extra of the anthropic SDK. "
                "Install with: pip install ai-parrot[anthropic]"
            ) from exc

        kwargs: dict = {}
        if self.aws_region is not None:
            kwargs["aws_region"] = self.aws_region
        if self.aws_access_key is not None:
            kwargs["aws_access_key"] = self.aws_access_key
        if self.aws_secret_key is not None:
            kwargs["aws_secret_key"] = self.aws_secret_key
        if self.aws_session_token is not None:
            kwargs["aws_session_token"] = self.aws_session_token

        return AsyncAnthropicBedrock(**kwargs)

    def translate_model(self, model: str) -> str:
        """Translate *model* to its AWS Bedrock ID.

        Delegates to :func:`parrot.models.bedrock_models.translate` with the
        configured ``region_prefix``.

        Args:
            model: Public or Bedrock model ID string.

        Returns:
            Translated Bedrock model ID string.
        """
        from parrot.models.bedrock_models import translate
        return translate(model, region_prefix=self.region_prefix)


class AWSWorkspaceBackend:
    """Backend strategy for Claude-on-AWS (``AsyncAnthropicAWS``).

    Both ``aws_region`` **and** ``workspace_id`` are mandatory — the SDK
    raises at construction time if either is missing with no fallback.
    This backend validates them eagerly in ``build_client()`` and raises a
    clear ``ValueError`` naming the env var to set.

    The SDK parameter is ``workspace_id`` (NOT ``aws_workspace_id``); the
    conf/env constant is ``ANTHROPIC_AWS_WORKSPACE_ID``, which is mapped
    to ``workspace_id`` at the call site.

    AWS credentials are optional (``aws_access_key`` / ``aws_secret_key``
    / ``aws_session_token`` / ``aws_profile``); pass ``None`` to let the
    SDK use the standard AWS chain.

    Args:
        aws_region: AWS region — **mandatory**.
        workspace_id: Claude-on-AWS workspace ID — **mandatory**.
        aws_access_key: AWS access key ID.  ``None`` → SDK chain.
        aws_secret_key: AWS secret access key.  ``None`` → SDK chain.
        aws_session_token: Optional STS session token.  ``None`` → omitted.
        aws_profile: Optional AWS profile name.  ``None`` → omitted.
    """

    def __init__(
        self,
        aws_region: Optional[str] = None,
        workspace_id: Optional[str] = None,
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        aws_profile: Optional[str] = None,
    ) -> None:
        self.aws_region = aws_region
        self.workspace_id = workspace_id
        self.aws_access_key = aws_access_key
        self.aws_secret_key = aws_secret_key
        self.aws_session_token = aws_session_token
        self.aws_profile = aws_profile
        self.logger = logging.getLogger(__name__)

    async def build_client(self):
        """Build and return an ``AsyncAnthropicAWS`` SDK client.

        Validates that ``aws_region`` and ``workspace_id`` are non-empty
        before constructing the SDK client (the SDK raises otherwise with an
        unhelpful message).

        Returns:
            An ``AsyncAnthropicAWS`` instance.

        Raises:
            ValueError: When ``aws_region`` or ``workspace_id`` is missing,
                with a message naming the corresponding env var to set.
            ImportError: When ``anthropic[aws]`` is not installed, with a
                hint to install ``ai-parrot[anthropic]``.
        """
        if not self.aws_region:
            raise ValueError(
                "AWSWorkspaceBackend requires aws_region. "
                "Set the AWS_REGION_NAME environment variable (or conf key) "
                "to the AWS region where your workspace is located."
            )
        if not self.workspace_id:
            raise ValueError(
                "AWSWorkspaceBackend requires workspace_id. "
                "Set the ANTHROPIC_AWS_WORKSPACE_ID environment variable "
                "(or conf key) to your Claude-on-AWS workspace ID."
            )

        try:
            from anthropic import AsyncAnthropicAWS
        except ImportError as exc:
            raise ImportError(
                "AWS-workspace backend requires the AWS extra of the anthropic SDK. "
                "Install with: pip install ai-parrot[anthropic]"
            ) from exc

        kwargs: dict = {
            "aws_region": self.aws_region,
            "workspace_id": self.workspace_id,
        }
        if self.aws_access_key is not None:
            kwargs["aws_access_key"] = self.aws_access_key
        if self.aws_secret_key is not None:
            kwargs["aws_secret_key"] = self.aws_secret_key
        if self.aws_session_token is not None:
            kwargs["aws_session_token"] = self.aws_session_token
        if self.aws_profile is not None:
            kwargs["aws_profile"] = self.aws_profile

        return AsyncAnthropicAWS(**kwargs)

    def translate_model(self, model: str) -> str:
        """Identity — AWS-workspace uses public model IDs unchanged.

        Args:
            model: Public model ID string.

        Returns:
            The same *model* string unchanged.
        """
        return model
