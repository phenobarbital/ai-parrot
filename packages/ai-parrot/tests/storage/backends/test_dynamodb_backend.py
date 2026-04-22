"""Unit tests for parrot.storage.backends.dynamodb.ConversationDynamoDB.

TASK-824: Refactor ConversationDynamoDB to implement ConversationBackend — FEAT-116.
Updated to match code-review fixes (ReturnValues='ALL_OLD', narrowed exceptions).
"""
import pytest
from botocore.exceptions import ClientError
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


async def test_delete_turn_calls_delete_item_with_return_values():
    """Fix #1: delete_item must be called with ReturnValues='ALL_OLD' so
    we can detect whether the item actually existed."""
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    backend._conv_table = MagicMock()
    backend._art_table = MagicMock()
    # Simulate item found: DynamoDB returns {"Attributes": {...}} when item existed
    backend._conv_table.delete_item = AsyncMock(
        return_value={"Attributes": {"PK": "USER#u#AGENT#a", "SK": "THREAD#s#TURN#t1"}}
    )
    ok = await backend.delete_turn("u", "a", "s", "t1")
    assert ok is True
    backend._conv_table.delete_item.assert_awaited_once_with(
        Key={"PK": "USER#u#AGENT#a", "SK": "THREAD#s#TURN#t1"},
        ReturnValues="ALL_OLD",
    )


async def test_delete_turn_returns_false_when_item_not_found():
    """Fix #1: when DynamoDB returns no Attributes, the item did not exist."""
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    backend._conv_table = MagicMock()
    backend._art_table = MagicMock()
    # Empty response → item did not exist
    backend._conv_table.delete_item = AsyncMock(return_value={})
    ok = await backend.delete_turn("u", "a", "s", "does-not-exist")
    assert ok is False


async def test_delete_turn_returns_false_on_client_error():
    """Fix #10: only ClientError/BotoCoreError is caught — not bare Exception."""
    from botocore.exceptions import ClientError
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    backend._conv_table = MagicMock()
    backend._art_table = MagicMock()
    error_response = {"Error": {"Code": "ProvisionedThroughputExceededException"}}
    backend._conv_table.delete_item = AsyncMock(
        side_effect=ClientError(error_response, "DeleteItem")
    )
    ok = await backend.delete_turn("u", "a", "s", "t1")
    assert ok is False


async def test_initialize_is_idempotent():
    """Fix #9: calling initialize() twice must not create a second session."""
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    # Manually set connected state
    mock_table = MagicMock()
    backend._conv_table = mock_table
    backend._art_table = mock_table
    # Second initialize() should return immediately without touching session
    await backend.initialize()
    # Tables are still the same mock (not replaced)
    assert backend._conv_table is mock_table


def test_default_ttl_days():
    assert ConversationDynamoDB.DEFAULT_TTL_DAYS == 180


def test_build_pk_static():
    assert ConversationDynamoDB._build_pk("u", "a") == "USER#u#AGENT#a"
