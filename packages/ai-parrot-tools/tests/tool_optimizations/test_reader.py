"""Unit tests for BoundedSourceToolkit (TASK-3082, FEAT-543)."""

import json
import os
import tracemalloc
from pathlib import Path

import pytest

from parrot_tools.tool_optimizations.models import SourceInfo, SourceResult
from parrot_tools.tool_optimizations.policy import measure_json_bytes
from parrot_tools.tool_optimizations.reader import (
    BoundedSourceToolkit,
    LineTooLargeError,
    RangeOutOfBoundsError,
    count_lines_bounded,
    read_line_range,
    sha256_stream,
    stat_regular,
)


def _lines(tmp_path: Path, n: int, width: int = 10, name: str = "f.py", eol: str = "\n") -> Path:
    """Write a file of ``n`` deterministic lines and return its path."""
    target = tmp_path / name
    body = eol.join(f"l{i:0{width}d}" for i in range(1, n + 1)) + eol
    target.write_bytes(body.encode())
    return target


# --------------------------------------------------------------------------- #
# Thresholds — strict '>' on both axes, tested independently
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("n,large", [(349, False), (350, False), (351, True)])
async def test_line_threshold(tmp_path, n, large):
    """351 lines is large; 350 is not. The byte axis is held out of the way."""
    _lines(tmp_path, n)
    info = await BoundedSourceToolkit(repo_root=tmp_path, large_file_bytes=10**9).source_info("f.py")
    assert isinstance(info, SourceInfo)
    assert info.is_large is large
    assert info.range_required is large
    assert info.line_count == (None if large else n)


@pytest.mark.parametrize("size,large", [(63_999, False), (64_000, False), (64_001, True)])
async def test_byte_threshold(tmp_path, size, large):
    """64,001 bytes is large; 64,000 is not. The line axis is held out of the way."""
    (tmp_path / "f.py").write_bytes(b"x" * size)
    info = await BoundedSourceToolkit(repo_root=tmp_path, max_lines=10**9).source_info("f.py")
    assert info.is_large is large
    assert info.size_bytes == size


async def test_source_info_never_returns_content(tmp_path):
    """source_info reports metadata and a revision, never file text."""
    path = _lines(tmp_path, 5)
    info = await BoundedSourceToolkit(repo_root=tmp_path).source_info("f.py")
    assert not hasattr(info, "content")
    assert info.sha256 == sha256_stream(path, deadline_seconds=10)
    assert info.path == "f.py"


# --------------------------------------------------------------------------- #
# Range requirement and continuation
# --------------------------------------------------------------------------- #
async def test_large_requires_range_without_content(tmp_path):
    """A large file yields an actionable refusal carrying no source text."""
    _lines(tmp_path, 1000)
    res = await BoundedSourceToolkit(repo_root=tmp_path).source_read("f.py")
    assert res.status == "error"
    assert res.error.code == "range_required"
    assert "content" not in res.data
    assert res.error.details["example"] == {"start_line": 1, "end_line": 350}

    ok = await BoundedSourceToolkit(repo_root=tmp_path).source_read("f.py", 1, 350)
    assert isinstance(ok, SourceResult)
    assert ok.next_line == 351
    assert ok.content.count("\n") == 350
    assert ok.eof is False
    assert ok.truncated is False


async def test_range_too_large(tmp_path):
    """A span wider than max_lines is refused before any read."""
    _lines(tmp_path, 1000)
    res = await BoundedSourceToolkit(repo_root=tmp_path).source_read("f.py", 1, 351)
    assert res.status == "error"
    assert res.error.code == "range_too_large"


async def test_end_beyond_eof_clamps_and_start_beyond_eof_errors(tmp_path):
    """An end past EOF clamps; a start past EOF is out of bounds."""
    _lines(tmp_path, 10)
    toolkit = BoundedSourceToolkit(repo_root=tmp_path)

    clamped = await toolkit.source_read("f.py", 5, 300)
    assert clamped.end_line == 10
    assert clamped.eof is True
    assert clamped.next_line is None

    out = await toolkit.source_read("f.py", 50, 60)
    assert out.status == "error"
    assert out.error.code == "range_out_of_bounds"
    assert out.error.details["total_lines"] == 10


async def test_continuation_walks_the_whole_file(tmp_path):
    """next_line + expected_sha256 pages through a file with no gaps."""
    _lines(tmp_path, 900)
    toolkit = BoundedSourceToolkit(repo_root=tmp_path)
    info = await toolkit.source_info("f.py")

    collected = ""
    cursor = 1
    while cursor is not None:
        chunk = await toolkit.source_read("f.py", cursor, min(cursor + 349, 900), expected_sha256=info.sha256)
        assert isinstance(chunk, SourceResult)
        collected += chunk.content
        cursor = chunk.next_line
    assert collected == (tmp_path / "f.py").read_bytes().decode()


