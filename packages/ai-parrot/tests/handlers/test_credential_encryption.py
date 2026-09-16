"""Unit tests for credential encryption helpers (TASK-438; envelope v2 in FEAT-099)."""
import base64
import os

import pytest
from navigator_session.vault import (
    KeyRing,
    UnknownKeyVersionError,
    UnsupportedFormatError,
    VaultIntegrityError,
    read_header,
)
from parrot.handlers.credentials_utils import (
    credential_context,
    decrypt_credential,
    encrypt_credential,
    llm_key_context,
    normalize_user_id,
    reseal_credential,
)

USER = 7
NAME = "prod_pg"


@pytest.fixture
def master_keys():
    return {1: os.urandom(32), 2: os.urandom(32)}


@pytest.fixture
def keyring(master_keys):
    return KeyRing(master_keys, 1)


@pytest.fixture
def ctx():
    return credential_context(USER, NAME)


class TestCredentialEncryption:
    """Round-trips through encrypt_credential / decrypt_credential."""

    @pytest.mark.parametrize(
        "cred",
        [
            {"driver": "pg", "params": {"host": "db", "password": "p@ss"}},
            {"driver": "pg", "password": "very$ecure!Pass#123 \n\t"},
            {"driver": "pg", "password": "contraseña_日本語_пароль"},
            {"driver": "pg"},
            {},
            {"api_key": "sk-test", "nested": {"list": [1, 2, {"a": None}]}},
        ],
        ids=["basic", "special-chars", "unicode", "driver-only", "empty", "nested"],
    )
    def test_roundtrip(self, keyring, ctx, cred):
        assert decrypt_credential(encrypt_credential(cred, ctx, keyring), ctx, keyring) == cred

    def test_encrypted_is_base64_v2_envelope(self, keyring, ctx):
        encrypted = encrypt_credential({"password": "super-secret"}, ctx, keyring)
        blob = base64.b64decode(encrypted)  # valid base64
        assert blob[0] == 0xA2 and read_header(blob).key_id == 1
        assert "super-secret" not in encrypted and b"super-secret" not in blob

    def test_nonce_is_random(self, keyring, ctx):
        cred = {"driver": "pg"}
        assert encrypt_credential(cred, ctx, keyring) != encrypt_credential(cred, ctx, keyring)

    def test_explicit_key_id(self, keyring, ctx):
        encrypted = encrypt_credential({"a": 1}, ctx, keyring, key_id=2)
        assert read_header(base64.b64decode(encrypted)).key_id == 2
        assert decrypt_credential(encrypted, ctx, keyring) == {"a": 1}


class TestContextBinding:
    @pytest.mark.parametrize(
        "other",
        [
            credential_context(8, NAME),
            credential_context(USER, "staging_pg"),
            llm_key_context(USER, NAME),
        ],
        ids=["other-user", "other-name", "other-purpose"],
    )
    def test_wrong_context_rejected(self, keyring, ctx, other):
        encrypted = encrypt_credential({"password": "p"}, ctx, keyring)
        with pytest.raises(VaultIntegrityError):
            decrypt_credential(encrypted, other, keyring)

    def test_llm_key_bound_to_provider(self, keyring):
        encrypted = encrypt_credential({"api_key": "sk"}, llm_key_context(USER, "openai"), keyring)
        with pytest.raises(VaultIntegrityError):
            decrypt_credential(encrypted, llm_key_context(USER, "anthropic"), keyring)

    def test_wrong_master_key(self, keyring, ctx, master_keys):
        encrypted = encrypt_credential({"a": 1}, ctx, keyring)
        other = KeyRing({1: os.urandom(32)}, 1)
        with pytest.raises(VaultIntegrityError):
            decrypt_credential(encrypted, ctx, other)

    def test_unknown_key_version(self, keyring, ctx, master_keys):
        encrypted = encrypt_credential({"a": 1}, ctx, keyring, key_id=2)
        with pytest.raises(UnknownKeyVersionError):
            decrypt_credential(encrypted, ctx, KeyRing({1: master_keys[1]}, 1))

    def test_legacy_v1_blob_rejected(self, keyring, ctx):
        v1 = base64.b64encode(b"\x00\x01" + os.urandom(40)).decode()
        with pytest.raises(UnsupportedFormatError):
            decrypt_credential(v1, ctx, keyring)

    def test_reseal_for_new_name(self, keyring, ctx):
        encrypted = encrypt_credential({"password": "p"}, ctx, keyring)
        new_ctx = credential_context(USER, "renamed")
        resealed = reseal_credential(encrypted, ctx, new_ctx, keyring)
        assert decrypt_credential(resealed, new_ctx, keyring) == {"password": "p"}
        with pytest.raises(VaultIntegrityError):
            decrypt_credential(resealed, ctx, keyring)


class TestContexts:
    @pytest.mark.parametrize("value,expected", [(7, 7), ("7", 7), ("alice", "alice")])
    def test_normalize_user_id(self, value, expected):
        assert normalize_user_id(value) == expected

    @pytest.mark.parametrize("value", [None, "", True, 1.5])
    def test_normalize_user_id_rejects(self, value):
        with pytest.raises(ValueError):
            normalize_user_id(value)

    def test_numeric_string_user_matches_int(self, keyring):
        encrypted = encrypt_credential({"a": 1}, credential_context("7", NAME), keyring)
        assert decrypt_credential(encrypted, credential_context(7, NAME), keyring) == {"a": 1}

    def test_context_shapes(self):
        cred = credential_context(7, NAME)
        assert cred.purpose == "parrot-credential" and cred.layer == "db"
        assert cred.fields == (("user_id", 7), ("name", NAME), ("field", "credential"))
        key = llm_key_context("7", "openai")
        assert key.purpose == "parrot-llm-key"
        assert key.fields == (("user_id", 7), ("provider", "openai"), ("field", "api_key"))

    @pytest.mark.parametrize("factory,args", [(credential_context, (7, "")), (llm_key_context, (7, ""))])
    def test_missing_identity_rejected(self, factory, args):
        with pytest.raises(ValueError):
            factory(*args)
