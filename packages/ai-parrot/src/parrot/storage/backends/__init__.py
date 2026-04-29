"""Pluggable ConversationBackend factory and re-exports.

Use ``build_conversation_backend()`` to get the backend specified by
``PARROT_STORAGE_BACKEND``. See docs/storage-backends.md for the full
backend selection matrix and environment variable reference.

FEAT-116: dynamodb-fallback-redis — Module 7 (factory + config wiring).
"""

import importlib
import os
from pathlib import Path
from typing import Optional

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.backends.dynamodb import ConversationDynamoDB
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.backends.postgres import ConversationPostgresBackend
from parrot.storage.backends.mongodb import ConversationMongoBackend
from parrot.storage.overflow import OverflowStore
from parrot.storage.metrics import StorageMetrics  # noqa: F401 (re-export)


__all__ = [
    "ConversationBackend",
    "ConversationDynamoDB",
    "ConversationSQLiteBackend",
    "ConversationPostgresBackend",
    "ConversationMongoBackend",
    "OverflowStore",
    "build_conversation_backend",
    "build_overflow_store",
    "load_metrics_from_path",
]


def _resolve_dynamodb_credentials() -> Optional[dict]:
    """Resolve credentials for the DynamoDB backend.

    Resolution order:
      1. ``DYNAMODB_AWS_PROFILE`` — name of an entry in ``AWS_CREDENTIALS``.
      2. ``BACKEND_AWS_ACCESS_KEY`` + ``BACKEND_AWS_SECRET_KEY`` env vars.
      3. ``None`` — let aioboto3 use the default credential chain
         (IAM role, ``~/.aws/credentials``, etc.).

    The general ``AWS_ACCESS_KEY`` / ``AWS_SECRET_KEY`` are intentionally NOT
    consulted, so the conversation backend cannot clobber the credentials used
    by S3 and other services that share the default profile.

    Why: parrot.conf snapshots env vars at import time, and tests rely on
    monkeypatch.setenv — read directly from os.environ for that reason.

    Returns:
        Dict with ``aws_key``, ``aws_secret``, and optional ``region_name``,
        or ``None`` to defer to boto3's resolution chain.

    Raises:
        RuntimeError: If ``DYNAMODB_AWS_PROFILE`` references a missing or
            incomplete profile.
    """
    profile_name = os.environ.get("DYNAMODB_AWS_PROFILE")
    if profile_name:
        from parrot.conf import AWS_CREDENTIALS  # noqa: E501 pylint: disable=import-outside-toplevel
        profile = AWS_CREDENTIALS.get(profile_name)
        if not profile:
            raise RuntimeError(
                f"DYNAMODB_AWS_PROFILE={profile_name!r} not found in "
                "AWS_CREDENTIALS."
            )
        aws_key = profile.get("aws_key") or profile.get("aws_access_key_id")
        aws_secret = profile.get("aws_secret") or profile.get("aws_secret_access_key")
        if not (aws_key and aws_secret):
            raise RuntimeError(
                f"AWS_CREDENTIALS profile {profile_name!r} is missing "
                "aws_key/aws_secret."
            )
        return {
            "aws_key": aws_key,
            "aws_secret": aws_secret,
            "region_name": profile.get("region_name"),
        }

    backend_key = os.environ.get("BACKEND_AWS_ACCESS_KEY")
    backend_secret = os.environ.get("BACKEND_AWS_SECRET_KEY")
    if backend_key and backend_secret:
        return {
            "aws_key": backend_key,
            "aws_secret": backend_secret,
            "region_name": os.environ.get("BACKEND_AWS_REGION"),
        }

    return None


