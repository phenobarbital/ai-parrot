"""Tests for ResultStorage ABC — ensures it cannot be instantiated directly."""
import pytest
from parrot.bots.flows.core.storage.backends import ResultStorage


def test_resultstorage_is_abstract():
    """ResultStorage cannot be instantiated directly (it is an ABC)."""
    with pytest.raises(TypeError):
        ResultStorage()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_fetch_default_raises():
    """The default fetch() implementation raises NotImplementedError.

    This keeps pre-existing third-party ResultStorage subclasses (that
    predate the read API) importable and instantiable without implementing
    fetch() themselves.
    """

    class Minimal(ResultStorage):
        async def save(self, collection, document):
            ...

        async def close(self):
            ...

    with pytest.raises(NotImplementedError):
        await Minimal().fetch("c", "eid")
