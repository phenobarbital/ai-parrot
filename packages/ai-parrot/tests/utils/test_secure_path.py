"""Tests for :mod:`parrot.utils.paths` (path-traversal guards)."""
import os
from pathlib import Path

import pytest

from parrot.utils.paths import secure_path, validate_path_segment


def test_valid_segment_is_returned_unchanged():
    assert validate_path_segment("agent-01_x.v2") == "agent-01_x.v2"


@pytest.mark.parametrize(
    "value",
    [
        "..",
        "../etc",
        "a/b",
        "a\\b",
        "/etc/passwd",
        ".hidden",
        "-leading-dash",
        "",
        None,
        123,
    ],
)
def test_unsafe_segments_are_rejected(value):
    with pytest.raises(ValueError):
        validate_path_segment(value, name="agent_id")


def test_secure_path_joins_under_base(tmp_path: Path):
    result = secure_path(tmp_path, "agent-123", "documents")
    assert result == (tmp_path.resolve() / "agent-123" / "documents")


def test_secure_path_result_stays_inside_base(tmp_path: Path):
    result = secure_path(tmp_path, "agent-123", "documents")
    assert str(result).startswith(str(tmp_path.resolve()) + os.sep)


def test_secure_path_with_no_segments_returns_base(tmp_path: Path):
    assert secure_path(tmp_path) == tmp_path.resolve()


@pytest.mark.parametrize(
    "segment",
    ["../../etc", "/etc/passwd", "..", "sub/dir"],
)
def test_secure_path_rejects_traversal(tmp_path: Path, segment):
    with pytest.raises(ValueError):
        secure_path(tmp_path, segment, "documents", name="agent_id")


def test_error_message_names_the_offending_value(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsafe agent_id"):
        secure_path(tmp_path, "../evil", name="agent_id")


def test_secure_path_rejects_symlink_escaping_base(tmp_path: Path):
    base = tmp_path / "static"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (base / "agent-1").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="resolves outside"):
        secure_path(base, "agent-1", "documents", name="agent_id")


def test_secure_path_allows_symlink_staying_inside_base(tmp_path: Path):
    base = tmp_path / "static"
    (base / "real").mkdir(parents=True)
    (base / "agent-1").symlink_to(base / "real", target_is_directory=True)

    result = secure_path(base, "agent-1", "documents", name="agent_id")

    # The symlink is followed, so the result is the canonical location.
    assert result == base.resolve() / "real" / "documents"


@pytest.mark.parametrize("value", ["agent-1\n", "agent-1\r", "agent-1\n../etc"])
def test_trailing_newline_does_not_bypass_validation(value):
    """``$`` also matches before a trailing newline — hence ``fullmatch``."""
    with pytest.raises(ValueError):
        validate_path_segment(value, name="agent_id")


def test_secure_path_returns_a_resolved_path(tmp_path: Path):
    """The result is canonical, as the ``.resolve()``-based code it replaced was."""
    result = secure_path(tmp_path, "agent-1", "documents")
    assert result.is_absolute()
    assert result == result.resolve()
