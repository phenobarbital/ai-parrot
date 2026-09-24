"""The package conftest keeps tests off real DocumentDB."""

import time

import pytest

from parrot.interfaces.documentdb import DocumentDb


async def test_documentdb_connect_fails_fast() -> None:
    """``async with DocumentDb()`` raises ConnectionError immediately under the guard."""
    start = time.monotonic()
    with pytest.raises(ConnectionError, match="disabled in unit tests"):
        async with DocumentDb():
            pass
    assert time.monotonic() - start < 1.0
