"""Unit tests for parrot.storage.backends.dynamodb.ConversationDynamoDB.

TASK-824: Refactor ConversationDynamoDB to implement ConversationBackend — FEAT-116.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.backends.dynamodb import ConversationDynamoDB


def test_is_subclass_of_conversation_backend():
    assert issubclass(ConversationDynamoDB, ConversationBackend)


def test_shim_still_imports():
    from parrot.storage.dynamodb import ConversationDynamoDB as Shimmed  # noqa: F401
    assert Shimmed is ConversationDynamoDB


def test_build_overflow_prefix_matches_existing_s3_layout():
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    assert (
        backend.build_overflow_prefix("u", "a", "s", "aid")
        == "artifacts/USER#u#AGENT#a/THREAD#s/aid"
    )


async def test_delete_turn_not_connected_returns_false():
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    # _conv_table is None by default → is_connected == False
    ok = await backend.delete_turn("u", "a", "s", "t1")
    assert ok is False


async def test_delete_turn_calls_delete_item():
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    backend._conv_table = MagicMock()
    backend._art_table = MagicMock()
    backend._conv_table.delete_item = AsyncMock(return_value={})
    ok = await backend.delete_turn("u", "a", "s", "t1")
    assert ok is True
    backend._conv_table.delete_item.assert_awaited_once_with(
        Key={"PK": "USER#u#AGENT#a", "SK": "THREAD#s#TURN#t1"}
    )


async def test_delete_turn_returns_false_on_error():
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    backend._conv_table = MagicMock()
    backend._art_table = MagicMock()
    backend._conv_table.delete_item = AsyncMock(side_effect=Exception("boom"))
    ok = await backend.delete_turn("u", "a", "s", "t1")
    assert ok is False


def test_default_ttl_days():
    assert ConversationDynamoDB.DEFAULT_TTL_DAYS == 180


def test_build_pk_static():
    assert ConversationDynamoDB._build_pk("u", "a") == "USER#u#AGENT#a"
