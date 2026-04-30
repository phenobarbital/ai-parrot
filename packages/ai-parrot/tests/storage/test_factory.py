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


async def test_dynamodb_uses_backend_aws_env_vars(monkeypatch):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "dynamodb")
    monkeypatch.setenv("PARROT_STORAGE_METRICS", "")
    monkeypatch.setenv("BACKEND_AWS_ACCESS_KEY", "AKIA_BACKEND")
    monkeypatch.setenv("BACKEND_AWS_SECRET_KEY", "secret_backend")
    monkeypatch.setenv("BACKEND_AWS_REGION", "eu-west-1")
    monkeypatch.delenv("DYNAMODB_AWS_PROFILE", raising=False)
    backend = await build_conversation_backend()
    assert isinstance(backend, ConversationDynamoDB)
    params = backend._dynamo_params
    assert params["aws_access_key_id"] == "AKIA_BACKEND"
    assert params["aws_secret_access_key"] == "secret_backend"
    assert params["region_name"] == "eu-west-1"


async def test_dynamodb_does_not_use_general_aws_keys(monkeypatch):
    """General AWS_ACCESS_KEY/AWS_SECRET_KEY must NOT be picked up — they
    belong to S3 and other shared services."""
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "dynamodb")
    monkeypatch.setenv("PARROT_STORAGE_METRICS", "")
    monkeypatch.setenv("AWS_ACCESS_KEY", "AKIA_GENERAL")
    monkeypatch.setenv("AWS_SECRET_KEY", "secret_general")
    monkeypatch.delenv("BACKEND_AWS_ACCESS_KEY", raising=False)
    monkeypatch.delenv("BACKEND_AWS_SECRET_KEY", raising=False)
    monkeypatch.delenv("DYNAMODB_AWS_PROFILE", raising=False)
    backend = await build_conversation_backend()
    params = backend._dynamo_params
    assert "aws_access_key_id" not in params
    assert "aws_secret_access_key" not in params


async def test_dynamodb_uses_aws_credentials_profile(monkeypatch):
    from parrot import conf
    monkeypatch.setitem(
        conf.AWS_CREDENTIALS,
        "myprofile",
        {
            "aws_key": "AKIA_PROFILE",
            "aws_secret": "secret_profile",
            "region_name": "ap-south-1",
        },
    )
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "dynamodb")
    monkeypatch.setenv("PARROT_STORAGE_METRICS", "")
    monkeypatch.setenv("DYNAMODB_AWS_PROFILE", "myprofile")
    backend = await build_conversation_backend()
    params = backend._dynamo_params
    assert params["aws_access_key_id"] == "AKIA_PROFILE"
    assert params["aws_secret_access_key"] == "secret_profile"
    assert params["region_name"] == "ap-south-1"


async def test_dynamodb_profile_missing_raises(monkeypatch):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "dynamodb")
    monkeypatch.setenv("PARROT_STORAGE_METRICS", "")
    monkeypatch.setenv("DYNAMODB_AWS_PROFILE", "doesnotexist")
    with pytest.raises(RuntimeError, match="not found in AWS_CREDENTIALS"):
        await build_conversation_backend()


async def test_dynamodb_profile_incomplete_raises(monkeypatch):
    from parrot import conf
    monkeypatch.setitem(
        conf.AWS_CREDENTIALS,
        "broken",
        {"region_name": "us-east-1"},  # no key/secret
    )
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "dynamodb")
    monkeypatch.setenv("PARROT_STORAGE_METRICS", "")
    monkeypatch.setenv("DYNAMODB_AWS_PROFILE", "broken")
    with pytest.raises(RuntimeError, match="missing aws_key/aws_secret"):
        await build_conversation_backend()


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
