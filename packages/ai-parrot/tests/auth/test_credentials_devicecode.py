"""Unit tests for the `device_code` AuthKind + signal-model extensions (FEAT-266)."""
import pytest

from parrot.auth.credentials import (
    ProviderCredentialConfig,
    NeedsAuth,
    CredentialRequired,
)


def test_authkind_includes_device_code():
    cfg = ProviderCredentialConfig(provider="o365", auth="device_code")
    assert cfg.auth == "device_code"


def test_needsauth_optional_devicecode_fields_default_none():
    n = NeedsAuth(provider="o365", auth_url="https://x", auth_kind="device_code")
    assert n.user_code is None
    assert n.verification_uri is None
    assert n.expires_in is None


def test_needsauth_carries_devicecode_fields():
    n = NeedsAuth(
        provider="o365",
        auth_url="https://microsoft.com/devicelogin",
        auth_kind="device_code",
        user_code="A1B2-C3D4",
        verification_uri="https://microsoft.com/devicelogin",
        expires_in=900,
    )
    assert n.user_code == "A1B2-C3D4"
    assert n.verification_uri == "https://microsoft.com/devicelogin"
    assert n.expires_in == 900


def test_needsauth_existing_auth_kinds_unaffected():
    n = NeedsAuth(provider="workiq", auth_url="https://x", auth_kind="obo")
    assert n.auth_kind == "obo"
    assert n.user_code is None
    assert n.verification_uri is None
    assert n.expires_in is None


def test_credentialrequired_backward_compatible():
    e = CredentialRequired("o365", "https://x", "device_code")
    assert e.provider == "o365"
    assert e.auth_url == "https://x"
    assert e.auth_kind == "device_code"
    assert e.user_code is None
    assert e.verification_uri is None
    assert e.expires_in is None


def test_credentialrequired_accepts_devicecode_kwargs():
    e = CredentialRequired(
        "o365",
        "https://microsoft.com/devicelogin",
        "device_code",
        user_code="A1B2-C3D4",
        verification_uri="https://microsoft.com/devicelogin",
        expires_in=900,
    )
    assert e.user_code == "A1B2-C3D4"
    assert e.verification_uri == "https://microsoft.com/devicelogin"
    assert e.expires_in == 900


def test_credentialrequired_existing_call_sites_unaffected():
    e = CredentialRequired("workiq", "https://auth.example.com", "obo")
    assert e.provider == "workiq"
    assert e.auth_kind == "obo"
    assert e.user_code is None
