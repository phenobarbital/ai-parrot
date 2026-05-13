"""Verify that the legacy AbstractDBAgent module has been hard-deleted (FEAT-164)."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_abstractdbagent_deleted_from_init() -> None:
    """from parrot.bots.database import AbstractDBAgent raises ImportError."""
    with pytest.raises(ImportError):
        from parrot.bots.database import AbstractDBAgent  # noqa: F401


def test_abstract_module_file_absent() -> None:
    """The abstract.py file no longer exists on disk."""
    import parrot.bots.database as pkg

    pkg_dir = Path(pkg.__file__).parent
    assert not (pkg_dir / "abstract.py").exists()
