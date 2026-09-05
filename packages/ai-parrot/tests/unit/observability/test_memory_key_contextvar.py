"""Unit tests for FEAT-525 current_memory_key_id ContextVar."""

from parrot.observability.context import current_memory_key_id, invocation_context


def test_contextvar_default_and_restore():
    assert current_memory_key_id.get() is None
    with invocation_context("a", user_id="u", session_id="s", memory_key_id="k"):
        assert current_memory_key_id.get() == "k"
        with invocation_context("b", memory_key_id="k2"):
            assert current_memory_key_id.get() == "k2"
        assert current_memory_key_id.get() == "k"
    assert current_memory_key_id.get() is None
