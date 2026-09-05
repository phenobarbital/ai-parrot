"""Fake entry-point target for ``test_factory_discovery.py`` (TASK-2847).

Not a real provider — just something ``importlib.metadata.EntryPoint.load()``
can resolve via the dotted path ``tests.unit.clients.fakes:FakeClient`` so
the discovery test can exercise the entry-point branch of
``parrot.clients.factory._discover()`` without a real satellite installed.

FEAT-523 (TASK-2853): once every real provider was extracted to its own
satellite, ``_IN_CORE_PROVIDERS`` became empty — ``test_list_models_
active_deprecated`` / ``test_list_providers_lists_in_core_keys`` can no
longer assert against a real in-core provider (that would make core's own
test suite depend on a satellite being installed), so ``FakeClient`` also
carries ``models``/``deprecated_models`` for those two tests to exercise
via a mocked entry point.
"""

from enum import Enum


class FakeModel(str, Enum):
    """Minimal model enum for ``FakeClient.models``."""

    FAKE_ACTIVE = "fake-active-model"


class FakeClient:
    """Stand-in client class for a mocked ``parrot.clients`` entry point."""

    provider_keys = ("test-provider",)
    models = FakeModel
    deprecated_models = {"fake-deprecated-model": "fake-active-model"}
