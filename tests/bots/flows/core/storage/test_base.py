"""Tests for ResultStorage ABC — ensures it cannot be instantiated directly."""
import pytest
from parrot.bots.flows.core.storage.backends import ResultStorage


def test_resultstorage_is_abstract():
    """ResultStorage cannot be instantiated directly (it is an ABC)."""
    with pytest.raises(TypeError):
        ResultStorage()  # type: ignore[abstract]
