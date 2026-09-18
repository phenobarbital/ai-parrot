"""FEAT-099 (TASK-081): users_bots protected target and legacy envelope unwrapping."""
from __future__ import annotations

import uuid

import orjson
import pytest
from navigator_session.vault import KeyRing, VaultIntegrityError, open_sealed
from navigator_session.vault.registry import ProtectedTarget, VaultRow

from parrot.handlers.models import _encrypted_field as ef
from parrot.handlers.models.vault_target import UsersBotsTarget, factory

MASTER_KEYS = {1: b"\x55" * 32}
BOT_A = uuid.UUID(int=1)
BOT_B = uuid.UUID(int=2)


@pytest.fixture
def keyring():
    return KeyRing(MASTER_KEYS, 1)


@pytest.fixture
def target():
    return UsersBotsTarget(db_pool=object())


def row_for(user_id, chatbot_id, values=None):
    return VaultRow(
        ref="r", pk=chatbot_id,
        identity={"user_id": user_id, "chatbot_id": chatbot_id},
        values=values or {},
    )


def legacy_plaintext(user_id, chatbot_id, field, value):
    """Pre-FEAT-099 plaintext: the in-plaintext _ctx envelope."""
    return orjson.dumps({
        "_v": 1,
        "_ctx": {"u": int(user_id), "c": str(chatbot_id), "f": field},
        "v": value,
    })


class TestDeclaration:
    def test_protocol_and_shape(self, target):
        assert isinstance(target, ProtectedTarget)
        assert target.encrypted_fields == ("mcp_config", "tools_config")
        assert target.name.endswith(".users_bots") and target.pk_column == "chatbot_id"
        assert target.state_columns == ("enabled",)
        assert target.quarantine_assignments == "enabled = false"
        assert target.pk_from_json(str(BOT_A)) == BOT_A
        assert target.state_from_json("enabled", 0) is False

    def test_schema_override_and_factory(self):
        assert UsersBotsTarget(db_pool=object(), schema="tenant").name == "tenant.users_bots"
        assert factory({}) is None
        assert isinstance(factory({"db_pool": object()}), UsersBotsTarget)
        assert isinstance(factory({"parrot_db_pool": object()}), UsersBotsTarget)

    def test_entry_point_declared(self):
        tomllib = pytest.importorskip("tomllib")
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        data = tomllib.loads((root / "pyproject.toml").read_text())
        group = data["project"]["entry-points"]["navigator_session.vault_targets"]
        assert group["parrot_users_bots"] == "parrot.handlers.models.vault_target:factory"


class TestContexts:
    def test_target_context_matches_model_sealing(self, target, keyring, monkeypatch):
        monkeypatch.setattr(ef, "get_vault_keyring", lambda: keyring)
        blob = ef.seal([{"server": "a"}], user_id=7, chatbot_id=BOT_A, field="mcp_config")
        row = row_for(7, BOT_A)
        import base64

        plaintext = open_sealed(
            base64.b64decode(blob), target.context_for(row, "mcp_config"), keyring
        )
        assert orjson.loads(plaintext) == {"v": [{"server": "a"}]}

    def test_column_and_row_swaps_detected(self, target, keyring, monkeypatch):
        monkeypatch.setattr(ef, "get_vault_keyring", lambda: keyring)
        import base64

        blob = base64.b64decode(
            ef.seal([{"server": "a"}], user_id=7, chatbot_id=BOT_A, field="mcp_config")
        )
        for context in (
            target.context_for(row_for(7, BOT_A), "tools_config"),
            target.context_for(row_for(8, BOT_A), "mcp_config"),
            target.context_for(row_for(7, BOT_B), "mcp_config"),
        ):
            with pytest.raises(VaultIntegrityError):
                open_sealed(blob, context, keyring)


class TestLegacyUnwrap:
    def test_valid_envelope_is_unwrapped(self, target):
        row = row_for(7, BOT_A)
        plaintext = legacy_plaintext(7, BOT_A, "mcp_config", [{"server": "a"}])
        assert orjson.loads(target.legacy_unwrap("mcp_config", plaintext, row)) == {
            "v": [{"server": "a"}]
        }

    @pytest.mark.parametrize(
        "user_id,chatbot_id,field",
        [(8, BOT_A, "mcp_config"), (7, BOT_B, "mcp_config"), (7, BOT_A, "tools_config")],
        ids=["other-user", "other-bot", "other-column"],
    )
    def test_substituted_envelope_is_rejected(self, target, user_id, chatbot_id, field):
        """A v1 blob already copied between rows/columns must not be legitimised."""
        row = row_for(7, BOT_A)
        plaintext = legacy_plaintext(user_id, chatbot_id, field, [{"server": "stolen"}])
        with pytest.raises(ValueError, match="context mismatch"):
            target.legacy_unwrap("mcp_config", plaintext, row)

    @pytest.mark.parametrize(
        "payload", [b'[{"k": "v"}]', b'{"v": 1}', b'{"_v": 2, "_ctx": {}, "v": 1}']
    )
    def test_missing_or_unsupported_envelope(self, target, payload):
        with pytest.raises(ValueError, match="missing or unsupported"):
            target.legacy_unwrap("mcp_config", payload, row_for(7, BOT_A))
