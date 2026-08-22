"""The signed-webhook review source. No database, no network."""
from __future__ import annotations

import hashlib
import hmac

import pytest

from parrot_saas.reviews.port import ReviewEvent, ReviewSourceError
from parrot_saas.reviews.webhook import (
    SIGNATURE_HEADER,
    GenericWebhookReviewSource,
    secret_key_for,
)

SECRET = "whsec_bar_pepe_shared_secret"
BODY = b'{"external_id":"g-1","rating":1,"text":"Cold food"}'


def sign(body: bytes, secret: str = SECRET, *, prefix: bool = False) -> str:
    """Produce the signature a platform would send."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}" if prefix else digest


@pytest.fixture
def source() -> GenericWebhookReviewSource:
    """The generic webhook adapter."""
    return GenericWebhookReviewSource()


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_a_correct_signature_verifies(source) -> None:
    """The happy path: body signed with the tenant's secret."""
    headers = {SIGNATURE_HEADER: sign(BODY)}

    assert source.verify_webhook(headers, BODY, SECRET) is True


def test_the_sha256_prefix_is_accepted(source) -> None:
    """Several platforms prefix the digest; both forms must work."""
    headers = {SIGNATURE_HEADER: sign(BODY, prefix=True)}

    assert source.verify_webhook(headers, BODY, SECRET) is True


def test_a_single_changed_byte_fails(source) -> None:
    """The signature covers the body, so tampering has to show."""
    headers = {SIGNATURE_HEADER: sign(BODY)}
    tampered = BODY.replace(b'"rating":1', b'"rating":5')

    assert source.verify_webhook(headers, tampered, SECRET) is False


def test_another_tenants_secret_fails(source) -> None:
    """This is what stops one tenant posting reviews as another."""
    headers = {SIGNATURE_HEADER: sign(BODY, "someone-elses-secret")}

    assert source.verify_webhook(headers, BODY, SECRET) is False


@pytest.mark.parametrize(
    "headers", [{}, {SIGNATURE_HEADER: ""}, {SIGNATURE_HEADER: "   "}]
)
def test_a_missing_signature_fails(source, headers) -> None:
    """No signature is not a pass."""
    assert source.verify_webhook(headers, BODY, SECRET) is False


def test_an_unset_secret_fails(source) -> None:
    """A tenant with no secret configured has no webhook.

    Letting a body through because there is nothing to compare it with is how
    an ingest endpoint becomes open to anyone who learns the URL.
    """
    assert source.verify_webhook({SIGNATURE_HEADER: sign(BODY)}, BODY, "") is False


def test_an_empty_body_fails(source) -> None:
    """There is nothing to authenticate in an empty body."""
    assert source.verify_webhook({SIGNATURE_HEADER: sign(b"")}, b"", SECRET) is False


@pytest.mark.parametrize(
    "signature", ["not-hex", "sha256=", "z" * 64, "sha512=" + "a" * 64, "ñ" * 8]
)
def test_a_malformed_signature_is_refused_without_raising(
    source, signature
) -> None:
    """Malformed and merely wrong must be indistinguishable to the caller.

    Raising on one and returning False on the other tells an attacker when a
    guess is at least well-formed.
    """
    assert source.verify_webhook({SIGNATURE_HEADER: signature}, BODY, SECRET) is False


def test_the_secret_name_is_scoped_to_the_source() -> None:
    """Two sources on one tenant must not share a signing key."""
    assert secret_key_for("webhook") == "webhook:webhook:hmac"
    assert secret_key_for("acme") == "webhook:acme:hmac"


def test_the_secret_name_matches_what_the_secrets_api_accepts() -> None:
    """The name has to be storable, or it can never be configured."""
    from parrot_saas.handlers.secrets import KEY_PATTERN

    assert KEY_PATTERN.match(secret_key_for("webhook"))


# ---------------------------------------------------------------------------
# Normalising
# ---------------------------------------------------------------------------


def test_normalize_reads_the_common_field_names(source) -> None:
    """Platforms disagree on names; the adapter absorbs that."""
    event = source.normalize(
        {
            "id": "g-1",
            "comment": "Slow service",
            "rating": "4",
            "locale": "es",
            "author": "Marta",
            "email": "marta@example.com",
            "location": "venue-central",
        }
    )

    assert event.external_id == "g-1"
    assert event.text == "Slow service"
    assert event.rating == 4
    assert event.language == "es"
    assert event.author_name == "Marta"
    assert event.author_email == "marta@example.com"
    assert event.location_ref == "venue-central"


