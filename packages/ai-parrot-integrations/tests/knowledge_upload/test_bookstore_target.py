"""Tests for the Bookstore knowledge-upload target."""

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.knowledge_upload import (
    BookstoreTargetConfig,
    UploaderIdentity,
    UploadRequest,
    UploadStatus,
    UploadTargetKind,
)
from parrot.integrations.knowledge_upload.targets.bookstore import BookstoreTarget


try:
    import parrot.utils.types  # noqa: F401 - prefer the compiled extension when available
except ModuleNotFoundError:
    utils_types = ModuleType("parrot.utils.types")
    utils_types.SafeDict = dict
    sys.modules["parrot.utils.types"] = utils_types


try:
    import parrot.utils.parsers.toml  # noqa: F401 - prefer the compiled extension when available
except ModuleNotFoundError:

    class TOMLParser:
        """Minimal parser placeholder for imports in an unbuilt Cython worktree."""

        async def parse(self, filename: str) -> dict[str, object]:
            """Reject parsing because this target test never reads TOML."""
            raise RuntimeError(f"TOML parsing is unavailable for {filename}")

    parsers_toml = ModuleType("parrot.utils.parsers.toml")
    parsers_toml.TOMLParser = TOMLParser
    sys.modules["parrot.utils.parsers.toml"] = parsers_toml


def _request(**kwargs: object) -> UploadRequest:
    """Build a conventional Bookstore upload request."""
    return UploadRequest(
        target=UploadTargetKind.BOOKSTORE,
        filename="doc.md",
        data=b"# T\n\nA sufficiently detailed markdown document for ingestion.",
        identity=UploaderIdentity(platform="telegram", platform_user_id="1"),
        **kwargs,
    )


async def test_available_builds_and_caches_bookstore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Availability creates one Bookstore with the resolved adapter."""
    adapter = object()
    bookstore_class = MagicMock()
    monkeypatch.setattr(
        "parrot.knowledge.bookstore._llm.resolve_adapter",
        lambda *args, **kwargs: (adapter, "light-model", None),
    )
    monkeypatch.setattr("parrot.knowledge.bookstore.library.Bookstore", bookstore_class)

    target = BookstoreTarget(BookstoreTargetConfig(library_dir=str(tmp_path)))
    available, reason = await target.available()

    assert available
    assert reason == ""
    assert target._bookstore is bookstore_class.return_value
    bookstore_class.assert_called_once()
    assert bookstore_class.call_args.kwargs == {
        "adapter": adapter,
        "lightweight_model": "light-model",
    }


async def test_available_without_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Availability rejects a Bookstore target without an LLM adapter."""
    monkeypatch.setattr(
        "parrot.knowledge.bookstore._llm.resolve_adapter",
        lambda *args, **kwargs: (None, None, None),
    )

    available, reason = await BookstoreTarget(BookstoreTargetConfig(library_dir=str(tmp_path))).available()

    assert not available
    assert reason == "no LLM for google:gemini-3.1-flash-lite"


@pytest.mark.parametrize(
    ("status", "expected"),
    [("added", UploadStatus.ADDED), ("updated", UploadStatus.UPDATED), ("skipped", UploadStatus.SKIPPED)],
)
async def test_status_mapping(tmp_path: Path, status: str, expected: UploadStatus) -> None:
    """Bookstore statuses map to their corresponding upload outcomes."""
    target = BookstoreTarget(BookstoreTargetConfig(library_dir=str(tmp_path)))
    card = MagicMock(book_id="b1", title="T")
    target._bookstore = MagicMock(add_book=AsyncMock(return_value=(card, status)))

    outcome = await target.ingest(tmp_path / "doc.md", _request(), "job1")

    assert outcome.status == expected
    assert outcome.detail == {"book_id": "b1", "title": "T"}
    kwargs = target._bookstore.add_book.call_args.kwargs
    assert kwargs["authors"] is None
    assert kwargs["topics"] is None
    assert kwargs["title"] is None
    assert kwargs["force"] is False


async def test_bookstore_error_is_a_path_safe_failed_outcome(tmp_path: Path) -> None:
    """Bookstore errors become failed outcomes without exposing an absolute path."""
    from parrot.knowledge.bookstore.library import BookstoreError

    target = BookstoreTarget(BookstoreTargetConfig(library_dir=str(tmp_path)))
    staged = target.staging_dir / "doc.md"
    target._bookstore = MagicMock(add_book=AsyncMock(side_effect=BookstoreError(f"File not found: {staged}")))

    outcome = await target.ingest(staged, _request(), "job1")

    assert outcome.status == UploadStatus.FAILED
    assert str(tmp_path) not in outcome.message
    assert outcome.message == "File not found: doc.md"


async def test_same_name_updates_real_bookstore(tmp_path: Path) -> None:
    """A real markdown Bookstore upload skips duplicates and updates same-name changes."""
    from parrot.knowledge.bookstore.config import LibraryLocation
    from parrot.knowledge.bookstore.library import Bookstore

    target = BookstoreTarget(BookstoreTargetConfig(library_dir=str(tmp_path / "library")))
    target._bookstore = Bookstore([LibraryLocation(scope="project", root=target.library_dir)], adapter=None)
    staged = target.staging_dir / "doc.md"
    staged.parent.mkdir(parents=True)
    staged.write_text(
        "# Initial Handbook\n\n"
        "This markdown section has enough detailed prose to survive the parser thinning threshold and create a real "
        "Bookstore tree with durable content for the integration assertion.\n",
        encoding="utf-8",
    )

    added = await target.ingest(staged, _request(), "job-added")
    skipped = await target.ingest(staged, _request(), "job-skipped")
    staged.write_text(
        "# Revised Handbook\n\n"
        "This revised markdown section also contains enough detailed prose to survive parser thinning and produce a "
        "different content hash while keeping the same stable staging identity.\n",
        encoding="utf-8",
    )
    updated = await target.ingest(staged, _request(), "job-updated")

    assert added.status == UploadStatus.ADDED
    assert skipped.status == UploadStatus.SKIPPED
    assert updated.status == UploadStatus.UPDATED
    assert updated.detail["book_id"] == added.detail["book_id"]
