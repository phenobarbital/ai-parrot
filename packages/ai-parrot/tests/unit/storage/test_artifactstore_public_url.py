"""Unit tests for ArtifactStore.get_public_url (FEAT-197, TASK-1321)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
import pytest
from unittest.mock import AsyncMock, MagicMock


# Force real storage modules (bypass conftest stubs).
for _mod in ("parrot.storage.artifacts", "parrot.storage.overflow", "parrot.storage.models"):
    sys.modules.pop(_mod, None)

import parrot.storage.models as _real_models
import parrot.storage.overflow as _real_overflow
import parrot.storage.artifacts as _real_artifacts

sys.modules["parrot.storage.models"] = _real_models
sys.modules["parrot.storage.overflow"] = _real_overflow
sys.modules["parrot.storage.artifacts"] = _real_artifacts

from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator  # noqa: E402
from parrot.storage.artifacts import ArtifactStore  # noqa: E402


_NOW = datetime.now(timezone.utc)


def _make_artifact(artifact_id: str, definition_ref: str | None = None) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        artifact_type=ArtifactType.INFOGRAPHIC,
        title="test",
        created_at=_NOW,
        updated_at=_NOW,
        created_by=ArtifactCreator.AGENT,
        definition={"html": "<html/>"},
        definition_ref=definition_ref,
    )


@pytest.fixture
def store_with_overflow_artifact():
    """ArtifactStore whose get_artifact returns an artifact with a definition_ref."""
    db = MagicMock()
    overflow = MagicMock()

    artifact = _make_artifact("art-1", definition_ref="artifacts/u/a/s/art-1.json")
    db.get_artifact = AsyncMock(return_value={
        "artifact_id": "art-1",
        "artifact_type": "infographic",
        "title": "test",
        "created_at": _NOW.isoformat(),
        "updated_at": _NOW.isoformat(),
        "created_by": "agent",
        "definition": None,  # offloaded
        "definition_ref": "artifacts/u/a/s/art-1.json",
    })
    overflow.resolve = AsyncMock(return_value={"html": "<html/>"})
    # Simulate a real presigned URL (no user_id in path/query)
    presigned = (
        "https://bucket.s3.amazonaws.com/artifacts/a/s/art-1.json"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        "&X-Amz-Credential=AKID%2F20260528%2Fus-east-1%2Fs3%2Faws4_request"
        "&X-Amz-Date=20260528T000000Z"
        "&X-Amz-Expires=604800"
        "&X-Amz-Signature=deadbeef123"
    )
    overflow.generate_presigned_url = AsyncMock(return_value=presigned)

    return ArtifactStore(dynamodb=db, s3_overflow=overflow), presigned


@pytest.fixture
def store_inline_artifact():
    """ArtifactStore whose artifact has no definition_ref (inline)."""
    db = MagicMock()
    overflow = MagicMock()

    db.get_artifact = AsyncMock(return_value={
        "artifact_id": "art-inline",
        "artifact_type": "infographic",
        "title": "test",
        "created_at": _NOW.isoformat(),
        "updated_at": _NOW.isoformat(),
        "created_by": "agent",
        "definition": {"html": "<html/>"},
        "definition_ref": None,
    })
    overflow.resolve = AsyncMock(return_value={"html": "<html/>"})

    return ArtifactStore(dynamodb=db, s3_overflow=overflow)


@pytest.fixture
def store_missing_artifact():
    """ArtifactStore whose artifact does not exist."""
    db = MagicMock()
    overflow = MagicMock()

    db.get_artifact = AsyncMock(return_value=None)
    overflow.resolve = AsyncMock(return_value=None)

    return ArtifactStore(dynamodb=db, s3_overflow=overflow)


@pytest.mark.asyncio
async def test_public_url_returns_string(store_with_overflow_artifact):
    """get_public_url should return a non-empty string."""
    store, _ = store_with_overflow_artifact
    url = await store.get_public_url(
        user_id="alice", agent_id="agt", session_id="sess",
        artifact_id="art-1", format="html",
    )
    assert isinstance(url, str)
    assert url.startswith("https://")


@pytest.mark.asyncio
async def test_public_url_no_user_id_in_path_or_query(store_with_overflow_artifact):
    """The presigned URL must not embed the user_id."""
    store, _ = store_with_overflow_artifact
    url = await store.get_public_url(
        user_id="alice", agent_id="agt", session_id="sess",
        artifact_id="art-1",
    )
    parsed = urlparse(url)
    assert "alice" not in parsed.path
    assert "alice" not in parsed.query


@pytest.mark.asyncio
async def test_public_url_has_sigv4_params(store_with_overflow_artifact):
    """URL should contain X-Amz-Signature and X-Amz-Expires."""
    store, _ = store_with_overflow_artifact
    url = await store.get_public_url(
        user_id="alice", agent_id="agt", session_id="sess",
        artifact_id="art-1",
    )
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert "X-Amz-Signature" in q
    assert "X-Amz-Expires" in q
    assert int(q["X-Amz-Expires"][0]) <= 604_800


@pytest.mark.asyncio
async def test_public_url_missing_artifact_raises(store_missing_artifact):
    """Should raise KeyError when the artifact does not exist."""
    with pytest.raises(KeyError):
        await store_missing_artifact.get_public_url(
            user_id="u", agent_id="a", session_id="s",
            artifact_id="does-not-exist",
        )


@pytest.mark.asyncio
async def test_public_url_inline_artifact_raises(store_inline_artifact):
    """Should raise ValueError when the artifact is stored inline (no S3 ref)."""
    with pytest.raises(ValueError, match="no overflow reference"):
        await store_inline_artifact.get_public_url(
            user_id="u", agent_id="a", session_id="s",
            artifact_id="art-inline",
        )
