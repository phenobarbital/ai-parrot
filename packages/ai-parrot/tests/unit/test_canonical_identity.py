"""Unit tests for TASK-1671: Canonical identity mapper.

Tests:
- A2A OID (from_id) and MSAgentSDK aad_object_id for the same human → same key
- email fallback when no OID present
- anonymous / neither → None (fail closed)
- OID takes precedence over email in same payload
- case normalisation (lower-case)
"""
from parrot.auth.identity import CanonicalIdentityMapper, identity_mapper


# ---------------------------------------------------------------------------
# OID-based mapping
# ---------------------------------------------------------------------------


def test_msagentsdk_aad_object_id_is_canonical():
    """aad_object_id UUID is returned as the canonical key (lower-cased)."""
    oid = "12345678-1234-5678-1234-567812345678"
    result = CanonicalIdentityMapper.to_canonical({"aad_object_id": oid})
    assert result == oid.lower()


def test_a2a_from_id_uuid_is_canonical():
    """A2A from_id UUID is returned as the canonical key."""
    oid = "ABCDEF01-2345-6789-ABCD-EF0123456789"
    result = CanonicalIdentityMapper.to_canonical({"from_id": oid})
    assert result == oid.lower()


def test_a2a_and_msagentsdk_same_oid_produce_same_canonical():
    """A2A (from_id) and MSAgentSDK (aad_object_id) for the same human map to one key.

    This is the core cross-surface reuse guarantee: a credential stored via
    one surface is found when the same user arrives via the other surface.
    """
    oid = "12345678-1234-5678-1234-567812345678"

    a2a_identity = {"from_id": oid, "from_email": "alice@corp.com"}
    ms_identity = {"aad_object_id": oid, "email": "alice@corp.com"}

    a2a_key = CanonicalIdentityMapper.to_canonical(a2a_identity)
    ms_key = CanonicalIdentityMapper.to_canonical(ms_identity)

    assert a2a_key == ms_key == oid.lower()


def test_oid_takes_precedence_over_email():
    """OID always wins over email when both are present."""
    oid = "12345678-1234-5678-1234-567812345678"
    result = CanonicalIdentityMapper.to_canonical(
        {"aad_object_id": oid, "email": "alice@corp.com"}
    )
    assert result == oid.lower()
    assert "@" not in result  # email not selected


def test_camel_case_aad_object_id_variant():
    """Raw-JSON camelCase aadObjectId is also accepted as OID source."""
    oid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    result = CanonicalIdentityMapper.to_canonical({"aadObjectId": oid})
    assert result == oid


# ---------------------------------------------------------------------------
# Email fallback
# ---------------------------------------------------------------------------


def test_a2a_from_email_is_canonical_when_no_oid():
    """A2A from_email used as canonical when no OID is present."""
    result = CanonicalIdentityMapper.to_canonical({"from_email": "alice@corp.com"})
    assert result == "alice@corp.com"


def test_a2a_nested_from_email_is_canonical():
    """Nested 'from.email' key (dotted notation) is supported."""
    result = CanonicalIdentityMapper.to_canonical({"from": {"email": "alice@corp.com"}})
    assert result == "alice@corp.com"


def test_email_key_direct():
    """Flat 'email' key works as email canonical."""
    result = CanonicalIdentityMapper.to_canonical({"email": "BOB@Corp.com"})
    assert result == "bob@corp.com"  # lower-cased


def test_x_ms_user_email_fallback():
    """x-ms-user-email header value used when no OID or primary email."""
    result = CanonicalIdentityMapper.to_canonical(
        {"x-ms-user-email": "Charlie@Corp.com"}
    )
    assert result == "charlie@corp.com"


def test_a2a_and_msagentsdk_same_email_produce_same_canonical():
    """When neither side has an OID, email-based canonical is cross-surface consistent."""
    a2a = {"from_email": "alice@corp.com"}
    ms = {"email": "alice@corp.com"}

    assert CanonicalIdentityMapper.to_canonical(a2a) == CanonicalIdentityMapper.to_canonical(ms)


# ---------------------------------------------------------------------------
# Fail-closed: anonymous / missing identity
# ---------------------------------------------------------------------------


def test_empty_dict_returns_none():
    """Empty identity dict → None (fail closed)."""
    assert CanonicalIdentityMapper.to_canonical({}) is None


def test_anonymous_string_id_returns_none():
    """Non-UUID, non-email from_id string → not treated as OID → None if no email."""
    result = CanonicalIdentityMapper.to_canonical({"from_id": "anonymous"})
    assert result is None


def test_sender_non_email_returns_none():
    """Non-email sender string → None (fail closed)."""
    result = CanonicalIdentityMapper.to_canonical({"sender": "bot-user-1234"})
    assert result is None


def test_none_values_in_dict_returns_none():
    """Explicit None values in known fields are ignored → None overall."""
    result = CanonicalIdentityMapper.to_canonical(
        {"aad_object_id": None, "email": None}
    )
    assert result is None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def test_module_level_singleton_works():
    """identity_mapper singleton delegates correctly."""
    oid = "12345678-1234-5678-1234-567812345678"
    result = identity_mapper.to_canonical({"aad_object_id": oid})
    assert result == oid.lower()
