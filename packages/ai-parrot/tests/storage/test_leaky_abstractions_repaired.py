"""Regression tests verifying leaky abstractions are repaired.

TASK-825: ChatStorage and ArtifactStore consume the ABC — FEAT-116.
"""
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.overflow import OverflowStore
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator


STORAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "parrot" / "storage"


def test_artifacts_py_has_no_build_pk_reference():
    """artifacts.py must not reference _build_pk anywhere."""
    src = (STORAGE_DIR / "artifacts.py").read_text()
    assert "_build_pk" not in src


def test_chat_py_has_no_botocore_import():
    """chat.py must not have any inline botocore imports."""
    src = (STORAGE_DIR / "chat.py").read_text()
    assert "from botocore" not in src
    assert "import botocore" not in src


class _StubBackend(ConversationBackend):
    async def initialize(self): ...
    async def close(self): ...

    @property
    def is_connected(self):
        return True

    async def put_thread(self, *a, **kw): ...
    async def update_thread(self, *a, **kw): ...
    async def query_threads(self, *a, **kw): return []
    async def put_turn(self, *a, **kw): ...
    async def query_turns(self, *a, **kw): return []
    async def delete_turn(self, *a, **kw): return True
    async def delete_thread_cascade(self, *a, **kw): return 0
    async def put_artifact(self, *a, **kw): ...
    async def get_artifact(self, *a, **kw): return None
    async def query_artifacts(self, *a, **kw): return []
    async def delete_artifact(self, *a, **kw): ...
    async def delete_session_artifacts(self, *a, **kw): return 0


def test_artifact_store_accepts_conversation_backend():
    """ArtifactStore.__init__ accepts any ConversationBackend subclass."""
    backend = _StubBackend()
    overflow = MagicMock(spec=OverflowStore)
    store = ArtifactStore(dynamodb=backend, s3_overflow=overflow)
    assert store._db is backend


async def test_artifact_store_uses_backend_overflow_prefix():
    """save_artifact calls backend.build_overflow_prefix (not _build_pk)."""
    backend = _StubBackend()
    backend.put_artifact = AsyncMock()
    backend.build_overflow_prefix = MagicMock(
        return_value="artifacts/USER#u#AGENT#a/THREAD#s/a1"
    )

    overflow = MagicMock(spec=OverflowStore)
    overflow.maybe_offload = AsyncMock(return_value=({"k": "v"}, None))

    store = ArtifactStore(dynamodb=backend, s3_overflow=overflow)
    artifact = Artifact(
        artifact_id="a1",
        artifact_type=ArtifactType.CHART,
        title="t",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        created_by=ArtifactCreator.USER,
        definition={"k": "v"},
    )
    await store.save_artifact("u", "a", "s", artifact)

    backend.build_overflow_prefix.assert_called_once_with("u", "a", "s", "a1")
    overflow.maybe_offload.assert_awaited_once_with(
        {"k": "v"}, "artifacts/USER#u#AGENT#a/THREAD#s/a1"
    )


async def test_chat_storage_delete_turn_uses_backend():
    """ChatStorage.delete_turn calls backend.delete_turn (not _conv_table)."""
    from parrot.storage.chat import ChatStorage

    backend = _StubBackend()
    backend.delete_turn = AsyncMock(return_value=True)
    backend.update_thread = AsyncMock()

    storage = ChatStorage(dynamodb=backend)
    result = await storage.delete_turn(
        session_id="s", turn_id="t1", user_id="u", agent_id="a"
    )
    assert result is True
    backend.delete_turn.assert_awaited_once_with("u", "a", "s", "t1")