async def build_conversation_backend(
    override: Optional[str] = None,
) -> ConversationBackend:
    """Instantiate the backend specified by ``PARROT_STORAGE_BACKEND``.

    Imports from ``parrot.conf`` are deferred inside the function body to
    avoid circular import issues between ``conf.py`` ← ``storage`` ← ``backends``.

    Args:
        override: Override the env-var value for this call only (used in tests).

    Returns:
        An uninitialised ``ConversationBackend`` instance. Call
        ``await backend.initialize()`` before using it.

    Raises:
        ValueError: If the backend name is unknown.
        RuntimeError: If a required DSN is not configured.
    """
    from parrot.conf import (  # noqa: E501 pylint: disable=import-outside-toplevel
        DYNAMODB_CONVERSATIONS_TABLE,
        DYNAMODB_ARTIFACTS_TABLE,
        DYNAMODB_REGION,
        DYNAMODB_ENDPOINT_URL,
    )
    # Read runtime-configurable values from os.environ first so that
    # monkeypatch.setenv works in tests (conf.py caches at import time).
    PARROT_STORAGE_BACKEND = os.environ.get("PARROT_STORAGE_BACKEND", "sqlite")
    PARROT_SQLITE_PATH = os.environ.get("PARROT_SQLITE_PATH") or str(
        Path.home() / ".parrot" / "parrot.db"
    )
    PARROT_POSTGRES_DSN = os.environ.get("PARROT_POSTGRES_DSN")
    PARROT_MONGODB_DSN = os.environ.get("PARROT_MONGODB_DSN")
    PARROT_STORAGE_METRICS = os.environ.get("PARROT_STORAGE_METRICS") or None
    name = (override or PARROT_STORAGE_BACKEND or "sqlite").lower()

    if name == "sqlite":
        backend: ConversationBackend = ConversationSQLiteBackend(path=PARROT_SQLITE_PATH)
    elif name == "postgres":
        if not PARROT_POSTGRES_DSN:
            raise RuntimeError(
                "PARROT_POSTGRES_DSN is required for postgres backend"
            )
        backend = ConversationPostgresBackend(dsn=PARROT_POSTGRES_DSN)
    elif name == "mongodb":
        if not PARROT_MONGODB_DSN:
            raise RuntimeError(
                "PARROT_MONGODB_DSN is required for mongodb backend"
            )
        backend = ConversationMongoBackend(dsn=PARROT_MONGODB_DSN)
    elif name == "dynamodb":
        params = {"region_name": DYNAMODB_REGION}
        if DYNAMODB_ENDPOINT_URL:
            params["endpoint_url"] = DYNAMODB_ENDPOINT_URL
        creds = _resolve_dynamodb_credentials()
        if creds:
            params["aws_access_key_id"] = creds["aws_key"]
            params["aws_secret_access_key"] = creds["aws_secret"]
            if creds.get("region_name"):
                params["region_name"] = creds["region_name"]
        backend = ConversationDynamoDB(
            conversations_table=DYNAMODB_CONVERSATIONS_TABLE,
            artifacts_table=DYNAMODB_ARTIFACTS_TABLE,
            dynamo_params=params,
        )
    else:
        raise ValueError(
            f"Unknown PARROT_STORAGE_BACKEND={name!r}. "
            "Valid values: sqlite, postgres, mongodb, dynamodb."
        )

    # Optional observability wrapping
    if PARROT_STORAGE_METRICS:
        from parrot.storage.instrumented import InstrumentedBackend  # noqa: E501 pylint: disable=import-outside-toplevel
        metrics = load_metrics_from_path(PARROT_STORAGE_METRICS)
        backend = InstrumentedBackend(backend, metrics=metrics)

    return backend


def build_overflow_store(override: Optional[str] = None) -> OverflowStore:
    """Instantiate the overflow store specified by ``PARROT_OVERFLOW_STORE``.

    Defaults:
      - ``dynamodb`` backend → ``s3``
      - everything else → ``local`` (filesystem under ``PARROT_OVERFLOW_LOCAL_PATH``)

    Args:
        override: Override the env-var value for this call only.

    Returns:
        An ``OverflowStore`` wrapping the appropriate ``FileManagerInterface``.

    Raises:
        ValueError: If the overflow store name is unknown.
    """
    from parrot.interfaces.file.local import LocalFileManager  # noqa: E501 pylint: disable=import-outside-toplevel

    PARROT_STORAGE_BACKEND = os.environ.get("PARROT_STORAGE_BACKEND", "sqlite")
    PARROT_OVERFLOW_STORE = os.environ.get("PARROT_OVERFLOW_STORE") or None
    PARROT_OVERFLOW_LOCAL_PATH = os.environ.get("PARROT_OVERFLOW_LOCAL_PATH") or str(
        Path.home() / ".parrot" / "artifacts"
    )

    name = (override or PARROT_OVERFLOW_STORE or "").lower()
    if not name:
        name = "s3" if PARROT_STORAGE_BACKEND == "dynamodb" else "local"

    if name == "s3":
        from parrot.interfaces.file.s3 import S3FileManager  # noqa: E501 pylint: disable=import-outside-toplevel
        return OverflowStore(file_manager=S3FileManager())
    if name == "gcs":
        from parrot.interfaces.file.gcs import GCSFileManager  # noqa: E501 pylint: disable=import-outside-toplevel
        return OverflowStore(file_manager=GCSFileManager())
    if name == "local":
        return OverflowStore(file_manager=LocalFileManager(base_path=PARROT_OVERFLOW_LOCAL_PATH))
    if name == "tmp":
        from parrot.interfaces.file.tmp import TempFileManager  # noqa: E501 pylint: disable=import-outside-toplevel
        return OverflowStore(file_manager=TempFileManager())
    raise ValueError(
        f"Unknown PARROT_OVERFLOW_STORE={name!r}. "
        "Valid values: s3, gcs, local, tmp."
    )


def load_metrics_from_path(path: str) -> "StorageMetrics":
    """Import and return a ``StorageMetrics`` instance from a module path.

    Args:
        path: Module path in ``"module.name:attribute"`` format.

    Returns:
        The ``StorageMetrics`` instance at the given path.

    Raises:
        RuntimeError: If the path is malformed or the import fails.
    """
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise RuntimeError(
            f"Invalid PARROT_STORAGE_METRICS path: {path!r}. "
            "Expected format: 'mymodule:ATTRIBUTE'"
        )
    try:
        mod = importlib.import_module(module_name)
        return getattr(mod, attr)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to import metrics from {path!r}: {exc}"
        ) from exc
