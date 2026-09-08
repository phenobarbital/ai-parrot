"""Compatibility for Bedrock gateway errors in the optional voice SDK.

Import only on the voice path: the Smithy SDK requires Python 3.12+.
SDK 0.7.0 ignores the capitalized ``Message`` sent by the Bedrock gateway,
losing the IAM denial reason. Normalize just this error field before using
the SDK's usual modeled-error deserializer.
"""

import json
from typing import Any

from aws_sdk_bedrock_runtime.config import _SCHEMA_AMAZON_BEDROCK_FRONTEND_SERVICE
from smithy_aws_core.aio.protocols import RestJsonClientProtocol
from smithy_core.exceptions import CallError


class NovaVoiceProtocol(RestJsonClientProtocol):
    """Preserve gateway error messages without changing successful streams."""

    def __init__(self) -> None:
        super().__init__(_SCHEMA_AMAZON_BEDROCK_FRONTEND_SERVICE)

    async def _create_error(self, **kwargs: Any) -> CallError:
        """Accept both modeled ``message`` and gateway ``Message`` keys."""
        body = kwargs.get("response_body")
        if isinstance(body, (bytes, bytearray)):
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                pass
            else:
                if isinstance(payload, dict) and "message" not in payload and isinstance(payload.get("Message"), str):
                    payload["message"] = payload["Message"]
                    kwargs["response_body"] = json.dumps(payload).encode("utf-8")
        return await super()._create_error(**kwargs)
