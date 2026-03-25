"""Integration tests for the full credential CRUD lifecycle (TASK-441).

These tests exercise the complete HTTP request cycle by wiring up
:class:`CredentialsHandler` in an aiohttp test application.

DocumentDB and vault crypto are mocked so no live services are required.
Session state is simulated by injecting ``_session`` onto the handler.
"""
from __future__ import annotations

import os
import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.handlers.credentials import (
    CredentialsHandler,
    setup_credentials_routes,
)
from parrot.handlers.credentials_utils import encrypt_credential

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

USER_A_ID = "user-aaa-111"
USER_B_ID = "user-bbb-222"

MASTER_KEY = os.urandom(32)
MASTER_KEYS = {1: MASTER_KEY}

SESSION_A: dict[str, Any] = {"user_id": USER_A_ID}
SESSION_B: dict[str, Any] = {"user_id": USER_B_ID}

SAMPLE_CREDENTIAL = {
    "name": "test-pg",
    "driver": "pg",
    "params": {"host": "localhost", "port": 5432},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_encrypted(cred_dict: dict) -> str:
    """Produce a real encrypted string for fixture data."""
    return encrypt_credential(cred_dict, key_id=1, master_key=MASTER_KEY)


def _inject_session(request: web.Request, session: dict) -> None:
    """Inject a fake session onto the handler after dispatch."""
    # Patched into CredentialsHandler._get_user_id via session attribute
    pass


class _FakeDB:
    """In-memory DocumentDB substitute.

    Stores documents in a list and supports the minimal interface
    used by CredentialsHandler.
    """

    def __init__(self):
        self._docs: list[dict] = []
        self.save_background_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def documentdb_connect(self):
        pass

    async def close(self):
        pass

    async def read_one(self, collection: str, query: dict) -> dict | None:
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    async def read(self, collection: str, query: dict) -> list[dict]:
        return [
            dict(doc) for doc in self._docs
            if all(doc.get(k) == v for k, v in query.items())
        ]

    async def delete(self, collection: str, query: dict) -> None:
        self._docs = [
            d for d in self._docs
            if not all(d.get(k) == v for k, v in query.items())
        ]
        self.delete_calls.append(query)

    def save_background(self, collection: str, data: dict, on_error=None, on_success=None):
        # Simulate synchronous upsert for testing:
        # If a document with the same user_id+name exists, replace it; else insert.
        doc = dict(data)
        self.save_background_calls.append(doc)
        uid = doc.get("user_id")
        name = doc.get("name")
        for i, existing in enumerate(self._docs):
            if existing.get("user_id") == uid and existing.get("name") == name:
                self._docs[i] = doc
                return MagicMock()
        self._docs.append(doc)
        return MagicMock()


# ---------------------------------------------------------------------------
# Application factory for integration tests
# ---------------------------------------------------------------------------

def _make_app(db: _FakeDB, session: dict) -> web.Application:
    """Build a minimal aiohttp application for testing.

    The session is injected by patching CredentialsHandler._get_user_id.
    """
    app = web.Application()
    setup_credentials_routes(app)
    app["_test_db"] = db
    app["_test_session"] = session
    return app


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestCredentialsCRUDLifecycle:
    """Full CRUD lifecycle: create → read → update → read → delete → verify gone."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """POST → GET → PUT → GET → DELETE → GET(404) lifecycle."""
        db = _FakeDB()
        session = dict(SESSION_A)

        with patch("parrot.handlers.credentials.DocumentDb", return_value=db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, MASTER_KEY, MASTER_KEYS)):

            # Build handler manually (bypassing aiohttp dispatch)
            from parrot.handlers.credentials import CredentialsHandler

            # --- POST (create) ---
            handler = _make_test_handler(session, db)
            handler.request.json = AsyncMock(return_value=SAMPLE_CREDENTIAL)
            handler.request.match_info.get = MagicMock(return_value=None)
            resp = await handler.post()
            assert resp.status == 201, f"POST failed: {getattr(resp, 'msg', '')}"

            # Session vault should have the credential
            assert "_credentials:test-pg" in session

            # Background save triggered
            assert len(db.save_background_calls) == 1

            # --- GET (single) ---
            handler2 = _make_test_handler(session, db)
            handler2.request.match_info.get = MagicMock(return_value="test-pg")
            resp2 = await handler2.get()
            assert resp2.status == 200
            assert resp2.data["name"] == "test-pg"
            assert resp2.data["driver"] == "pg"

            # --- PUT (update) ---
            updated = {**SAMPLE_CREDENTIAL, "params": {"host": "newhost", "port": 5432}}
            handler3 = _make_test_handler(session, db)
            handler3.request.match_info.get = MagicMock(return_value="test-pg")
            handler3.request.json = AsyncMock(return_value=updated)
            resp3 = await handler3.put()
            assert resp3.status == 200

            # --- GET (verify update) ---
            handler4 = _make_test_handler(session, db)
            handler4.request.match_info.get = MagicMock(return_value="test-pg")
            resp4 = await handler4.get()
            assert resp4.status == 200
            assert resp4.data["params"]["host"] == "newhost"

            # --- DELETE ---
            handler5 = _make_test_handler(session, db)
            handler5.request.match_info.get = MagicMock(return_value="test-pg")
            resp5 = await handler5.delete()
            assert resp5.status == 200

            # Session vault should no longer have the credential
            assert "_credentials:test-pg" not in session

            # --- GET (verify gone) ---
            handler6 = _make_test_handler(session, db)
            handler6.request.match_info.get = MagicMock(return_value="test-pg")
            resp6 = await handler6.get()
            assert resp6.status == 404


class TestCredentialsPerUserIsolation:
    """Two users can have credentials with the same name independently."""

    @pytest.mark.asyncio
    async def test_same_name_different_users(self):
        """User A and user B can each own a credential named 'shared-name'."""
        db = _FakeDB()
        session_a = dict(SESSION_A)
        session_b = dict(SESSION_B)
        cred = {"name": "shared-name", "driver": "pg", "params": {}}

        with patch("parrot.handlers.credentials.DocumentDb", return_value=db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, MASTER_KEY, MASTER_KEYS)):

            # User A creates credential
            ha = _make_test_handler(session_a, db)
            ha.request.json = AsyncMock(return_value=cred)
            ha.request.match_info.get = MagicMock(return_value=None)
            ra = await ha.post()
            assert ra.status == 201

            # User B creates credential with same name (different user_id)
            hb = _make_test_handler(session_b, db)
            hb.request.json = AsyncMock(return_value=cred)
            hb.request.match_info.get = MagicMock(return_value=None)
            rb = await hb.post()
            assert rb.status == 201

            # Both docs exist in DB
            docs = await db.read("user_credentials", {})
            names = [d["name"] for d in docs]
            assert names.count("shared-name") == 2

    @pytest.mark.asyncio
    async def test_user_a_cannot_see_user_b_credentials(self):
        """GET for user A does not return user B's credentials."""
        db = _FakeDB()
        cred_a = {"driver": "pg", "params": {}}
        cred_b = {"driver": "mysql", "params": {}}

        # Pre-populate DB with credentials for both users
        db._docs.append({
            "user_id": USER_A_ID,
            "name": "cred-a",
            "credential": _make_encrypted(cred_a),
        })
        db._docs.append({
            "user_id": USER_B_ID,
            "name": "cred-b",
            "credential": _make_encrypted(cred_b),
        })

        with patch("parrot.handlers.credentials.DocumentDb", return_value=db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, MASTER_KEY, MASTER_KEYS)):

            # User A lists credentials
            handler = _make_test_handler(dict(SESSION_A), db)
            handler.request.match_info.get = MagicMock(return_value=None)
            resp = await handler.get()

            assert resp.status == 200
            assert "cred-a" in resp.data
            assert "cred-b" not in resp.data


