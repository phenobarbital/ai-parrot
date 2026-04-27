"""Unit tests for scripts/recompute_contextual_embeddings.py (FEAT-127 TASK-868).

Drives the run() coroutine against a fully mocked store and session.
No real Postgres or embedding model required.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Ensure the scripts package/directory is importable
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = str(
    Path(__file__).resolve().parents[3] / "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_mod():
    """Import (or reimport) the migration script module."""
    mod_name = "recompute_contextual_embeddings"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return importlib.import_module(mod_name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def args():
    return SimpleNamespace(
        dsn="postgresql://x",
        table="t",
        schema="public",
        embedding_model=None,
        template=None,
        max_header_tokens=100,
        batch_size=2,
        limit=None,
        dry_run=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _build_fake_store(rows_first_call: list) -> tuple:
    """Build a (fake_store, fake_session) pair for testing.

    The session returns *rows_first_call* on the first execute, then empty.
    """
    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    call_count_box = [0]

    async def _execute(_stmt):
        call_count_box[0] += 1
        result = MagicMock()
        if call_count_box[0] == 1:
            result.scalars.return_value.all.return_value = rows_first_call
        else:
            result.scalars.return_value.all.return_value = []
        return result

    fake_session.execute = _execute
    fake_session._call_count = call_count_box  # expose for assertions

    fake_store = MagicMock()
    fake_store.connection = AsyncMock()
    fake_store.session = MagicMock(return_value=fake_session)
    fake_store._embed_ = MagicMock()
    fake_store._embed_.embed_documents = AsyncMock(return_value=[np.zeros(4)])
    fake_store.embedding_store = MagicMock()
    fake_store._id_column = "id"
    fake_store.dimension = 4
    fake_store._define_collection_store = MagicMock(return_value=fake_store.embedding_store)
    return fake_store, fake_session


@pytest.mark.asyncio
async def test_run_updates_rows_with_meta(args):
    """Rows with document_meta get re-embedded; rows without are skipped."""
    mod = _import_mod()

    rows = [
        SimpleNamespace(
            id="1",
            document="Body 1",
            cmetadata={"document_meta": {"title": "T1"}},
            embedding=[0.0] * 4,
        ),
        SimpleNamespace(
            id="2",
            document="Body 2",
            cmetadata={},  # no document_meta → skipped
            embedding=[0.0] * 4,
        ),
    ]
    fake_store, _ = _build_fake_store(rows)

    with patch.object(mod, "PgVectorStore", return_value=fake_store), \
         patch.object(mod, "select", return_value=MagicMock()), \
         patch.object(mod, "update", return_value=MagicMock()):
        await mod.run(args)

    # Row 1 has document_meta → embed_documents called once.
    # Row 2 has no document_meta → skipped.
    assert fake_store._embed_.embed_documents.await_count == 1


@pytest.mark.asyncio
async def test_dry_run_does_not_update(args):
    """In dry-run mode, embed_documents is called but no real UPDATEs are issued."""
    mod = _import_mod()
    args.dry_run = True

    rows = [
        SimpleNamespace(
            id="1",
            document="Body",
            cmetadata={"document_meta": {"title": "T"}},
            embedding=[0.0] * 4,
        ),
    ]
    fake_store, fake_session = _build_fake_store(rows)

    update_mock = MagicMock(return_value=MagicMock())

    with patch.object(mod, "PgVectorStore", return_value=fake_store), \
         patch.object(mod, "select", return_value=MagicMock()), \
         patch.object(mod, "update", update_mock):
        await mod.run(args)

    # embed_documents WAS called (dry-run still validates).
    assert fake_store._embed_.embed_documents.await_count == 1
    # update() should NOT have been called (dry-run).
    update_mock.assert_not_called()


@pytest.mark.asyncio
async def test_limit_stops_early(args):
    """--limit stops after processing at most N rows."""
    mod = _import_mod()
    args.limit = 1
    args.batch_size = 10

    rows = [
        SimpleNamespace(id=str(i), document=f"Body {i}",
                        cmetadata={"document_meta": {"title": f"T{i}"}},
                        embedding=[0.0] * 4)
        for i in range(5)
    ]
    fake_store, _ = _build_fake_store(rows)

    with patch.object(mod, "PgVectorStore", return_value=fake_store), \
         patch.object(mod, "select", return_value=MagicMock()), \
         patch.object(mod, "update", return_value=MagicMock()):
        await mod.run(args)

    # limit=1: only the first row is processed.
    assert fake_store._embed_.embed_documents.await_count == 1