# --------------------------------------------------------------------------- #
# Byte budget
# --------------------------------------------------------------------------- #
async def test_budget_returns_complete_lines_only(tmp_path):
    """The budget truncates by whole lines and reports where to resume."""
    _lines(tmp_path, 100, width=100)
    res = await BoundedSourceToolkit(repo_root=tmp_path, max_result_bytes=4096).source_read("f.py", 1, 100)
    assert res.truncated is True
    assert res.next_line == res.end_line + 1
    assert res.content.endswith("\n")
    assert res.end_line < 100
    assert measure_json_bytes(res.model_dump(mode="json")) <= 4096


async def test_single_long_line_is_reported_not_cut(tmp_path):
    """An oversized line is reported by number and size, never partially returned."""
    (tmp_path / "f.py").write_bytes(b"y" * 5000 + b"\n")
    res = await BoundedSourceToolkit(repo_root=tmp_path, max_result_bytes=4096).source_read("f.py")
    assert res.status == "error"
    assert res.error.code == "line_too_large"
    assert res.error.details["line"] == 1
    # `bytes` is a *lower bound*: the reader stops at max_line_bytes + 1 and
    # deliberately never reads the rest of the line, so memory stays bounded.
    assert res.error.details["bytes"] > 4096


# --------------------------------------------------------------------------- #
# Encoding and byte fidelity
# --------------------------------------------------------------------------- #
async def test_crlf_and_no_final_newline_roundtrip(tmp_path):
    """CRLF and a missing final newline survive byte-exactly."""
    raw = b"a\r\nb\r\nc"
    (tmp_path / "f.py").write_bytes(raw)
    res = await BoundedSourceToolkit(repo_root=tmp_path).source_read("f.py")
    assert res.content.encode() == raw
    assert res.eof is True
    assert res.next_line is None
    assert res.end_line == 3


async def test_empty_file(tmp_path):
    """An empty file reads as empty content at EOF, not as an error."""
    (tmp_path / "f.py").write_bytes(b"")
    res = await BoundedSourceToolkit(repo_root=tmp_path).source_read("f.py")
    assert res.content == ""
    assert res.start_line == 1
    assert res.end_line == 0
    assert res.eof is True
    assert res.next_line is None


async def test_binary_and_invalid_utf8(tmp_path):
    """A NUL byte is binary; invalid UTF-8 without NUL is an encoding error."""
    (tmp_path / "b.bin").write_bytes(b"ok\x00then")
    binary = await BoundedSourceToolkit(repo_root=tmp_path).source_read("b.bin")
    assert binary.error.code == "binary_file"

    (tmp_path / "bad.py").write_bytes(b"fine\n\xff\xfe not utf8\n")
    invalid = await BoundedSourceToolkit(repo_root=tmp_path).source_read("bad.py")
    assert invalid.error.code == "invalid_encoding"
    assert invalid.error.details["line"] == 2


async def test_unicode_content_is_measured_in_bytes(tmp_path):
    """Multibyte content is charged its real UTF-8 cost, not its length."""
    (tmp_path / "u.py").write_bytes(("ñ" * 50 + "\n").encode() * 20)
    res = await BoundedSourceToolkit(repo_root=tmp_path, max_result_bytes=4096).source_read("u.py")
    assert measure_json_bytes(res.model_dump(mode="json")) <= 4096
    assert res.content.startswith("ñ")


# --------------------------------------------------------------------------- #
# Revision safety
# --------------------------------------------------------------------------- #
async def test_stale_hash_rejected(tmp_path):
    """A continuation against an outdated revision is refused."""
    _lines(tmp_path, 10)
    res = await BoundedSourceToolkit(repo_root=tmp_path).source_read("f.py", 1, 5, expected_sha256="0" * 64)
    assert res.status == "error"
    assert res.error.code == "stale_revision"
    assert len(res.error.details["current_sha256"]) == 64