def test_normalize_never_assigns_the_tenant(source) -> None:
    """A payload must not be able to nominate whose review it is."""
    event = source.normalize({"id": "g-1", "tenant_id": "hotel-x"})

    assert event.tenant_id == ""


def test_normalize_keeps_the_raw_payload(source) -> None:
    """Kept for audit and replay."""
    event = source.normalize({"id": "g-1", "vendor_field": 7})

    assert event.raw["vendor_field"] == 7


def test_normalize_tolerates_a_zulu_timestamp(source) -> None:
    """``fromisoformat`` on 3.11 does not accept a trailing Z on its own."""
    event = source.normalize({"id": "g-1", "posted_at": "2026-05-04T10:00:00Z"})

    assert event.posted_at.year == 2026


def test_normalize_survives_an_unparseable_timestamp(source) -> None:
    """A bad date must not lose the review; it falls back to now."""
    event = source.normalize({"id": "g-1", "posted_at": "last tuesday"})

    assert event.posted_at is not None


def test_normalize_rejects_a_non_object(source) -> None:
    """A JSON array is not a review."""
    with pytest.raises(ValueError, match="JSON object"):
        source.normalize(["not", "an", "object"])


# ---------------------------------------------------------------------------
# De-duplication
# ---------------------------------------------------------------------------


def test_dedupe_prefers_the_platform_identifier(source) -> None:
    """When the platform gives a stable id, use it."""
    event = source.normalize({"id": "g-1", "text": "Cold food"})

    assert source.dedupe_key(event) == "g-1"


def test_dedupe_falls_back_to_a_content_hash(source) -> None:
    """Without an id, every retry would otherwise create a second review."""
    event = source.normalize({"text": "Cold food", "rating": 1})

    key = source.dedupe_key(event)
    assert key.startswith("sha256:")
    assert len(key) == len("sha256:") + 64


def test_the_content_hash_is_stable_across_deliveries(source) -> None:
    """Same review, same key — that is what collapses the replay."""
    payload = {"text": "Cold food", "rating": 1, "posted_at": "2026-05-04T10:00:00Z"}

    first = source.dedupe_key(source.normalize(dict(payload)))
    second = source.dedupe_key(source.normalize(dict(payload)))

    assert first == second


def test_the_content_hash_ignores_delivery_metadata(source) -> None:
    """A retry often carries a new attempt counter; that is the same review."""
    base = {"text": "Cold food", "rating": 1, "posted_at": "2026-05-04T10:00:00Z"}

    first = source.dedupe_key(source.normalize({**base, "delivery_attempt": 1}))
    second = source.dedupe_key(source.normalize({**base, "delivery_attempt": 2}))

    assert first == second


def test_a_different_review_hashes_differently(source) -> None:
    """The key has to discriminate, or distinct reviews would collapse."""
    posted = "2026-05-04T10:00:00Z"
    first = source.dedupe_key(
        source.normalize({"text": "Cold food", "rating": 1, "posted_at": posted})
    )
    second = source.dedupe_key(
        source.normalize({"text": "Lovely meal", "rating": 5, "posted_at": posted})
    )

    assert first != second


# ---------------------------------------------------------------------------
# Refused operations
# ---------------------------------------------------------------------------


async def test_fetch_is_refused(source) -> None:
    """A webhook is pushed to, never polled."""
    with pytest.raises(ReviewSourceError, match="cannot be polled"):
        await source.fetch("bar-pepe")


async def test_reply_is_refused(source) -> None:
    """A generic webhook has nowhere to publish a reply."""
    with pytest.raises(ReviewSourceError, match="cannot publish"):
        await source.reply("bar-pepe", "g-1", "Thanks")


def test_it_is_a_review_source(source) -> None:
    """The abstract contract is satisfied, refusals included."""
    from parrot_saas.reviews.port import ReviewSource

    assert isinstance(source, ReviewSource)
    assert isinstance(source.normalize({"id": "x"}), ReviewEvent)
