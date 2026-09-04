"""Fake entry-point target for ``test_factory_discovery.py`` (TASK-2847).

Not a real provider — just something ``importlib.metadata.EntryPoint.load()``
can resolve via the dotted path ``tests.unit.clients.fakes:FakeClient`` so
the discovery test can exercise the entry-point branch of
``parrot.clients.factory._discover()`` without a real satellite installed.
"""


class FakeClient:
    """Stand-in client class for a mocked ``parrot.clients`` entry point."""

    provider_keys = ("test-provider",)
