"""Security-focused tests for the per-user-bots feature.

Covers the hardening applied after the post-merge code review:
    * Sealed-blob context binding (seal/unseal)
    * Credential redaction in API responses
    * _deep_merge delete sentinel
    * UUID coercion of path parameters
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from parrot.handlers.agents.users import (
    _coerce_chatbot_id,
    _deep_merge,
    _is_credential_key,
    _redact,
    _REDACT_PLACEHOLDER,
)
from parrot.handlers.models._encrypted_field import seal, unseal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault_keys():
    """Patch ``load_vault_keys`` to return a deterministic master key."""
    master_key = os.urandom(32)
    with patch(
        "parrot.handlers.models._encrypted_field.load_vault_keys",
        return_value=(1, master_key, {1: master_key}),
    ):
        yield


# ---------------------------------------------------------------------------
# seal / unseal — context binding
# ---------------------------------------------------------------------------

class TestSealUnsealContext:
    """Verify the in-plaintext context envelope defends against substitution."""

    def test_roundtrip_returns_original_value(self, vault_keys):
        payload = [{"name": "weather", "api_key": "secret"}]
        blob = seal(payload, user_id=42, chatbot_id="b1", field="mcp_config")
        out = unseal(blob, user_id=42, chatbot_id="b1", field="mcp_config")
        assert out == payload

    def test_empty_value_returns_none(self, vault_keys):
        for empty in (None, [], {}, ""):
            assert seal(empty, user_id=1, chatbot_id="x", field="f") is None

    def test_unseal_none_returns_none(self):
        assert unseal(None, user_id=1, chatbot_id="x", field="f") is None
        assert unseal("", user_id=1, chatbot_id="x", field="f") is None

    def test_cross_user_substitution_rejected(self, vault_keys):
        """Copying user_A's blob into user_B's row must fail to decrypt."""
        blob = seal([{"k": "v"}], user_id=1, chatbot_id="b1", field="mcp_config")
        with pytest.raises(ValueError, match="context mismatch"):
            unseal(blob, user_id=2, chatbot_id="b1", field="mcp_config")

    def test_cross_bot_substitution_rejected(self, vault_keys):
        """Copying a user's blob between two of their own bots must fail."""
        blob = seal([{"k": "v"}], user_id=1, chatbot_id="b1", field="mcp_config")
        with pytest.raises(ValueError, match="context mismatch"):
            unseal(blob, user_id=1, chatbot_id="b2", field="mcp_config")

    def test_column_swap_rejected(self, vault_keys):
        """A blob sealed for mcp_config must not decrypt as tools_config."""
        blob = seal([{"k": "v"}], user_id=1, chatbot_id="b1", field="mcp_config")
        with pytest.raises(ValueError, match="context mismatch"):
            unseal(blob, user_id=1, chatbot_id="b1", field="tools_config")

    def test_legacy_envelope_rejected(self, vault_keys):
        """Ciphertext lacking the _ctx envelope must be rejected.

        Simulates a row encrypted under the pre-hardening scheme by
        directly encrypting a raw list.
        """
        from parrot.handlers.credentials_utils import encrypt_credential
        master_key = os.urandom(32)
        with patch(
            "parrot.handlers.models._encrypted_field.load_vault_keys",
            return_value=(1, master_key, {1: master_key}),
        ):
            legacy = encrypt_credential({"__list__": [{"k": "v"}]}, 1, master_key)
            with pytest.raises(ValueError, match="missing or unsupported"):
                unseal(legacy, user_id=1, chatbot_id="b1", field="mcp_config")


# ---------------------------------------------------------------------------
# _redact
# ---------------------------------------------------------------------------

