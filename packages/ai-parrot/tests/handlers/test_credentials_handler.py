"""Unit tests for CredentialsHandler (TASK-439).

Tests are structured as pure-Python unit tests that mock DocumentDb,
the session vault, and vault crypto — no live services required.
"""
from __future__ import annotations

import os
import base64
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

from parrot.handlers.credentials import CredentialsHandler, setup_credentials_routes
from parrot.handlers.models.credentials import CredentialPayload, CredentialResponse


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_encrypted(cred_dict: dict) -> str:
    """Create a minimal fake encrypted string for test fixtures."""
    import orjson, base64 as b64
    # Use a fake static ciphertext (2B key_id + 12B nonce + payload)
    raw = b"\x00\x01" + b"\x00" * 12 + orjson.dumps(cred_dict)
    return b64.b64encode(raw).decode("ascii")


@pytest.fixture
def sample_credential():
    """Return a sample valid credential payload dict."""
    return {
        "name": "my-postgres",
        "driver": "pg",
        "params": {"host": "localhost", "port": 5432, "user": "admin", "password": "secret"},
    }


@pytest.fixture
def user_id():
    return "user-test-123"


@pytest.fixture
def master_key():
    return os.urandom(32)


@pytest.fixture
def master_keys(master_key):
    return {1: master_key}


_MISSING = object()  # sentinel for "use default session"


def _make_handler(user_id: str, session=_MISSING):
    """Create a CredentialsHandler with mocked request/session state."""
    handler = CredentialsHandler.__new__(CredentialsHandler)
    handler.logger = MagicMock()
    handler.request = MagicMock()
    handler.request.match_info = MagicMock()
    handler.request.match_info.get = MagicMock(return_value=None)
    handler._session = {"user_id": user_id} if session is _MISSING else session
    # Mock response helpers
    handler.json_response = MagicMock(
        side_effect=lambda data, status=200: MagicMock(status=status, data=data)
    )
    handler.error = MagicMock(
        side_effect=lambda msg, status=400: MagicMock(status=status, msg=msg)
    )
    return handler


# ---------------------------------------------------------------------------
# _get_user_id
# ---------------------------------------------------------------------------

class TestGetUserId:
    def test_returns_user_id_from_session(self, user_id):
        handler = _make_handler(user_id)
        assert handler._get_user_id() == user_id

    def test_returns_user_id_from_nested_session(self, user_id):
        handler = _make_handler(user_id, session={"session": {"user_id": user_id}})
        assert handler._get_user_id() == user_id

    def test_raises_when_session_missing(self, user_id):
        from aiohttp import web
        handler = _make_handler(user_id, session=None)
        with pytest.raises(web.HTTPUnauthorized):
            handler._get_user_id()

    def test_raises_when_user_id_missing(self, user_id):
        from aiohttp import web
        handler = _make_handler(user_id, session={})
        with pytest.raises(web.HTTPUnauthorized):
            handler._get_user_id()


# ---------------------------------------------------------------------------
# Session vault helpers
# ---------------------------------------------------------------------------

class TestSessionVaultHelpers:
    def test_session_key_format(self, user_id):
        handler = _make_handler(user_id)
        assert handler._session_key("my-pg") == "_credentials:my-pg"

    def test_set_session_credential(self, user_id):
        session: dict = {"user_id": user_id}
        handler = _make_handler(user_id, session=session)
        handler._set_session_credential("my-pg", {"driver": "pg", "params": {}})
        assert session["_credentials:my-pg"] == {"driver": "pg", "params": {}}

    def test_remove_session_credential(self, user_id):
        session: dict = {"user_id": user_id, "_credentials:my-pg": {"driver": "pg"}}
        handler = _make_handler(user_id, session=session)
        handler._remove_session_credential("my-pg")
        assert "_credentials:my-pg" not in session

    def test_remove_nonexistent_is_safe(self, user_id):
        handler = _make_handler(user_id)
        # Should not raise
        handler._remove_session_credential("does-not-exist")

    def test_get_all_session_credentials(self, user_id):
        session: dict = {
            "user_id": user_id,
            "_credentials:pg-one": {"driver": "pg", "params": {}},
            "_credentials:mysql-two": {"driver": "mysql", "params": {}},
            "other_key": "ignored",
        }
        handler = _make_handler(user_id, session=session)
        creds = handler._get_all_session_credentials()
        assert "pg-one" in creds
        assert "mysql-two" in creds
        assert "other_key" not in creds


