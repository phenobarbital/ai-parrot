"""Tests for parrot.utils.tty.restore_stdin_blocking."""

import io
import os
import sys

import pytest

from parrot.utils.tty import restore_stdin_blocking


@pytest.fixture
def pipe_stdin(monkeypatch):
    """Replace sys.stdin with the read end of a real pipe."""
    read_fd, write_fd = os.pipe()
    stdin = os.fdopen(read_fd, "r")
    monkeypatch.setattr(sys, "stdin", stdin)
    yield stdin
    stdin.close()
    os.close(write_fd)


def test_restores_blocking_after_prompt_leaves_fd_non_blocking(pipe_stdin):
    """A prompt that flips fd 0 to O_NONBLOCK is undone on exit."""
    with restore_stdin_blocking():
        os.set_blocking(pipe_stdin.fileno(), False)
    assert os.get_blocking(pipe_stdin.fileno())


def test_restores_blocking_when_prompt_raises(pipe_stdin):
    """The restore also runs when the prompt raises (e.g. Ctrl-C)."""
    with pytest.raises(KeyboardInterrupt):
        with restore_stdin_blocking():
            os.set_blocking(pipe_stdin.fileno(), False)
            raise KeyboardInterrupt
    assert os.get_blocking(pipe_stdin.fileno())


def test_tolerates_stdin_without_fileno(monkeypatch):
    """A non-file stdin (pytest capture, StringIO) is ignored, not an error."""
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    with restore_stdin_blocking():
        pass
