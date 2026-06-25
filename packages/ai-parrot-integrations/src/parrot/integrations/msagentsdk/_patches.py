"""
Runtime patches for the Microsoft 365 Agents SDK.

The SDK is vendored as an installed dependency, so these patches monkeypatch
specific methods at runtime rather than editing the package on disk (which a
reinstall would clobber). Every patch here is idempotent and guarded so a
missing SDK symbol degrades to a no-op instead of raising at import time.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_MCS_JSON_PATCH_APPLIED = False


def patch_mcs_connector_empty_response() -> None:
    """Make the MCS connector tolerate an empty / non-JSON 200 response.

    When an agent reply is sent through Microsoft Copilot Studio's
    ``pva-studio`` channel, the SDK's ``MCSConversations.send_to_conversation``
    POSTs the activity to the Power Apps runtime and then calls
    ``response.json()`` unconditionally. The runtime acknowledges a successful
    delivery with **HTTP 200 but an empty body and no ``Content-Type``**, so
    aiohttp raises ``ContentTypeError`` ("Attempt to decode JSON with
    unexpected mimetype") — even though the message was delivered fine. The
    error then bubbles up, the turn fails, and the SDK retries (sending the
    reply several times).

    This patch replaces ``send_to_conversation`` with a version that reads the
    body defensively: it still raises on real HTTP errors (status >= 300), but
    treats an empty or non-JSON success body as an empty ``ResourceResponse``
    instead of crashing.

    Idempotent: safe to call multiple times. A no-op if the SDK is not
    installed or its internals have changed shape.
    """
    global _MCS_JSON_PATCH_APPLIED
    if _MCS_JSON_PATCH_APPLIED:
        return

    try:
        from microsoft_agents.activity import ResourceResponse
        from microsoft_agents.hosting.core.connector.mcs.mcs_connector_client import (
            MCSConversations,
        )
    except Exception as exc:  # noqa: BLE001 — optional dep / moved symbol
        logger.debug("MCS connector patch skipped (import failed): %s", exc)
        return

    async def send_to_conversation(self, conversation_id, activity, **kwargs):
        """Patched: tolerate an empty / non-JSON 200 acknowledgement."""
        if activity is None:
            raise ValueError("activity is required")

        logger.debug(
            "MCS Connector (patched): sending %s activity to conversation %s",
            activity.type,
            conversation_id,
        )

        async with self._client.post(
            self._endpoint,
            json=activity.model_dump(
                by_alias=True, exclude_unset=True, mode="json"
            ),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        ) as response:
            if response.status >= 300:
                logger.error(
                    "MCS Connector: error sending activity: %s", response.status
                )
                response.raise_for_status()

            # The runtime often acknowledges with 200 + empty body / no
            # content-type. Read raw bytes and parse only when there is JSON.
            body = await response.read()
            if not body or not body.strip():
                return ResourceResponse()
            try:
                data = json.loads(body)
            except (ValueError, TypeError):
                logger.debug(
                    "MCS Connector: 200 with non-JSON body (%d bytes) — "
                    "treating as successful delivery",
                    len(body),
                )
                return ResourceResponse()
            return ResourceResponse.model_validate(data)

    MCSConversations.send_to_conversation = send_to_conversation
    _MCS_JSON_PATCH_APPLIED = True
    logger.info(
        "Applied MCS connector patch (tolerate empty/non-JSON 200 responses)."
    )
