"""Shared fixtures for the repl_worker test suite."""
import shutil
import uuid
from pathlib import Path
from typing import Iterator

import pytest

from parrot.conf import STATIC_DIR


@pytest.fixture
def repl_output_dir() -> Iterator[Path]:
    """Yield a fresh, per-test output directory under ``STATIC_DIR``.

    Two path-traversal guards reject pytest's ``tmp_path`` (under ``/tmp``):
    ``AbstractTool.__init__`` accepts only ``STATIC_DIR`` or ``OUTPUT_DIR``, and
    ``PythonREPL._setup_environment`` accepts only ``STATIC_DIR``. With
    ``tmp_path`` the worker namespace raises and real worker subprocesses die at
    bootstrap. The worker subprocess resolves the same ``STATIC_DIR``, so a
    directory created here passes both guards on both sides.

    Yields:
        Path: an existing, empty directory, removed after the test.
    """
    path = Path(STATIC_DIR).resolve() / ".pytest-repl-worker" / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
