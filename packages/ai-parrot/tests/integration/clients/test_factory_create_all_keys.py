"""TASK-2855: every key `LLMFactory._discover()` registers must resolve to
a real `AbstractClient` subclass that actually answers to that key.

Requires all 15 satellites installed — see `test_import_all_client_paths.py`
for the same caveat.
"""
from parrot.clients.base import AbstractClient
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS


def test_every_key_resolves_to_declared_client():
    LLMFactory._discover()
    for key, entry in SUPPORTED_CLIENTS.items():
        cls = entry() if callable(entry) and not isinstance(entry, type) else entry
        assert issubclass(cls, AbstractClient) and key in cls.provider_keys, key
