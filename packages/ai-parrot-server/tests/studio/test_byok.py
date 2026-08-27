"""Tests for BYOK per-user LLM API keys (FEAT-467 TASK-2516).

Covers store+masked-list, plaintext never appearing in any response or
log record, unsupported-provider 400, missing-vault-master-keys 503,
delete removing both copies, and the ``resolve_user_api_key`` helper.

DocumentDB is faked in-memory; the navigator-session vault master keys
are a deterministic fixture (pattern hinted at by the spec's ``vault_keys``
fixture) so encryption/decryption round-trips genuinely.
"""
from __future__ import annotations

import json
import logging
from typing import ClassVar

import parrot.interfaces.documentdb as documentdb_module
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import byok as byok_module
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.byok import StudioKeysHandler, resolve_user_api_key

MASTER_KEY_ID = 1
MASTER_KEY = b"1" * 32
MASTER_KEYS = {MASTER_KEY_ID: MASTER_KEY}


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeDocumentDb:
    """In-memory stand-in for ``parrot.interfaces.documentdb.DocumentDb``."""

    docs: ClassVar[list] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def documentdb_connect(self):
        return None

    async def read_one(self, collection_name, query):
        for doc in self.docs:
            if doc.get("_collection") != collection_name:
                continue
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    async def read(self, collection_name, query):
        return [
            doc for doc in self.docs
            if doc.get("_collection") == collection_name
            and all(doc.get(k) == v for k, v in query.items())
        ]

    async def delete(self, collection_name, query):
        before = len(self.docs)
        self.docs[:] = [
            doc for doc in self.docs
            if not (
                doc.get("_collection") == collection_name
                and all(doc.get(k) == v for k, v in query.items())
            )
        ]
        return {"deleted": before - len(self.docs)}

    def save_background(self, collection_name, data, on_success=None, on_error=None):
        record = dict(data)
        record["_collection"] = collection_name
        # Upsert semantics matching the handler's own duplicate check.
        self.docs[:] = [
            d for d in self.docs
            if not (
                d.get("_collection") == collection_name
                and d.get("user_id") == record.get("user_id")
                and d.get("provider") == record.get("provider")
            )
        ]
        self.docs.append(record)

        class _FakeTask:
            def __await__(self_inner):
                async def _noop():
                    return None
                return _noop().__await__()

        return _FakeTask()


@pytest.fixture(autouse=True)
def patch_vault_keys(monkeypatch):
    try:
        import navigator_session.vault.config as vault_config_module
    except ImportError:
        pytest.skip("navigator_session.vault not installed")
    monkeypatch.setattr(vault_config_module, "load_master_keys", lambda: MASTER_KEYS)
    monkeypatch.setattr(vault_config_module, "get_active_key_id", lambda: MASTER_KEY_ID)
    monkeypatch.setattr(byok_module, "load_master_keys", lambda: MASTER_KEYS)
    monkeypatch.setattr(byok_module, "get_active_key_id", lambda: MASTER_KEY_ID)


@pytest.fixture
def fake_db(monkeypatch):
    _FakeDocumentDb.docs = []
    monkeypatch.setattr(byok_module, "DocumentDb", _FakeDocumentDb)
    monkeypatch.setattr(documentdb_module, "DocumentDb", _FakeDocumentDb)
    return _FakeDocumentDb


@pytest.fixture
def app() -> web.Application:
    return web.Application()


def _make_handler(app, *, method="GET", path="/x", match_info=None,
                   json_body=None, owner="1", session=None):
    from unittest.mock import AsyncMock

    request = make_mocked_request(method, path, match_info=match_info or {}, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    handler = StudioKeysHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id=owner))
    handler._resolve_session = AsyncMock(return_value=session if session is not None else {})
    return handler


