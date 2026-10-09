"""Unit tests for private knowledge upload staging."""

import asyncio
import stat

import pytest

from parrot.integrations.knowledge_upload.staging import safe_filename, staged_file, sweep_staging


def test_safe_filename_traversal_and_empty_values() -> None:
    """Filenames retain only a portable basename."""
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\docs\\manual.pdf") == "manual.pdf"
    with pytest.raises(ValueError):
        safe_filename("../")


async def test_staged_file_deleted_on_success_error_and_cancellation(tmp_path) -> None:
    """A staging file is removed for each context-manager exit path."""
    directory = tmp_path / "up"
    async with staged_file(directory, "a.md", b"# hi") as path:
        assert path.read_bytes() == b"# hi"
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert not path.exists()

    with pytest.raises(RuntimeError):
        async with staged_file(directory, "error.md", b"# hi") as error_path:
            raise RuntimeError("ingest failed")
    assert not error_path.exists()

    cancelled_path = None
    entered_context = asyncio.Event()

    async def hold_staged_file() -> None:
        nonlocal cancelled_path
        async with staged_file(directory, "cancel.md", b"# hi") as cancelled_path:
            entered_context.set()
            await asyncio.Event().wait()

    cancellation_task = asyncio.create_task(hold_staged_file())
    await entered_context.wait()
    cancellation_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancellation_task
    assert cancelled_path is not None
    assert not cancelled_path.exists()


def test_sweep_staging_removes_files_only(tmp_path) -> None:
    """Sweeping removes leftovers without recursing into child directories."""
    (tmp_path / "x.pdf").write_bytes(b"x")
    (tmp_path / "child").mkdir()
    (tmp_path / "child" / "nested.pdf").write_bytes(b"x")

    assert sweep_staging(tmp_path) == 1
    assert (tmp_path / "child" / "nested.pdf").exists()
    assert sweep_staging(tmp_path / "missing") == 0
