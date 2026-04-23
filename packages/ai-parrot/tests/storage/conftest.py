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
    """Return a ConversationDynamoDB with moto mocks, or skip if moto not available."""
    try:
        import moto  # noqa: F401
    except ImportError:
        pytest.skip("moto not installed — skipping DynamoDB contract tests")

    try:
        import boto3
        from moto import mock_aws
        from parrot.storage.backends.dynamodb import ConversationDynamoDB

        # Start moto mock
        mock = mock_aws()
        mock.start()

        # Create fake tables
        client = boto3.client("dynamodb", region_name="us-east-1")
        for table_name in ("parrot-conversations", "parrot-artifacts"):
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
            conversations_table="parrot-conversations",
            artifacts_table="parrot-artifacts",
            dynamo_params={"region_name": "us-east-1"},
        )
        # Store mock handle so we can stop it later
        backend._moto_mock = mock
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