# ---------------------------------------------------------------------------
# POST
# ---------------------------------------------------------------------------

class TestPost:
    @pytest.mark.asyncio
    async def test_post_creates_credential(self, sample_credential, user_id, master_key, master_keys):
        session: dict = {"user_id": user_id}
        handler = _make_handler(user_id, session=session)
        handler.request.json = AsyncMock(return_value=sample_credential)

        mock_db = AsyncMock()
        mock_db.documentdb_connect = AsyncMock()
        mock_db.read_one = AsyncMock(return_value=None)  # no duplicate
        mock_db.save_background = MagicMock()

        with patch("parrot.handlers.credentials.DocumentDb", return_value=mock_db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, master_key, master_keys)):
            response = await handler.post()

        assert response.status == 201
        # Credential saved to session
        assert f"_credentials:{sample_credential['name']}" in session

    @pytest.mark.asyncio
    async def test_post_duplicate_returns_409(self, sample_credential, user_id, master_key, master_keys):
        handler = _make_handler(user_id)
        handler.request.json = AsyncMock(return_value=sample_credential)

        mock_db = AsyncMock()
        mock_db.documentdb_connect = AsyncMock()
        mock_db.read_one = AsyncMock(return_value={"name": "my-postgres"})  # duplicate
        mock_db.close = AsyncMock()

        with patch("parrot.handlers.credentials.DocumentDb", return_value=mock_db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, master_key, master_keys)):
            response = await handler.post()

        assert response.status == 409

    @pytest.mark.asyncio
    async def test_post_invalid_payload_returns_400(self, user_id, master_key, master_keys):
        handler = _make_handler(user_id)
        # Missing 'driver' field
        handler.request.json = AsyncMock(return_value={"name": "test"})

        with patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, master_key, master_keys)):
            response = await handler.post()

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_post_invalid_json_returns_400(self, user_id, master_key, master_keys):
        handler = _make_handler(user_id)
        handler.request.json = AsyncMock(side_effect=Exception("bad json"))

        with patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, master_key, master_keys)):
            response = await handler.post()

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_post_vault_unavailable_returns_500(self, sample_credential, user_id):
        handler = _make_handler(user_id)
        handler.request.json = AsyncMock(return_value=sample_credential)

        with patch("parrot.handlers.credentials._load_vault_keys",
                   side_effect=RuntimeError("No vault keys")):
            response = await handler.post()

        assert response.status == 500

    @pytest.mark.asyncio
    async def test_post_calls_save_background_not_write(
        self, sample_credential, user_id, master_key, master_keys
    ):
        """POST must use save_background (fire-and-forget), not write."""
        handler = _make_handler(user_id)
        handler.request.json = AsyncMock(return_value=sample_credential)

        mock_db = AsyncMock()
        mock_db.documentdb_connect = AsyncMock()
        mock_db.read_one = AsyncMock(return_value=None)
        mock_db.save_background = MagicMock(return_value=MagicMock())

        with patch("parrot.handlers.credentials.DocumentDb", return_value=mock_db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, master_key, master_keys)):
            await handler.post()

        mock_db.save_background.assert_called_once()
        mock_db.write.assert_not_called()


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------

