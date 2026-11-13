"""Shared pytest fixtures for storage backend contract tests.

TASK-830: Shared Backend Contract Test Suite — FEAT-116.
"""
import os
import pytest

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.backends.sqlite import ConversationSQLiteBackend

POSTGRES_DSN = os.environ.get("POSTGRES_TEST_DSN")
MONGO_DSN = os.environ.get("MONGO_TEST_DSN")


def _dynamodb_backend():
    """Return a ConversationDynamoDB served by a moto SERVER (aioboto3 talks aiohttp, which ``mock_aws()`` does
    not intercept), or skip if moto is not available."""
    try:
        import moto  # noqa: F401
        from moto.server import ThreadedMotoServer
    except ImportError:
        pytest.skip("moto[server] not installed — skipping DynamoDB contract tests")

    try:
        import socket
        import uuid

        import boto3
        from parrot.storage.backends.dynamodb import ConversationDynamoDB

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = ThreadedMotoServer(port=port, verbose=False)
        server.start()
        endpoint = f"http://127.0.0.1:{port}"
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
        os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
        client = boto3.client("dynamodb", endpoint_url=endpoint, region_name="us-east-1")
        suffix = uuid.uuid4().hex[:8]
        names = (f"parrot-conversations-{suffix}", f"parrot-artifacts-{suffix}")
        for table_name in names:
            client.create_table(
                TableName=table_name,
                KeySchema=[
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )

        backend = ConversationDynamoDB(
            conversations_table=names[0],
            artifacts_table=names[1],
            dynamo_params={"region_name": "us-east-1", "endpoint_url": endpoint,
                           "aws_access_key_id": "x", "aws_secret_access_key": "x"},
        )
        # Store the server handle (``stop()``) so the fixture can stop it later
        backend._moto_mock = server
        return backend
    except Exception as exc:
        pytest.skip(f"DynamoDB moto setup failed: {exc}")


@pytest.fixture(params=["sqlite", "dynamodb", "postgres", "mongodb"])
async def any_backend(request, tmp_path) -> ConversationBackend:
    """Parametrized fixture yielding each ConversationBackend implementation.

    - sqlite: always runs.
    - dynamodb: runs with moto; skips if moto not installed.
    - postgres: skips if POSTGRES_TEST_DSN not set.
    - mongodb: skips if MONGO_TEST_DSN not set.
    """
    name = request.param
    moto_mock = None

    if name == "sqlite":
        b = ConversationSQLiteBackend(
            path=str(tmp_path / f"contract-{request.node.name[:20]}.db")
        )
    elif name == "dynamodb":
        b = _dynamodb_backend()
        moto_mock = getattr(b, "_moto_mock", None)
    elif name == "postgres":
        if not POSTGRES_DSN:
            pytest.skip("POSTGRES_TEST_DSN not set — skipping Postgres contract suite")
        from parrot.storage.backends.postgres import ConversationPostgresBackend
        b = ConversationPostgresBackend(dsn=POSTGRES_DSN)
    elif name == "mongodb":
        if not MONGO_DSN:
            pytest.skip("MONGO_TEST_DSN not set — skipping MongoDB contract suite")
        from parrot.storage.backends.mongodb import ConversationMongoBackend
        b = ConversationMongoBackend(
            dsn=MONGO_DSN,
            database=f"parrot_test_{request.node.name[:20]}",
        )
    else:
        pytest.skip(f"Unknown backend: {name}")

    await b.initialize()
    yield b

    try:
        await b.delete_thread_cascade("u", "a", "s1")
        await b.delete_session_artifacts("u", "a", "s1")
    except Exception:
        pass
    try:
        await b.close()
    except Exception:
        pass
    if moto_mock:
        try:
            moto_mock.stop()
        except Exception:
            pass