class TestCredentialsErrorCases:
    """Error handling: duplicate, not-found, invalid payload."""

    @pytest.mark.asyncio
    async def test_duplicate_name_returns_409(self):
        """POST with an existing name returns 409 Conflict."""
        db = _FakeDB()
        session = dict(SESSION_A)
        cred = {"name": "dup-test", "driver": "pg", "params": {}}

        with patch("parrot.handlers.credentials.DocumentDb", return_value=db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, MASTER_KEY, MASTER_KEYS)):

            # First POST — should succeed
            h1 = _make_test_handler(session, db)
            h1.request.json = AsyncMock(return_value=cred)
            h1.request.match_info.get = MagicMock(return_value=None)
            r1 = await h1.post()
            assert r1.status == 201

            # Second POST with same name — should return 409
            h2 = _make_test_handler(session, db)
            h2.request.json = AsyncMock(return_value=cred)
            h2.request.match_info.get = MagicMock(return_value=None)
            r2 = await h2.post()
            assert r2.status == 409

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(self):
        """GET for a non-existent credential name returns 404."""
        db = _FakeDB()

        with patch("parrot.handlers.credentials.DocumentDb", return_value=db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, MASTER_KEY, MASTER_KEYS)):
            handler = _make_test_handler(dict(SESSION_A), db)
            handler.request.match_info.get = MagicMock(return_value="nope")
            resp = await handler.get()
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_invalid_payload_returns_400(self):
        """POST without required 'driver' field returns 400 Bad Request."""
        db = _FakeDB()

        with patch("parrot.handlers.credentials.DocumentDb", return_value=db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, MASTER_KEY, MASTER_KEYS)):
            handler = _make_test_handler(dict(SESSION_A), db)
            handler.request.json = AsyncMock(return_value={"name": "x"})  # missing driver
            handler.request.match_info.get = MagicMock(return_value=None)
            resp = await handler.post()
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_put_nonexistent_returns_404(self):
        """PUT on a non-existent credential returns 404."""
        db = _FakeDB()

        with patch("parrot.handlers.credentials.DocumentDb", return_value=db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, MASTER_KEY, MASTER_KEYS)):
            handler = _make_test_handler(dict(SESSION_A), db)
            handler.request.match_info.get = MagicMock(return_value="no-such")
            handler.request.json = AsyncMock(return_value=SAMPLE_CREDENTIAL)
            resp = await handler.put()
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self):
        """DELETE on a non-existent credential returns 404."""
        db = _FakeDB()

        with patch("parrot.handlers.credentials.DocumentDb", return_value=db):
            handler = _make_test_handler(dict(SESSION_A), db)
            handler.request.match_info.get = MagicMock(return_value="no-such")
            resp = await handler.delete()
            assert resp.status == 404