class TestGet:
    @pytest.mark.asyncio
    async def test_get_all_returns_dict(self, user_id, master_key, master_keys):
        handler = _make_handler(user_id)
        handler.request.match_info.get = MagicMock(return_value=None)  # no name

        from parrot.handlers.credentials_utils import encrypt_credential as real_encrypt
        enc1 = real_encrypt({"driver": "pg", "params": {}}, 1, master_key)
        enc2 = real_encrypt({"driver": "mysql", "params": {}}, 1, master_key)

        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db_cm)
        mock_db_cm.__aexit__ = AsyncMock(return_value=False)
        mock_db_cm.read = AsyncMock(return_value=[
            {"name": "pg-cred", "credential": enc1},
            {"name": "mysql-cred", "credential": enc2},
        ])

        with patch("parrot.handlers.credentials.DocumentDb", return_value=mock_db_cm), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, master_key, master_keys)):
            response = await handler.get()

        assert response.status == 200
        assert "pg-cred" in response.data
        assert "mysql-cred" in response.data

    @pytest.mark.asyncio
    async def test_get_single_returns_credential(self, user_id, master_key, master_keys):
        handler = _make_handler(user_id)
        handler.request.match_info.get = MagicMock(return_value="my-pg")

        from parrot.handlers.credentials_utils import encrypt_credential as real_encrypt
        enc = real_encrypt({"driver": "pg", "params": {"host": "localhost"}}, 1, master_key)

        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db_cm)
        mock_db_cm.__aexit__ = AsyncMock(return_value=False)
        mock_db_cm.read_one = AsyncMock(return_value={"name": "my-pg", "credential": enc})

        with patch("parrot.handlers.credentials.DocumentDb", return_value=mock_db_cm), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, master_key, master_keys)):
            response = await handler.get()

        assert response.status == 200
        assert response.data["name"] == "my-pg"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(self, user_id, master_key, master_keys):
        handler = _make_handler(user_id)
        handler.request.match_info.get = MagicMock(return_value="no-such-cred")

        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db_cm)
        mock_db_cm.__aexit__ = AsyncMock(return_value=False)
        mock_db_cm.read_one = AsyncMock(return_value=None)

        with patch("parrot.handlers.credentials.DocumentDb", return_value=mock_db_cm), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, master_key, master_keys)):
            response = await handler.get()

        assert response.status == 404


# ---------------------------------------------------------------------------
# PUT
# ---------------------------------------------------------------------------

class TestPut:
    @pytest.mark.asyncio
    async def test_put_updates_credential(self, sample_credential, user_id, master_key, master_keys):
        session: dict = {"user_id": user_id}
        handler = _make_handler(user_id, session=session)
        handler.request.match_info.get = MagicMock(return_value=sample_credential["name"])
        handler.request.json = AsyncMock(return_value=sample_credential)

        mock_db = AsyncMock()
        mock_db.documentdb_connect = AsyncMock()
        mock_db.read_one = AsyncMock(return_value={"name": sample_credential["name"], "created_at": datetime.now(timezone.utc)})
        mock_db.save_background = MagicMock()

        with patch("parrot.handlers.credentials.DocumentDb", return_value=mock_db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, master_key, master_keys)):
            response = await handler.put()

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_put_nonexistent_returns_404(self, sample_credential, user_id, master_key, master_keys):
        handler = _make_handler(user_id)
        handler.request.match_info.get = MagicMock(return_value="no-such-cred")
        handler.request.json = AsyncMock(return_value=sample_credential)

        mock_db = AsyncMock()
        mock_db.documentdb_connect = AsyncMock()
        mock_db.read_one = AsyncMock(return_value=None)
        mock_db.close = AsyncMock()

        with patch("parrot.handlers.credentials.DocumentDb", return_value=mock_db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, master_key, master_keys)):
            response = await handler.put()

        assert response.status == 404


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_credential(self, user_id, master_key, master_keys):
        session: dict = {
            "user_id": user_id,
            "_credentials:my-pg": {"driver": "pg", "params": {}},
        }
        handler = _make_handler(user_id, session=session)
        handler.request.match_info.get = MagicMock(return_value="my-pg")

        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db_cm)
        mock_db_cm.__aexit__ = AsyncMock(return_value=False)
        mock_db_cm.read_one = AsyncMock(return_value={"name": "my-pg"})
        mock_db_cm.delete = AsyncMock()

        with patch("parrot.handlers.credentials.DocumentDb", return_value=mock_db_cm):
            response = await handler.delete()

        assert response.status == 200
        assert "_credentials:my-pg" not in session
        mock_db_cm.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, user_id):
        handler = _make_handler(user_id)
        handler.request.match_info.get = MagicMock(return_value="no-such-cred")

        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db_cm)
        mock_db_cm.__aexit__ = AsyncMock(return_value=False)
        mock_db_cm.read_one = AsyncMock(return_value=None)

        with patch("parrot.handlers.credentials.DocumentDb", return_value=mock_db_cm):
            response = await handler.delete()

        assert response.status == 404