class TestByok:
    async def test_store_and_masked_list(self, app, fake_db):
        handler = _make_handler(
            app, method="POST", path="/keys",
            json_body={"provider": "anthropic", "api_key": "sk-ant-abcdef1234"},
        )
        response = await _unwrap(StudioKeysHandler.post)(handler)
        assert response.status == 201
        body = await _decode(response)
        assert body["provider"] == "anthropic"
        assert body["masked"] == "sk-…1234"
        assert "sk-ant-abcdef1234" not in json.dumps(body)

        list_handler = _make_handler(app, method="GET", path="/keys")
        list_response = await _unwrap(StudioKeysHandler.get)(list_handler)
        assert list_response.status == 200
        list_body = await _decode(list_response)
        assert list_body["count"] == 1
        assert list_body["keys"][0]["provider"] == "anthropic"
        assert list_body["keys"][0]["masked"] == "sk-…1234"
        assert "sk-ant-abcdef1234" not in json.dumps(list_body)

    async def test_plaintext_never_in_response_or_logs(self, app, fake_db, caplog):
        secret = "sk-ant-super-secret-value-xyz"
        with caplog.at_level(logging.DEBUG):
            handler = _make_handler(
                app, method="POST", path="/keys",
                json_body={"provider": "anthropic", "api_key": secret},
            )
            response = await _unwrap(StudioKeysHandler.post)(handler)

        assert response.status == 201
        assert secret not in json.dumps(await _decode(response))
        for record in caplog.records:
            assert secret not in record.getMessage()

    async def test_session_vault_hot_copy_written(self, app, fake_db):
        session = {}
        handler = _make_handler(
            app, method="POST", path="/keys", session=session,
            json_body={"provider": "openai", "api_key": "sk-openai-secret-9999"},
        )
        response = await _unwrap(StudioKeysHandler.post)(handler)
        assert response.status == 201
        assert "_byok:openai" in session
        assert "sk-openai-secret-9999" not in str(session["_byok:openai"])

    async def test_unsupported_provider_400(self, app, fake_db):
        handler = _make_handler(
            app, method="POST", path="/keys",
            json_body={"provider": "not-a-real-provider", "api_key": "sk-whatever"},
        )
        response = await _unwrap(StudioKeysHandler.post)(handler)
        assert response.status == 400
        assert (await _decode(response))["code"] == "invalid_provider"

    async def test_missing_master_keys_503(self, app, fake_db, monkeypatch):
        monkeypatch.setattr(byok_module, "load_master_keys", None)
        monkeypatch.setattr(byok_module, "get_active_key_id", None)

        handler = _make_handler(
            app, method="POST", path="/keys",
            json_body={"provider": "anthropic", "api_key": "sk-ant-whatever"},
        )
        response = await _unwrap(StudioKeysHandler.post)(handler)
        assert response.status == 503
        assert (await _decode(response))["code"] == "vault_unavailable"

    async def test_delete_removes_both_copies(self, app, fake_db):
        session = {}
        store_handler = _make_handler(
            app, method="POST", path="/keys", session=session,
            json_body={"provider": "google", "api_key": "sk-google-secret-0001"},
        )
        await _unwrap(StudioKeysHandler.post)(store_handler)
        assert "_byok:google" in session
        assert len(fake_db.docs) == 1

        delete_handler = _make_handler(
            app, method="DELETE", path="/keys/google",
            match_info={"provider": "google"}, session=session,
        )
        response = await _unwrap(StudioKeysHandler.delete)(delete_handler)
        assert response.status == 200
        assert "_byok:google" not in session
        assert fake_db.docs == []

    async def test_provider_normalized_lowercase_on_store(self, app, fake_db):
        handler = _make_handler(
            app, method="POST", path="/keys",
            json_body={"provider": "ANTHROPIC", "api_key": "sk-ant-mixedcase123"},
        )
        response = await _unwrap(StudioKeysHandler.post)(handler)
        assert response.status == 201
        assert (await _decode(response))["provider"] == "anthropic"


class TestResolveUserApiKey:
    async def test_resolve_user_api_key_after_store(self, app, fake_db):
        store_handler = _make_handler(
            app, method="POST", path="/keys", owner="42",
            json_body={"provider": "anthropic", "api_key": "sk-ant-resolvable-key"},
        )
        await _unwrap(StudioKeysHandler.post)(store_handler)

        resolved = await resolve_user_api_key(app, "42", "anthropic")
        assert resolved == "sk-ant-resolvable-key"

    async def test_resolve_user_api_key_absent_returns_none(self, app, fake_db):
        resolved = await resolve_user_api_key(app, "no-such-user", "anthropic")
        assert resolved is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