class TestRedaction:
    """Credential-shaped keys must never be echoed back on responses."""

    @pytest.mark.parametrize(
        "key",
        [
            "api_key", "apikey", "API_KEY", "Api-Key", "X-Api-Key",
            "client_secret", "password", "passwd",
            "token", "auth_token", "access_token", "refresh_token",
            "id_token", "secret", "webhook_secret", "signing_secret",
            "private_key", "private_key_id",
            "bearer", "Authorization",
            "credentials", "session_token",
        ],
    )
    def test_known_credential_keys_are_redacted(self, key):
        out = _redact({key: "leaky-value", "name": "weather"})
        assert out[key] == _REDACT_PLACEHOLDER
        assert out["name"] == "weather"

    def test_redaction_recurses_into_nested_dicts_and_lists(self):
        payload = {
            "servers": [
                {"name": "weather", "config": {"api_key": "leak"}},
                {"name": "news", "token": "leak"},
            ],
        }
        out = _redact(payload)
        assert out["servers"][0]["config"]["api_key"] == _REDACT_PLACEHOLDER
        assert out["servers"][1]["token"] == _REDACT_PLACEHOLDER
        assert out["servers"][0]["name"] == "weather"

    def test_env_dict_redacts_all_values(self):
        """MCP-style env dicts redact every value (uppercase env-var keys)."""
        payload = {
            "name": "anthropic",
            "env": {
                "ANTHROPIC_API_KEY": "sk-...",
                "MY_CUSTOM_TOKEN": "t-...",
                "LOG_LEVEL": "INFO",  # not a credential, but env block redacts everything
            },
        }
        out = _redact(payload)
        assert out["env"]["ANTHROPIC_API_KEY"] == _REDACT_PLACEHOLDER
        assert out["env"]["MY_CUSTOM_TOKEN"] == _REDACT_PLACEHOLDER
        assert out["env"]["LOG_LEVEL"] == _REDACT_PLACEHOLDER
        assert out["name"] == "anthropic"

    def test_env_with_non_dict_value_falls_through(self):
        """`env: "string"` is not a credential bag; leave the value alone."""
        payload = {"env": "production"}
        out = _redact(payload)
        assert out["env"] == "production"

    def test_dash_and_underscore_normalisation(self):
        """`Api-Key` and `api_key` both match."""
        assert _is_credential_key("Api-Key") is True
        assert _is_credential_key("api_key") is True
        assert _is_credential_key("X-API-KEY") is True
        assert _is_credential_key("name") is False
        assert _is_credential_key(123) is False  # non-string

    def test_non_dict_non_list_passthrough(self):
        assert _redact("plain") == "plain"
        assert _redact(42) == 42
        assert _redact(None) is None


# ---------------------------------------------------------------------------
# _deep_merge — delete sentinel
# ---------------------------------------------------------------------------

class TestDeepMergeDeleteSentinel:
    """Named-list items can be deleted via {"name": "...", "_delete": True}."""

    def test_delete_sentinel_removes_named_entry(self):
        base = [
            {"name": "weather", "api_key": "k1"},
            {"name": "news", "api_key": "k2"},
        ]
        patch_payload = [{"name": "weather", "_delete": True}]
        result = _deep_merge(base, patch_payload)
        assert {it["name"] for it in result} == {"news"}

    def test_delete_sentinel_does_not_affect_other_entries(self):
        base = [
            {"name": "a", "v": 1},
            {"name": "b", "v": 2},
            {"name": "c", "v": 3},
        ]
        result = _deep_merge(base, [{"name": "b", "_delete": True}])
        names = {it["name"]: it for it in result}
        assert "b" not in names
        assert names["a"]["v"] == 1
        assert names["c"]["v"] == 3

    def test_delete_unknown_name_is_noop(self):
        base = [{"name": "a", "v": 1}]
        result = _deep_merge(base, [{"name": "z", "_delete": True}])
        assert result == base

    def test_partial_update_preserves_unmentioned_keys(self):
        """Patch without _delete merges into the named entry."""
        base = [{"name": "weather", "api_key": "k1", "url": "http://w"}]
        result = _deep_merge(base, [{"name": "weather", "url": "https://w"}])
        assert result[0]["api_key"] == "k1"
        assert result[0]["url"] == "https://w"

    def test_dict_explicit_none_deletes_key(self):
        """Dict-merge: None value deletes the key (regression guard)."""
        base = {"a": 1, "b": 2}
        result = _deep_merge(base, {"b": None})
        assert result == {"a": 1}


# ---------------------------------------------------------------------------
# _coerce_chatbot_id
# ---------------------------------------------------------------------------

class TestCoerceChatbotId:
    """Path-segment chatbot_id must be UUID-validated before reaching the ORM."""

    def test_valid_uuid_returns_canonical_string(self):
        raw = "5b2c7af0-2c9c-4f0b-9ab1-58e88a82d6cf"
        assert _coerce_chatbot_id(raw) == raw

    def test_uppercase_uuid_normalised(self):
        raw = "5B2C7AF0-2C9C-4F0B-9AB1-58E88A82D6CF"
        assert _coerce_chatbot_id(raw) == raw.lower()

    def test_invalid_uuid_returns_none(self):
        assert _coerce_chatbot_id("not-a-uuid") is None
        assert _coerce_chatbot_id("'; DROP TABLE --") is None

    def test_missing_returns_none(self):
        assert _coerce_chatbot_id(None) is None
        assert _coerce_chatbot_id("") is None