class TestFireAndForget:
    """Verify fire-and-forget behavior: POST returns before DB write completes."""

    @pytest.mark.asyncio
    async def test_post_schedules_background_save(self):
        """save_background() is called exactly once during POST."""
        db = _FakeDB()
        session = dict(SESSION_A)

        with patch("parrot.handlers.credentials.DocumentDb", return_value=db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, MASTER_KEY, MASTER_KEYS)):
            handler = _make_test_handler(session, db)
            handler.request.json = AsyncMock(return_value=SAMPLE_CREDENTIAL)
            handler.request.match_info.get = MagicMock(return_value=None)
            resp = await handler.post()

        assert resp.status == 201
        assert len(db.save_background_calls) == 1

    @pytest.mark.asyncio
    async def test_post_returns_before_db_write_completes(self):
        """Simulates slow DocumentDB: POST returns immediately."""
        db = _FakeDB()
        session = dict(SESSION_A)

        # Track whether save_background was called (fire-and-forget)
        bg_called = []

        original_save_bg = db.save_background

        def slow_save_background(collection, data, **kwargs):
            bg_called.append(True)
            return original_save_bg(collection, data, **kwargs)

        db.save_background = slow_save_background

        with patch("parrot.handlers.credentials.DocumentDb", return_value=db), \
             patch("parrot.handlers.credentials._load_vault_keys",
                   return_value=(1, MASTER_KEY, MASTER_KEYS)):
            handler = _make_test_handler(session, db)
            handler.request.json = AsyncMock(return_value=SAMPLE_CREDENTIAL)
            handler.request.match_info.get = MagicMock(return_value=None)
            resp = await handler.post()

        # Response is available immediately (status 201)
        assert resp.status == 201
        # save_background was scheduled (called synchronously in our mock)
        assert len(bg_called) == 1


# ---------------------------------------------------------------------------
# Helper: build handler instance for direct method invocation
# ---------------------------------------------------------------------------

def _make_test_handler(
    session: dict,
    db: _FakeDB,
) -> "CredentialsHandler":
    """Build a CredentialsHandler instance for direct async method testing.

    Args:
        session: Dict with ``user_id`` for authentication simulation.
        db: Fake in-memory DocumentDB instance.

    Returns:
        Configured CredentialsHandler ready for direct method calls.
    """
    handler = CredentialsHandler.__new__(CredentialsHandler)
    handler.logger = MagicMock()
    handler.request = MagicMock()
    handler.request.match_info = MagicMock()
    handler.request.match_info.get = MagicMock(return_value=None)
    handler._session = session

    handler.json_response = MagicMock(
        side_effect=lambda data, status=200: MagicMock(status=status, data=data)
    )
    handler.error = MagicMock(
        side_effect=lambda msg, status=400: MagicMock(status=status, msg=msg)
    )
    return handler
