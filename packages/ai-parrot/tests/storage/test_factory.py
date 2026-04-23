"""Unit tests for the backend factory and config wiring.

TASK-829: Backend Factory and Configuration Wiring — FEAT-116.
"""
from pathlib import Path

import pytest

from parrot.storage.backends import (
    build_conversation_backend,
    build_overflow_store,
    ConversationBackend,
    ConversationSQLiteBackend,
    ConversationDynamoDB,
    ConversationPostgresBackend,
    ConversationMongoBackend,
)
from parrot.storage.overflow import OverflowStore


async def test_factory_returns_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("PARROT_SQLITE_PATH", str(tmp_path / "parrot.db"))
    monkeypatch.setenv("PARROT_STORAGE_METRICS", "")
    backend = await build_conversation_backend()
    assert isinstance(backend, ConversationSQLiteBackend)
    assert isinstance(backend, ConversationBackend)


async def test_factory_returns_dynamodb(monkeypatch):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "dynamodb")
    monkeypatch.setenv("PARROT_STORAGE_METRICS", "")
    backend = await build_conversation_backend()
    assert isinstance(backend, ConversationDynamoDB)


async def test_factory_postgres_requires_dsn(monkeypatch):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("PARROT_STORAGE_METRICS", "")
    monkeypatch.delenv("PARROT_POSTGRES_DSN", raising=False)
    with pytest.raises(RuntimeError, match="PARROT_POSTGRES_DSN"):
        await build_conversation_backend()


async def test_factory_mongodb_requires_dsn(monkeypatch):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "mongodb")
    monkeypatch.setenv("PARROT_STORAGE_METRICS", "")
    monkeypatch.delenv("PARROT_MONGODB_DSN", raising=False)
    with pytest.raises(RuntimeError, match="PARROT_MONGODB_DSN"):
        await build_conversation_backend()


async def test_factory_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "firebase")
    monkeypatch.setenv("PARROT_STORAGE_METRICS", "")
    with pytest.raises(ValueError, match="Unknown PARROT_STORAGE_BACKEND"):
        await build_conversation_backend()


def test_overflow_local(monkeypatch, tmp_path):
    monkeypatch.setenv("PARROT_OVERFLOW_STORE", "local")
    monkeypatch.setenv("PARROT_OVERFLOW_LOCAL_PATH", str(tmp_path))
    store = build_overflow_store()
    assert isinstance(store, OverflowStore)


def test_overflow_unknown_raises(monkeypatch):
    monkeypatch.setenv("PARROT_OVERFLOW_STORE", "minio")
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "sqlite")
    with pytest.raises(ValueError, match="Unknown PARROT_OVERFLOW_STORE"):
        build_overflow_store()


def test_chat_storage_no_direct_dynamodb_import():
    """chat.py must not directly import ConversationDynamoDB."""
    src = (
        Path(__file__).resolve().parents[2] / "src" / "parrot" / "storage" / "chat.py"
    ).read_text()
    assert "from .dynamodb import ConversationDynamoDB" not in src
    assert "from parrot.storage.dynamodb import ConversationDynamoDB" not in src


def test_load_metrics_bad_path():
    from parrot.storage.backends import load_metrics_from_path
    with pytest.raises(RuntimeError):
        load_metrics_from_path("nonexistent.module:THING")
    with pytest.raises(RuntimeError):
        load_metrics_from_path("invalid-format-no-colon")
