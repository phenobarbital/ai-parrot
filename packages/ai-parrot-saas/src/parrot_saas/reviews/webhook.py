"""A signed-webhook :class:`ReviewSource` — the inbound half of real ingest.

Platforms that push reviews register a URL and POST to it. There is no session
and no tenant header, so the signature over the request body is the whole of
the authentication: this adapter says whether a body was produced by someone
holding the tenant's shared secret, and nothing else in the ingest path decides
that question.

**On replay.** The signature carries no timestamp, so a captured body can be
sent again. The defence is not cryptographic — it is the
``UNIQUE (tenant_id, source, external_id)`` constraint behind
``ReviewRepository.ingest``, which turns a replay into a ``duplicate`` response
rather than a second run, a second public reply and a second coupon. Adding a
timestamp window here would break the legitimate retries every webhook platform
performs, so it is deliberately absent.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from navconfig.logging import logging

from .port import ReviewEvent, ReviewReply, ReviewSource, ReviewSourceError

logger = logging.getLogger("parrot_saas.reviews.webhook")

#: Header carrying the HMAC-SHA256 signature of the raw request body.
SIGNATURE_HEADER = "X-Parrot-Signature"

#: Prefix some platforms put in front of the digest. Accepted, not required.
SIGNATURE_PREFIX = "sha256="

#: Template for the per-tenant shared secret in the ``SecretStore``.
WEBHOOK_SECRET_KEY = "webhook:{source}:hmac"


def secret_key_for(source: str) -> str:
    """Return the secret name holding one source's webhook signing key.

    Args:
        source: Adapter name.

    Returns:
        The key to read from the tenant's secret store.
    """
    return WEBHOOK_SECRET_KEY.format(source=source)


class GenericWebhookReviewSource(ReviewSource):
    """Accepts reviews pushed over a signed webhook.

    Inbound only. A generic webhook has no API to poll and no endpoint to
    publish a reply through, so :meth:`fetch` and :meth:`reply` refuse rather
    than pretend — that is a fact about this adapter, not a gap in it. A
    tenant whose platform can also receive replies uses that platform's own
    adapter.

    Args:
        name: Adapter name. Stored on every review row and part of the
            de-duplication key, so changing it orphans existing rows.
    """

    def __init__(self, *, name: str = "webhook") -> None:
        self.name = name

    # -- authentication ----------------------------------------------------

    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, secret: str
    ) -> bool:
        """Whether ``body`` was signed with ``secret``.

        Never raises. A malformed signature and an incorrect one must be
        indistinguishable to the caller: an exception on one and a ``False`` on
        the other is a side channel that tells an attacker when their guess is
        at least well-formed.

        Args:
            headers: Request headers.
            body: The **raw** request body. A body that has been parsed and
                re-serialised will not verify — key order and whitespace are
                part of what was signed.
            secret: The tenant's shared secret for this source.

        Returns:
            ``True`` only when a signature is present, the secret is set, and
            the digests match.
        """
        if not secret or not body:
            return False
        provided = self._signature(headers)
        if not provided:
            return False
        expected = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        try:
            return hmac.compare_digest(expected, provided)
        except (TypeError, ValueError):  # pragma: no cover - non-ascii header
            return False

    @staticmethod
    def _signature(headers: Mapping[str, str]) -> str:
        """Extract the digest from the signature header.

        Args:
            headers: Request headers.

        Returns:
            The lowercase hex digest, or an empty string.
        """
        raw = (headers.get(SIGNATURE_HEADER) or "").strip()
        if raw.lower().startswith(SIGNATURE_PREFIX):
            raw = raw[len(SIGNATURE_PREFIX):]
        return raw.strip().lower()

    # -- normalisation -----------------------------------------------------

    def normalize(self, payload: Mapping[str, Any]) -> ReviewEvent:
        """Convert a pushed payload into an event.

        Args:
            payload: The platform's own representation.

        Returns:
            The normalised event, with ``tenant_id`` unset — the ingest path
            assigns it from the verified route, never from the payload.

        Raises:
            ValueError: If the payload is not a JSON object.
        """
        if not isinstance(payload, Mapping):
            raise ValueError("a review webhook payload must be a JSON object")
        data = dict(payload)
        posted_at = data.get("posted_at") or data.get("created_at")
        if isinstance(posted_at, str):
            try:
                posted_at = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None
        elif not isinstance(posted_at, datetime):
            posted_at = None

        event = ReviewEvent(
            source=self.name,
            external_id=str(
                data.get("external_id") or data.get("id") or ""
            ).strip(),
            location_ref=str(data.get("location_ref") or data.get("location") or ""),
            rating=self._as_int(data.get("rating")),
            text=str(data.get("text") or data.get("comment") or data.get("body") or ""),
            language=str(data.get("language") or data.get("locale") or "en"),
            author_name=str(data.get("author_name") or data.get("author") or ""),
            author_email=str(data.get("author_email") or data.get("email") or ""),
            author_phone=str(data.get("author_phone") or data.get("phone") or ""),
            raw=data,
            **({"posted_at": posted_at} if posted_at else {}),
        )
        return event

    @staticmethod
    def _as_int(value: Any) -> int:
        """Coerce a rating to an int, tolerating ``"4"`` and ``4.0``."""
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    def dedupe_key(self, event: ReviewEvent) -> str:
        """Return a stable de-duplication value, hashing content if need be.

        A generic webhook cannot promise its senders supply an identifier, and
        without one every retry would create a second review, a second reply
        and a second coupon. When the platform gives nothing to key on, the
        review's own content becomes the key: same review, same digest, and
        ``ingest`` collapses the replay.

        The digest covers the fields a person would use to say "that is the
        same review" — not the whole payload, which can carry delivery
        metadata that differs between retries.

        Args:
            event: The normalised event.

        Returns:
            The event's own identifier, or ``"sha256:<digest>"``.
        """
        if event.external_id:
            return event.external_id
        material = json.dumps(
            {
                "author": event.author_name,
                "language": event.language,
                "location": event.location_ref,
                "posted_at": event.posted_at.isoformat(),
                "rating": event.rating,
                "text": event.text,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        logger.debug(
            "webhook payload carried no external id; keyed on content hash %s",
            digest[:12],
        )
        return f"sha256:{digest}"

    # -- refused operations ------------------------------------------------

    async def fetch(
        self,
        tenant_id: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> Sequence[ReviewEvent]:
        """Always refuses: a webhook is pushed to, never polled.

        Raises:
            ReviewSourceError: Always.
        """
        raise ReviewSourceError(
            f"{self.name!r} is an inbound webhook source; it cannot be polled"
        )

    async def reply(
        self, tenant_id: str, external_id: str, text: str
    ) -> ReviewReply:
        """Always refuses: a generic webhook has nowhere to publish a reply.

        Raises:
            ReviewSourceError: Always.
        """
        raise ReviewSourceError(
            f"{self.name!r} is an inbound webhook source; it cannot publish "
            "replies. Configure the platform's own adapter to reply."
        )


__all__ = (
    "SIGNATURE_HEADER",
    "SIGNATURE_PREFIX",
    "WEBHOOK_SECRET_KEY",
    "GenericWebhookReviewSource",
    "secret_key_for",
)
