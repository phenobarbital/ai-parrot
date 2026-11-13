"""FEAT-886 M8 — shared durable contract + DynamoDB-specific tests against a real DynamoDB API (moto server mode).

Skipped without ``moto[server]``.
"""
from __future__ import annotations

import socket
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

moto_server = pytest.importorskip("moto.server", reason="moto[server] not installed — skipping DynamoDB durable contract")
boto3 = pytest.importorskip("boto3")
from botocore.exceptions import ClientError  # noqa: E402

from parrot.storage.backends.dynamodb import ConversationDynamoDB  # noqa: E402
from parrot.storage.errors import ConversationDeletedError, StorageUnavailableError  # noqa: E402

from .. import durable_contract  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
TABLE = "parrot-conv-test"


@pytest.fixture(scope="module")
def endpoint():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = moto_server.ThreadedMotoServer(port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture
async def backend(endpoint, monkeypatch):
    for k, v in (("AWS_ACCESS_KEY_ID", "x"), ("AWS_SECRET_ACCESS_KEY", "x"), ("AWS_DEFAULT_REGION", "us-east-1")):
        monkeypatch.setenv(k, v)
    name = f"{TABLE}-{uuid.uuid4().hex[:8]}"
    client = boto3.client("dynamodb", endpoint_url=endpoint, region_name="us-east-1")
    client.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
                        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                              {"AttributeName": "SK", "AttributeType": "S"}])
    art = f"{name}-art"
    client.create_table(TableName=art, BillingMode="PAY_PER_REQUEST",
                        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
                        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                              {"AttributeName": "SK", "AttributeType": "S"}])
    b = ConversationDynamoDB(conversations_table=name, artifacts_table=art,
                             dynamo_params={"region_name": "us-east-1", "endpoint_url": endpoint,
                                            "aws_access_key_id": "x", "aws_secret_access_key": "x"})
    await b.initialize()
    yield b
    await b.close()


@asynccontextmanager
async def _inject_write_failure(backend):
    client = backend._resource.meta.client
    original = client.transact_write_items

    async def boom(*a, **kw):
        raise ClientError({"Error": {"Code": "InternalServerError", "Message": "injected"}}, "TransactWriteItems")

    client.transact_write_items = boom
    try:
        yield
    finally:
        client.transact_write_items = original


async def _seed_legacy(backend, session_id, rows):
    pk = backend._build_pk(durable_contract.USER, durable_contract.AGENT)
    for row in rows:  # pre-FEAT-886 canonical items: no chrono_sk, no companion
        await backend._conv_table.put_item(Item={
            "PK": pk, "SK": f"THREAD#{session_id}#TURN#{row['turn_id']}", "type": "turn", "session_id": session_id,
            **row})


@pytest.fixture
def harness(backend):
    async def expire(session_id):  # TTL simulation: the transcript items vanish, tombstones must not
        pk = backend._build_pk(durable_contract.USER, durable_contract.AGENT)
        from boto3.dynamodb.conditions import Key

        resp = await backend._conv_table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with(f"THREAD#{session_id}"))
        for item in resp.get("Items", []):
            await backend._conv_table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    return durable_contract.DurableHarness(
        backend=backend,
        disconnect=backend.close,
        inject_write_failure=lambda: _inject_write_failure(backend),
        seed_legacy=lambda sid, rows: _seed_legacy(backend, sid, rows),
        expire_transcript=expire,
    )


@pytest.mark.parametrize("check", durable_contract.ALL_CHECKS, ids=lambda c: c.__name__)
async def test_dynamodb_durable_contract(check, harness):
    await check(harness)


async def test_transaction_accepts_native_types(backend):
    await backend.put_turn("u", "a", "s", "t1", {"timestamp": T0.isoformat(), "sequence": 1, "cost_usd": 0.42,
                                                 "usage": {"total_tokens": 8}})
    [row] = await backend.query_turn_window("u", "a", "s", 5)
    assert row["cost_usd"] == 0.42 and row["usage"] == {"total_tokens": 8}


async def test_rejected_put_writes_nothing(backend):
    await backend.put_tombstone("u", "a", "s")
    with pytest.raises(ConversationDeletedError):
        await backend.put_turn("u", "a", "s", "t1", {"timestamp": T0.isoformat(), "sequence": 1})
    resp = await backend._conv_table.scan()
    assert [i["SK"] for i in resp["Items"]] == ["TOMB#s"]


async def test_tombstone_and_marker_items_have_no_ttl(backend):
    await backend.put_turn("u", "a", "s", "t1", {"timestamp": T0.isoformat(), "sequence": 1})
    await backend.put_tombstone("u", "a", "s2")
    items = {i["SK"]: i for i in (await backend._conv_table.scan())["Items"]}
    assert "ttl" not in items["TOMB#s2"] and "ttl" not in items["INDEXSTATE#s"]
    assert "ttl" in items["THREAD#s#TURN#t1"]


async def test_delete_turn_removes_the_companion_and_cascade_keeps_tombstones(backend):
    await backend.put_turn("u", "a", "s", "t1", {"timestamp": T0.isoformat(), "sequence": 1})
    assert await backend.delete_turn("u", "a", "s", "t1") is True
    await backend.put_tombstone("u", "a", "s")
    await backend.delete_thread_cascade("u", "a", "s")
    sks = [i["SK"] for i in (await backend._conv_table.scan())["Items"]]
    assert not any("CHRONO" in sk for sk in sks) and "TOMB#s" in sks


async def test_equal_timestamp_ties_break_on_turn_id(backend):
    for tid in ("c", "a", "d", "b"):
        await backend.put_turn("u", "a", "s", tid, {"timestamp": T0.isoformat(), "sequence": 1})
    assert [t["turn_id"] for t in await backend.query_turn_window("u", "a", "s", 3)] == ["b", "c", "d"]


async def test_disconnected_raises(endpoint):
    b = ConversationDynamoDB("x", "y", {"region_name": "us-east-1"})
    with pytest.raises(StorageUnavailableError):
        await b.query_turn_window("u", "a", "s", 1)


async def test_sequences_of_different_widths_order_numerically(backend):
    for seq in (100, 2, 10):  # equal timestamp: only the zero-padded sequence orders them
        await backend.put_turn("u", "a", "s", f"t{seq}", {"timestamp": T0.isoformat(), "sequence": seq})
    assert [t["sequence"] for t in await backend.query_turn_window("u", "a", "s", 5)] == [2, 10, 100]


async def test_lost_ordering_race_converges_on_the_first_writer(backend):
    await backend.put_turn("u", "a", "s", "t1", {"timestamp": T0.isoformat(), "sequence": 1, "user_message": "first"})
    real = backend._get_item
    state = {"hidden": False}

    async def blind_once(pk, sk):
        if sk.endswith("#TURN#t1") and not state["hidden"]:
            state["hidden"] = True
            return None  # the canonical turn "appeared" after this read: the conditional Put must abort us
        return await real(pk, sk)

    backend._get_item = blind_once
    try:
        later = (T0 + timedelta(hours=5)).isoformat()
        await backend.put_turn("u", "a", "s", "t1", {"timestamp": later, "sequence": 9, "user_message": "retry"})
    finally:
        backend._get_item = real
    [row] = await backend.query_turn_window("u", "a", "s", 5)
    assert row["sequence"] == 1 and row["timestamp"] == T0.isoformat() and row["user_message"] == "retry"
    chrono = [i for i in (await backend._conv_table.scan())["Items"] if i["SK"].startswith("THREAD#s#CHRONO#")]
    assert len(chrono) == 1