async def test_concurrent_modification_detected(tmp_path, monkeypatch):
    """A file changed mid-scan is reported instead of returning mixed content."""
    path = _lines(tmp_path, 10)
    toolkit = BoundedSourceToolkit(repo_root=tmp_path)

    import parrot_tools.tool_optimizations.reader as reader_module

    real_read_line_range = reader_module.read_line_range

    def _mutating_read(*args, **kwargs):
        result = real_read_line_range(*args, **kwargs)
        path.write_bytes(b"totally different content\n")
        return result

    monkeypatch.setattr(reader_module, "read_line_range", _mutating_read)
    res = await toolkit.source_read("f.py", 1, 5)
    assert res.status == "error"
    assert res.error.code == "concurrent_modification"


# --------------------------------------------------------------------------- #
# Path policy
# --------------------------------------------------------------------------- #
async def test_path_policy_codes(tmp_path):
    """Each rejected path shape maps to its own stable error code."""
    _lines(tmp_path, 3, name="real.py")
    (tmp_path / "link.py").symlink_to(tmp_path / "real.py")
    (tmp_path / ".env").write_text("SECRET=1\n")
    (tmp_path / ".env.example").write_text("SECRET=\n")
    (tmp_path / "sub").mkdir()
    os.mkfifo(tmp_path / "pipe")

    toolkit = BoundedSourceToolkit(repo_root=tmp_path)
    assert (await toolkit.source_read("link.py")).error.code == "symlink_rejected"
    assert (await toolkit.source_read(".env")).error.code == "secret_file"
    assert (await toolkit.source_read("../escape.py")).error.code == "path_outside_root"
    assert (await toolkit.source_read("sub")).error.code == "not_a_file"
    assert (await toolkit.source_read("pipe")).error.code == "not_a_file"
    assert (await toolkit.source_read("missing.py")).error.code == "not_found"

    allowed = await toolkit.source_read(".env.example")
    assert isinstance(allowed, SourceResult)
    assert allowed.content == "SECRET=\n"


async def test_invalid_arguments_rejected(tmp_path):
    """One range end alone, or an inverted range, is refused."""
    _lines(tmp_path, 10)
    toolkit = BoundedSourceToolkit(repo_root=tmp_path)
    assert (await toolkit.source_read("f.py", 5)).error.code == "invalid_arguments"
    assert (await toolkit.source_read("f.py", 9, 2)).error.code == "invalid_arguments"

    with pytest.raises(ValueError, match="invalid arguments"):
        await toolkit._pre_execute("source_read", path="f.py", start_line=5)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload,stop,expected",
    [
        (b"", 10, (0, False)),
        (b"a\n", 10, (1, False)),
        (b"a", 10, (1, False)),
        (b"a\nb\nc", 10, (3, False)),
        (b"a\nb\nc\n", 2, (3, True)),
    ],
)
def test_count_lines_bounded(tmp_path, payload, stop, expected):
    """Counting handles a missing final newline and exits early past the bound."""
    target = tmp_path / "c.txt"
    target.write_bytes(payload)
    assert count_lines_bounded(target, stop) == expected


def test_read_line_range_bounds_and_errors(tmp_path):
    """The pure range reader clamps, detects EOF and refuses an impossible start."""
    target = _lines(tmp_path, 10)
    span = read_line_range(target, 3, 5, max_line_bytes=4096)
    assert len(span.lines) == 3
    assert span.actual_end == 5
    assert span.eof is False

    tail = read_line_range(target, 9, 20, max_line_bytes=4096)
    assert tail.actual_end == 10
    assert tail.eof is True

    with pytest.raises(RangeOutOfBoundsError):
        read_line_range(target, 50, 60, max_line_bytes=4096)


def test_bounded_allocation_on_huge_single_line(tmp_path):
    """A 200 MiB single line fails by size without being loaded into memory."""
    target = tmp_path / "huge.py"
    with open(target, "wb") as handle:
        for _ in range(200):
            handle.write(b"z" * (1 << 20))

    tracemalloc.start()
    try:
        with pytest.raises(LineTooLargeError):
            read_line_range(target, 1, 1, max_line_bytes=64_000)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * (1 << 20), f"peak allocation {peak} bytes is not bounded"


def test_stat_regular_rejects_non_files(tmp_path):
    """Symlinks and non-regular files are rejected at the stat boundary."""
    (tmp_path / "real.py").write_text("x\n")
    (tmp_path / "link.py").symlink_to(tmp_path / "real.py")
    assert stat_regular(tmp_path / "real.py").size == 2
    with pytest.raises(Exception):
        stat_regular(tmp_path / "link.py")


def test_no_whole_file_reads_in_source():
    """The module must never read an entire file into memory."""
    import inspect

    import parrot_tools.tool_optimizations.reader as module

    src = inspect.getsource(module)
    assert "read_text(" not in src
    assert ".read()" not in src
    assert "readlines(" not in src
